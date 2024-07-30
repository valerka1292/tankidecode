import struct

from alternativa import protocol

class ByteArray(object):
    def __init__(self, data=None):
        self.data = data if data else bytearray()
        self.position = 0

    def writeByte(self, byte):
        self.data += struct.pack('>B', byte & 0xFF)
        self.position += 1

    def readByte(self):
        if not self.bytesAvailable():
            raise IndexError('Tried to read more bytes than available')
        byte = self.data[self.position]
        self.position += 1
        return byte

    def readBytes(self, length=None):
        if length is None:
            length = self.bytesAvailable()
        if length > self.bytesAvailable():
            raise IndexError('Tried to read more bytes than available')
        bytes = self.data[self.position:self.position+length]
        self.position += len(bytes)
        return bytes

    def readShort(self):
        return struct.unpack('>h', self.readBytes(2))[0]

    def readInt(self):
        return struct.unpack('>i', self.readBytes(4))[0]

    def readLong(self):
        return struct.unpack('>q', self.readBytes(8))[0]

    def readFloat(self):
        return struct.unpack('>f', self.readBytes(4))[0]

    def readDouble(self):
        return struct.unpack('>d', self.readBytes(8))[0]

    def readString(self):
        length = protocol.decode_length(self)
        return self.readBytes(length).decode('utf-8')

    def readIntVector(self):
        vector = list()
        for _ in range(protocol.decode_length(self)):
            vector.append(self.readInt())
        return vector

    def readLongVector(self):
        vector = list()
        for _ in range(protocol.decode_length(self)):
            vector.append(self.readLong())
        return vector

    def bytesAvailable(self):
        return len(self.data) - self.position

    def clear(self):
        self.data = bytearray()
        self.position = 0

    def hex(self):
        return self.data.hex()

    def __add__(self, other):
        self.data += other.data
        self.position += len(other.data)
        return self

    def __len__(self):
        return len(self.data)

    def __str__(self):
        tmp = self.position
        data = self.readBytes()
        self.position = tmp
        return str(data)
