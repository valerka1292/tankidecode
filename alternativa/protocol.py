import sys
import zlib
import struct

from alternativa import util, model

# PacketHelper flags
BIG_LENGTH_FLAG = 128
ZIPPED_FLAG = 64

# OptionalMapCodecHelper flags
INPLACE_MASK_1_BYTES = 0x20
INPLACE_MASK_2_BYTES = 0x40
INPLACE_MASK_3_BYTES = 0x60
INPLACE_MASK_FLAG = 0x80
MASK_LENGTH_1_BYTE = 0x80
MASK_LENGTH_3_BYTE = 0xC00000

def decode_null_map(data):
    flag = data.readByte()

    if ((flag & INPLACE_MASK_FLAG) != 0):
        length = flag & 0x3F
        if ((flag & INPLACE_MASK_2_BYTES) != 0):
            length = (length << 16) + ((data.readByte() & 0xFF) << 8) + (data.readByte() & 0xFF)
        map = util.ByteArray(data.readBytes(length))
        return OptionalMap(length << 3, map)

    length = (flag & 0x60) >> 5
    flag = flag << 3
    map = util.ByteArray()
    if length == 0:
        map.writeByte(flag)
        size = 5
    elif length == 1:
        map1 = data.readByte()
        map.writeByte(flag + ((map1 & 0xFF) >> 5))
        map.writeByte(map1 << 3)
        size = 13
    elif length == 2:
        map1, map2 = data.readByte(), data.readByte()
        map.writeByte(flag + ((map1 & 0xFF) >> 5))
        map.writeByte((map1 << 3) + ((map2 & 0xFF) >> 5))
        map.writeByte(map2 << 3)
        size = 21
    elif length == 3:
        map1, map2, map3 = data.readByte(), data.readByte(), data.readByte()
        map.writeByte(flag + ((map1 & 0xFF) >> 5))
        map.writeByte((map1 << 3) + ((map2 & 0xFF) >> 5))
        map.writeByte((map2 << 3) + ((map3 & 0xFF) >> 5))
        map.writeByte(map3 << 3)
        size = 29
    else:
        raise AssertionError()

    return OptionalMap(size, map)

# alternativa.protocol.impl.PacketHelper (unwrapPacket)
def unwrap_packet(data):
    if data.bytesAvailable() < 2:
        return
    flag = data.readByte()
    if flag & BIG_LENGTH_FLAG:
        if data.bytesAvailable() >= 3:
            compressed = False
            byte0 = (flag ^ BIG_LENGTH_FLAG) << 24
            byte1 = (data.readByte() & 0xFF) << 16
            byte2 = (data.readByte() & 0xFF) << 8
            byte3 = data.readByte() & 0xFF
            length = byte0 + byte1 + byte2 + byte3
        else:
            return
    else:
        compressed = flag & ZIPPED_FLAG
        byte0 = (flag & 63) << 8
        byte1 = data.readByte() & 0xFF
        length = byte0 + byte1

    if data.bytesAvailable() < length:
        return
    unwrapped = util.ByteArray(data.readBytes(length))
    assert unwrapped.bytesAvailable() == length
    if compressed:
        compressed = unwrapped.readBytes()
        print('Compressed:', compressed.hex())
        unzipped = zlib.decompress(compressed, -15)
        unwrapped = util.ByteArray(unzipped)
    return unwrapped

def decode_length(data):
    byte0 = data.readByte()
    if byte0 & 0x80 == 0:
        return byte0
    byte1 = data.readByte()
    if byte0 & 0x40 == 0:
        return ((byte0 & 0x3F) << 8) + (byte1 & 0xFF)
    byte2 = data.readByte()
    return ((byte0 & 0x3F) << 16) + ((byte1 & 0xFF) << 8) + (byte2 & 0xFF)

class OptionalMap(object):
    def __init__(self, size, map):
        self.size = size
        self.map = map
        self.position = 0

    def next(self):
        if self.position > self.size:
            raise IndexError('No more optional bits')

        optional = self.get_bit(self.position)
        self.position += 1
        return optional

    def get_bit(self, bit):
        self.map.position = bit >> 3
        shift = (7 ^ bit) & 7
        return (self.map.readByte() & (1 << shift)) != 0

    def __str__(self):
        tmp = self.position
        self.position = 0
        bits = ''
        while self.position < self.size:
            bits += '1' if self.next() else '0'
        self.position = tmp
        return f'OptionalMap[pos={tmp},bits={bits},size={self.size}]'

