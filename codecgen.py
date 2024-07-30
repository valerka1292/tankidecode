#!/usr/bin/env python3
import collections
import datetime
import argparse
import json
import glob
import os
import io

class StringReader():
    def __init__(self, string):
        self.string = string
        self.cursor = 0
    
    def peek(self):
        return self.string[self.cursor:self.cursor+1]
    
    def peek_remaining(self):
        return self.string[self.cursor:]

    def consume(self):
        peeked = self.peek()
        self.cursor += 1
        return peeked

    def consume_whitespace(self):
        while self.peek() and self.peek() in ' \r\n\t':
            self.consume()

    def consume_until(self, substr):
        try:
            index = self.string[self.cursor:].index(substr)
        except ValueError:
            index = len(self.string) - 1
        consumed = self.string[self.cursor:self.cursor+index]
        self.cursor += index + len(substr)
        return consumed

    def expect(self, *args):
        substr = ''.join(args)
        length = len(substr)
        if self.string[self.cursor:self.cursor+length] != substr:
            raise ValueError('Expected substring not matched')
        self.cursor += length

class ClassReader(StringReader):
    def __init__(self, code):
        super().__init__(code)
        self.package = self.read_package()
        self.class_name = self.read_class_name().rstrip()

    def read_package(self):
        self.expect('package ')
        return self.consume_until('\n')

    def read_class_name(self):
        self.consume_until('class ')
        # TODO: not always correct!
        return self.consume_until(' ')

    def read_assignments(self):
        assignments, discards = list(), list()
        while self.peek() != '}':
            line = self.consume_until(';')
            self.consume_whitespace()
            if '=' not in line:
                discards.append(line)
                continue

            assignments.append(line.split(' = '))
        return assignments, discards

    def read_get_long(self, expr):
        expr.expect('Long.getLong(')
        high = int(expr.consume_until(','))
        low = int(expr.consume_until(')'))
        return (high << 32) | (low & 0xFFFFFFFF)

class ClassWriter():
    def __init__(self, indent=4):
        self.indent = indent
        self.buf = io.StringIO()
        self.level = 0

    def up(self):
        self.level += 1
        return self
    
    def down(self):
        self.level -= 1
        return self

    def line(self, line):
        self.buf.write(' ' * (self.level * self.indent))
        self.buf.write(line + '\n')
        return self

class CodecInfo():
    def __init__(self, info_type, optional):
        self.info_type = info_type
        self.optional = optional

class TypeCodecInfo(CodecInfo):
    def __init__(self, info_type, type_name, optional):
        super().__init__(info_type, optional)
        self.type_name = type_name

    def __repr__(self):
        return f'<info={self.info_type},type={self.type_name},optional={self.optional}>'

class CollectionCodecInfo(CodecInfo):
    def __init__(self, element_type, optional):
        super().__init__('CollectionCodecInfo', optional)
        self.element_type = element_type

    def __repr__(self):
        return f'<collection={self.element_type},optional={self.optional}>'

class TypeInfoReader(StringReader):
    def __init__(self, expr):
        super().__init__(expr)
    
    def read_get_codec(self):
        self.consume_until('getCodec(')
        return self.read()

    def read(self):
        self.expect('new ')
        info_type = self.consume_until('(')

        if info_type == 'TypeCodecInfo' or info_type == 'EnumCodecInfo':
            type_name = self.consume_until(',')
            optional = self.consume_until(')') == 'true'
            type_info = TypeCodecInfo(info_type, type_name, optional)
        elif info_type == 'CollectionCodecInfo':
            element_type = self.read()
            self.expect(',')
            optional = self.consume_until(',') == 'true'
            level = self.consume_until(')')
            assert level == '1'
            type_info = CollectionCodecInfo(element_type, optional)
        else:
            raise ValueError(f'Unknown TypeCodecInfo type: {info_type}')

        return type_info

class ModelDefinition():
    def update_references(self, codecs):
        pass

    def get_codec(self, codecs):
        pass

class ModelCC(ModelDefinition):
    def __init__(self, model_id, class_name, type_info):
        self.model_id = model_id
        self.class_name = class_name
        self.type_info = type_info

    def update_references(self, codecs):
        if self.type_info:
            codecs[self.type_info.type_name].references += 1

    def get_codec(self, codecs):
        if not self.type_info: # void constructor
            return CodecDefinition(self.class_name)
        cc_type = self.type_info.type_name
        codec = codecs[cc_type]
        if codec.references > 1:
            return CodecDefinition(self.class_name, inherits=cc_type)
        return codec

    def __repr__(self):
        return f'<class_name={self.class_name},model_id={self.model_id},type={self.type_info}>'

