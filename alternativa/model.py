from collections import defaultdict
from alternativa import protocol

class Codec():
    def read(self, packet, optional):
        return {'codec': type(self).__name__}

class GameClass(Codec):
    def read(self, packet):
        data = super().read(packet, None)
        data['class_id'] = packet.readLong()
        data['models'] = [packet.readLong() for _ in range(packet.readInt())]
        return data

class GameObject(Codec):
    def read(self, packet):
        data = super().read(packet, None)
        data['object_id'] = packet.readLong()
        data['class_id'] = packet.readLong()
        return data

class ModelData(Codec):
    def read(self, packet, optional, reader):
        data = super().read(packet, None)
        model_id = packet.readLong()
        data['model_id'] = model_id
        if model_id == 0:
            data['data'] = packet.readLong()
        else:
            data['data'] = reader.read(packet, optional, model_id)
        return data

class ObjectsDependenciesCodec(Codec):
    def __init__(self, reader):
        self.reader = reader

    def read(self, packet, optional):
        data = super().read(packet, optional)
        data['callback_id'] = packet.readInt()
        self._read_game_classes(packet, data)
        self._read_resources(packet, data)
        return data

    def _read_game_classes(self, packet, data):
        codec = GameClass()
        data['game_classes'] = [codec.read(packet) for _ in range(packet.readInt())]

    def _read_resources(self, packet, data):
        resources = list()
        for _ in range(packet.readInt()):
            dependencies = list()
            res = self._read_resource_info(packet)
            for _ in range(packet.readByte()):
                dependencies.append(packet.readLong())
            res['dependencies'] = dependencies
            resources.append(res)
        data['resources'] = resources

    def _read_resource_info(self, packet):
        return {
            'id': packet.readLong(),
            'type': packet.readShort(),
            'version': packet.readLong(),
            'lazy': bool(packet.readByte())
        }

class ObjectsDataCodec(Codec):
    def __init__(self, reader):
        self.reader = reader

    def read(self, packet, optional):
        data = super().read(packet, optional)
        self._read_objects(packet, data)
        self._read_models_data(packet, optional, data)
        return data

    def _read_objects(self, packet, data):
        codec = GameObject()
        data['objects'] = [codec.read(packet) for _ in range(packet.readInt())]

    def _read_models_data(self, packet, optional, data):
        codec = ModelData()
        models = list()
        for _ in range(packet.readInt()):
            model_data = codec.read(packet, optional, self.reader)
            model_id = model_data['model_id']
            if not model_data['data']:
                raise Exception(f'Unknown model ({model_id}), last codec: {prev}')
            models.append(model_data)
            prev = model_id
        data['models'] = models

class ModelReader():
    def __init__(self):
        from alternativa import codecs
        self.codecs = codecs.CODECS
        self.codecs[3216143066888387731] = ObjectsDependenciesCodec(self)
        self.codecs[7640916300855664666] = ObjectsDataCodec(self)

    def read(self, packet, optional, model_id):
        if model_id in self.codecs:
            return self.codecs[model_id].read(packet, optional)
        return None

    def get_codec_name(self, model_id):
        return type(self.codecs[model_id]).__name__ if model_id in self.codecs else None