class Command(object):
    def __init__(self, command_type):
        self.command_type = command_type
        self.data = None

class ControlCommand(Command):
    def __init__(self, command_id):
        super().__init__('control')
        self.command_id = command_id

class SpaceCommand(Command):
    def __init__(self, object_id, method_id):
        super().__init__('space')
        self.object_id = object_id
        self.method_id = method_id

class Decoder(object):
    def decode(self, data, optional):
        pass

class ClientControlCommandDecoder(Decoder):
    def __init__(self):
        self.types = {
            1: 'CL_HASH_REQUEST',
            3: 'CL_SPACE_OPENED',
            32: 'CL_LOG',
            10: 'CL_COMMAND_RESPONSE'
        }

    def decode(self, data, optional):
        command_id = int(data.readByte())
        command = ControlCommand(command_id)
        if command_id == 1:
            keys = list()
            for _ in range(decode_length(data)):
                string = data.readBytes(decode_length(data))
                keys.append(string.decode('utf-8'))
            values = list()
            for _ in range(decode_length(data)):
                string = data.readBytes(decode_length(data))
                values.append(string.decode('utf-8'))
            command.data = {'params': dict(zip(keys, values))}
        elif command_id == 3:
            prot_hash = data.readBytes(32).hex()
            space_id, = struct.unpack('>Q', data.readBytes(8))
            command.data = {'hash': prot_hash, 'space_id': space_id}
        return command

class ServerControlCommandDecoder(Decoder):
    def __init__(self):
        self.types = {
            2: 'SV_HASH_RESPONSE',
            32: 'SV_OPEN_SPACE',
            35: 'SV_MESSAGE',
            9: 'SV_COMMAND_REQUEST'
        }

    def decode(self, data, optional):
        command_id = int(data.readByte())
        command = ControlCommand(command_id)
        if command_id == 2:
            prot_hash = data.readBytes(32).hex()
            prot = bool(data.readByte())
            command.data = {'hash': prot_hash, 'encrypt': prot}
        elif command_id == 32:
            space_id, = struct.unpack('>Q', data.readBytes(8))
            command.data = {'space_id': space_id}
        return command

class SpaceCommandDecoder(Decoder):
    def __init__(self):
        self.reader = model.ModelReader()

    def decode(self, data, optional):
        object_id, method_id = struct.unpack('>QQ', data.readBytes(16))
        command = SpaceCommand(object_id, method_id)
        command.data = self.reader.read(data, optional, method_id)
        if not command.data:
            raise Exception(f'Unknown model ({method_id})')

        return command

class XorProtection(object):
    def __init__(self, hash, id_high, id_low, client):
        self.client = client
        self.initialSeed = 0
        for i in range(32):
            self.initialSeed ^= hash[i]
        self.initialSeed ^= (id_high >> 24) & 0xFF
        self.initialSeed ^= (id_high >> 16) & 0xFF
        self.initialSeed ^= (id_high >> 8) & 0xFF
        self.initialSeed ^= id_high & 0xFF
        self.initialSeed ^= (id_low >> 24) & 0xFF
        self.initialSeed ^= (id_low >> 16) & 0xFF
        self.initialSeed ^= (id_low >> 8) & 0xFF
        self.initialSeed ^= id_low & 0xFF
        if self.initialSeed >= 128:
            self.initialSeed -= 256
        self.reset()

    def reset(self):
        self.serverSequence = list(self.initialSeed ^ (i << 3) for i in range(8))
        self.clientSequence = list((self.initialSeed ^ (i << 3)) ^ 87 for i in range(8))
        self.serverSelector = 0
        self.clientSelector = 0

    def unwrapClient(self, data):
        output = util.ByteArray()
        for byte in data:
            if byte >= 128:
                byte -= 256
            self.clientSequence[self.clientSelector] = byte ^ self.clientSequence[self.clientSelector]
            output.writeByte(self.clientSequence[self.clientSelector])
            self.clientSelector ^= self.clientSequence[self.clientSelector] & 7
        return output.data

    def unwrap(self, data):
        if self.client:
            return self.unwrapClient(data)
        output = util.ByteArray()
        for byte in data:
            if byte >= 128:
                byte -= 256
            self.serverSequence[self.serverSelector] = byte ^ self.serverSequence[self.serverSelector]
            output.writeByte(self.serverSequence[self.serverSelector])
            self.serverSelector ^= self.serverSequence[self.serverSelector] & 7
        return output.data