class ModelMethod(ModelDefinition):
    def __init__(self, model_id, class_name, method_name):
        self.model_id = model_id
        self.class_name = class_name
        self.method_name = method_name
        self.fields = dict()

    def get_codec(self, codecs):
        codec_name = '_'.join([self.class_name, self.method_name])
        return CodecDefinition(codec_name, self.fields)

class ModelDefinitionReader(ClassReader):
    def __init__(self, code):
        super().__init__(code)
        self.method_ids, self.method_types = self.read_methods()

    def read_methods(self):
        method_ids = self.read_method_ids()
        method_types = self.read_method_types()
        return method_ids, method_types

    def read_method_ids(self):
        self.consume_until('public function ')
        self.expect(self.class_name, '()')
        self.consume_whitespace()
        self.expect('{')
        self.consume_whitespace()

        method_ids = dict()
        assignments, _ = self.read_assignments()
        for var, expr in assignments:
            if 'Id' not in var:
                continue
            var = var[5:-2].lstrip('_') # this.modelId or this._<field>Id
            expr = StringReader(expr)
            method_ids[var] = self.read_get_long(expr)

        return method_ids

    def read_method_types(self):
        self.consume_until('function ')
        self.expect('initCodecs() : void')
        self.consume_whitespace()
        self.expect('{')
        self.consume_whitespace()

        method_types = dict()
        assignments, discards = self.read_assignments()
        for var, expr in assignments:
            if var == 'this.server':
                expr = StringReader(expr)
                expr.expect('new ')
                self.server_model = expr.consume_until('(')
                continue

            if 'getCodec' in expr:
                var = var[6:-5] # this._<field>Codec
                method_types[var] = TypeInfoReader(expr).read_get_codec()

        for line in discards:
            if 'getCodec' in line:
                type_info = TypeInfoReader(line)
                method_types['model'] = type_info.read_get_codec()
                break

        return method_types

    def get_type_definitions(self):
        models = dict()
        cc_id = self.method_ids.pop('model', None)
        if cc_id: # server models don't have one
            cc_type = self.method_types.pop('model', None)
            model = ModelCC(cc_id, self.class_name, cc_type)
            models['model'] = model

        for method_name, model_id in self.method_ids.items():
            models[method_name] = ModelMethod(model_id, self.class_name, method_name)

        for var, type_info in self.method_types.items():
            method_name, param = var.split('_')
            model = models[method_name]
            model.fields[param] = type_info

        return models.values()

class ModelServerDefinitionReader(ModelDefinitionReader):
    def __init__(self, code):
        super().__init__(code)

    def read_methods(self):
        self.consume_until('public function ')
        self.expect(self.class_name, '(param1:IModel)')
        self.consume_whitespace()
        self.expect('{')
        self.consume_whitespace()

        method_ids, method_types = dict(), dict()
        assignments, _ = self.read_assignments()
        for var, expr in assignments:
            if 'getLong' in expr:
                var = var[6:-2] # this._<field>Id
                expr = StringReader(expr)
                method_ids[var] = self.read_get_long(expr)
            elif 'getCodec' in expr:
                var = var[6:-5] # this._<field>Codec
                method_types[var] = TypeInfoReader(expr).read_get_codec()

        return method_ids, method_types

class CodecDefinition():
    def __init__(self, name, fields=None, inherits=None):
        self.name = name
        self.fields = fields or dict()
        self.inherits = inherits or 'Codec'
        self.references = 0
        self.code = None

    def write(self, writer):
        self.code, dependencies = writer.write(self)
        return dependencies

    def __repr__(self):
        return f'<name={self.name},fields={self.fields}>'

class CodecReader(ClassReader):
    def __init__(self, code):
        super().__init__(code)

    def read(self):
        self.consume_until('function init')
        self.expect('(param1:IProtocol) : void')
        self.consume_whitespace()
        self.expect('{')
        self.consume_whitespace()

        fields = dict()
        assignments, _ = self.read_assignments()
        for var, expr in assignments:
            var = var[11:]
            fields[var] = TypeInfoReader(expr).read_get_codec()

        codec_name = self.class_name
        if codec_name.startswith('Codec'):
            codec_name = codec_name[5:]
        return CodecDefinition(codec_name, fields)

