import math

from alternativa.model import Codec

ANGLE_FACTOR = math.pi / 4096
ANGULAR_VELOCITY_FACTOR = 0.005
POSITION_COMPONENT_BITSIZE = 17
ORIENTATION_COMPONENT_BITSIZE = 13
LINEAR_VELOCITY_COMPONENT_BITSIZE = 13
ANGULAR_VELOCITY_COMPONENT_BITSIZE = 13
BIT_AREA_SIZE = 21

def read_vector3(area, bits, factor):
    x = (area.read(bits) - (1 << bits - 1)) * factor
    y = (area.read(bits) - (1 << bits - 1)) * factor
    z = (area.read(bits) - (1 << bits - 1)) * factor
    return x, y, z

class BitArea:
    def __init__(self, data, size):
        self.data = data
        self.size = size
        self.position = 0
        self.length = size * 8

    def get_bit(self, bit):
        position = bit >> 3
        shift = (7 ^ bit) & 7
        return (self.data[position] & (1 << shift)) != 0

    def read(self, bits):
        value = 0
        bits = bits - 1
        while bits >= 0:
            if self.get_bit(self.position):
                value = value + (1 << bits)
            self.position += 1
            bits -= 1
        return value

class TankState(Codec):
    def read(self, packet, optional):
        data = super().read(packet, optional)
        area = BitArea(packet.readBytes(BIT_AREA_SIZE), BIT_AREA_SIZE)
        position = read_vector3(area, POSITION_COMPONENT_BITSIZE, 1)
        orientation = read_vector3(area, ORIENTATION_COMPONENT_BITSIZE, ANGLE_FACTOR)
        lin_velocity = read_vector3(area, LINEAR_VELOCITY_COMPONENT_BITSIZE, 1)
        ang_velocity = read_vector3(area, ANGULAR_VELOCITY_COMPONENT_BITSIZE, ANGULAR_VELOCITY_FACTOR)
        data['angularVelocity'] = ang_velocity
        data['linearVelocity'] = lin_velocity
        data['orientation'] = orientation
        data['position'] = position
        return data