class CodecDefinitionWriter():
    PRIMITIVES = {
        'Byte': 'packet.readByte()',
        'Short': 'packet.readShort()',
        'int': 'packet.readInt()',
        'Long': 'packet.readLong()',
        'Float': 'packet.readFloat()',
        'Number': 'packet.readDouble()',
        'Boolean': 'bool(packet.readByte())',
        'String': 'packet.readString()',
        'IGameObject': 'packet.readLong()',
        'Date': 'packet.readLong()'
    }
    def __init__(self, codecs):
        self.codecs = codecs

    def emit_type_call(self, type_info, dependencies):
        call = None
        if type_info.info_type == 'CollectionCodecInfo':
            call = self.emit_type_call(type_info.element_type, dependencies)
        else:
            field_type = type_info.type_name
            if type_info.info_type == 'EnumCodecInfo':
                field_type = 'int'

            if field_type in self.PRIMITIVES:
                call = self.PRIMITIVES[field_type]
            elif field_type in self.codecs:
                field_codec = self.codecs[field_type]
                call = f'{field_codec.name}().read(packet, optional)'
                if field_codec not in dependencies:
                    dependencies.append(field_codec)
            elif field_type.endswith('Resource'):
                call = 'packet.readLong()'

        if not call:
            return None

        if type_info.info_type == 'CollectionCodecInfo':
            call = f'[{call} for _ in range(protocol.decode_length(packet))]'

        if type_info.optional:
            call = f'None if optional.next() else {call}'

        return call

    def write(self, codec):
        dependencies = list()
        if codec.inherits != 'Codec':
            dependencies.append(self.codecs[codec.inherits])
        writer = ClassWriter()
        writer.line(f'class {codec.name}({codec.inherits}):').up()
        if not codec.fields:
            writer.line('pass')
            return writer.buf.getvalue(), dependencies
        writer.line('def read(self, packet, optional):').up()
        writer.line('data = super().read(packet, optional)')
        for field, type_info in codec.fields.items():
            call = self.emit_type_call(type_info, dependencies)
            if not call:
                print('Cannot decode:', type_info)
            writer.line(f"data['{field}'] = {call}")

        writer.line('return data')
        return writer.buf.getvalue(), dependencies

def classes_by_keyword(path, keyword, sort=False):
    classes = list()
    for fname in glob.glob(os.path.join(path, '**/*.as'), recursive=True):
        with open(fname, 'r', encoding='utf-8') as f:
            code = f.read()
        if keyword in code:
            classes.append(ClassReader(code))
    if sort:
        classes.sort(key=lambda x: x.class_name)
    return classes

def generate(path, filename, comments=None):
    codecs = dict()
    for code in classes_by_keyword(path, 'implements ICodec'):
        reader = CodecReader(code.string)
        if reader.class_name.startswith('Vector') or 'MapCodecInfo' in code.string:
            continue

        try:
            codec = reader.read()
            codecs[codec.name] = codec
        except ValueError:
            print(f'Cannot read: {reader.package}.{reader.class_name}')

    server_models = dict()
    for code in classes_by_keyword(path, 'ModelServer'):
        if not 'ModelServer' in code.class_name:
            continue

        reader = ModelServerDefinitionReader(code.string)
        server_models[reader.class_name] = reader.get_type_definitions()

    models = list()
    for code in classes_by_keyword(path, 'extends Model', sort=True):
        reader = ModelDefinitionReader(code.string)
        for model in reader.get_type_definitions():
            model.update_references(codecs)
            models.append(model)
        models += server_models[reader.server_model]

    writer = ClassWriter()
    writer.line('CODECS = {').up()
    to_write = collections.deque()
    for model in models:
        codec = model.get_codec(codecs)
        writer.line(f'{model.model_id}: {codec.name}(),')
        to_write.appendleft(codec)
    writer.down().line('}')

    now = datetime.datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S GMT')
    prelude = ClassWriter()
    prelude.line(f'# Codec definitions autogenerated on {now}')
    if comments:
        for line in comments:
            prelude.line(f'# {line}')

    prelude.line('from alternativa.model import Codec')
    prelude.line('from alternativa import protocol')
    sections = [prelude.buf.getvalue()]

    written = set()
    codec_writer = CodecDefinitionWriter(codecs)
    while to_write:
        codec = to_write.pop()
        if codec in written:
            continue
        if codec.code:
            sections.append(codec.code)
            written.add(codec)
            continue

        dependencies = codec.write(codec_writer)
        to_write.append(codec)
        to_write += dependencies

    sections.append(writer.buf.getvalue())
    with open(filename, 'w') as f:
        f.write('\n'.join(sections))

    print(f'Generated {len(written)} codecs')

def main():
    parser = argparse.ArgumentParser(description='Generate Python codecs from Tanki Online sources.')
    parser.add_argument('path', help='path to scan for sources')
    parser.add_argument('filename', nargs='?', default='alternativa/codecs.py', help='generated codecs file')
    args = parser.parse_args()

    generate(args.path, args.filename)

if __name__ == '__main__':
    main()
