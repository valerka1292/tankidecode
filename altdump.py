#!/usr/bin/env python3
import traceback
import datetime
import argparse
import struct
import base64
import queue
import time
import os
import sys

import simplejson

from alternativa import protocol, util

RECORD_BEGIN = 1
RECORD_DATA = 2
RECORD_END = 3

class Record():
    def __init__(self, rec_type, conn_id, outgoing, when=None):
        self.rec_type = rec_type
        self.conn_id = conn_id
        self.outgoing = outgoing
        self.time = when or time.time()

    def write(self, f):
        flags = (self.rec_type << 4) | self.outgoing
        f.write(struct.pack('>BH', flags, self.conn_id))

class RecordBegin(Record):
    def __init__(self, conn_id, outgoing, src, dst, when=None):
        super().__init__(RECORD_BEGIN, conn_id, outgoing, when=when)
        self.src_addr = src
        self.dst_addr = dst

    def write(self, f):
        super().write(f)
        src_ip, src_port = self.src_addr
        dst_ip, dst_port = self.dst_addr
        f.write(struct.pack('>HB', src_port, len(src_ip)))
        f.write(src_ip.encode('utf-8'))
        f.write(struct.pack('>HB', dst_port, len(dst_ip)))
        f.write(dst_ip.encode('utf-8'))

class RecordData(Record):
    def __init__(self, conn_id, outgoing, data, when=None):
        super().__init__(RECORD_DATA, conn_id, outgoing, when=when)
        self.data = data

    def write(self, f):
        super().write(f)
        f.write(struct.pack('>I', len(self.data)))
        f.write(self.data)

class RecordEnd(Record):
    def __init__(self, conn_id, outgoing, when=None):
        super().__init__(RECORD_END, conn_id, outgoing, when=when)

class PacketWriter():
    def __init__(self, fname):
        self.fname = fname
        self.start = time.time()
        self.start_millis = int(self.start * 1000)
        self.f = None

    def write(self, record):
        diff = int((record.time - self.start) * 1000)
        self.f.write(struct.pack('>I', diff))
        record.write(self.f)
        self.f.flush()

    def _write_header(self):
        millis = int(self.start * 1000)
        self.f.write(b'TNK')
        self.f.write(struct.pack('>Q', millis))

    def __enter__(self):
        self.f = open(self.fname, 'wb')
        self._write_header()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.f.close()

class PacketReader():
    def __init__(self, f):
        file_header = f.read(11)
        if file_header[:3] != b'TNK':
            raise ValueError('Invalid magic')
        self.start, = struct.unpack('>Q', file_header[3:])
        self.f = f

    def __iter__(self):
        return self

    def __next__(self):
        header = self.f.read(7)
        if not header:
            raise StopIteration()

        time, flags, connection_id = struct.unpack('>IBH', header)
        time, record_type, outgoing = self.start + time, flags >> 4, bool(flags & 1)
        if record_type == RECORD_BEGIN:
            src_port, src_ip_len = struct.unpack('>HB', self.f.read(3))
            src_ip = self.f.read(src_ip_len).decode('utf-8')
            dst_port, dst_ip_len = struct.unpack('>HB', self.f.read(3))
            dst_ip = self.f.read(dst_ip_len).decode('utf-8')
            return RecordBegin(connection_id, outgoing, (src_ip, src_port), (dst_ip, dst_port), when=time)
        elif record_type == RECORD_DATA:
            length, = struct.unpack('>I', self.f.read(4))
            return RecordData(connection_id, outgoing, self.f.read(length), when=time)
        elif record_type == RECORD_END:
            return RecordEnd(connection_id, outgoing, when=time)
        else:
            raise ValueError(f'Invalid record type ({record_type})')

class Event():
    def __init__(self, evt_type, record):
        self.type = evt_type
        self.time = datetime.datetime.utcfromtimestamp(record.time / 1000).isoformat()
        self.connection_id = record.conn_id
        self.outgoing = record.outgoing

    def to_dict(self):
        return self.__dict__.copy()

class BeginEvent(Event):
    def __init__(self, record):
        super().__init__('begin', record)
        src_ip, src_port = record.src_addr
        dst_ip, dst_port = record.dst_addr
        self.source = f'{src_ip}:{src_port}'
        self.destination = f'{dst_ip}:{dst_port}'

class EndEvent(Event):
    def __init__(self, record):
        super().__init__('end', record)

class CommandEvent(Event):
    def __init__(self, record, record_id, command):
        super().__init__('command', record)
        self.record_id = record_id
        self.command = command.__dict__

    def to_dict(self):
        data = super().to_dict()
        data.update(data.pop('command'))
        return data

class ProtocolEventReader(PacketReader):
    def __init__(self, f):
        super().__init__(f)
        self.control = [
            protocol.ServerControlCommandDecoder(),
            protocol.ClientControlCommandDecoder()
        ]
        self.space = protocol.SpaceCommandDecoder()
        self.in_space = dict()
        self.queue = list()
        self.i = 0

    def _next_record(self):
        record = super().__next__()
        if record.rec_type == RECORD_BEGIN:
            self.in_space[record.conn_id] = False
            self.queue.append(BeginEvent(record))
        elif record.rec_type == RECORD_END:
            self.queue.append(EndEvent(record))
        elif record.rec_type == RECORD_DATA:
            packet = util.ByteArray(record.data)
            optional_map = protocol.decode_null_map(packet)
            space_conn = self.in_space[record.conn_id]
            decoder = self.space if space_conn else self.control[record.outgoing]
            while packet.bytesAvailable():
                try:
                    command = decoder.decode(packet, optional_map)
                except:
                    traceback.print_exc()
                    dummy = protocol.SpaceCommand(None, None)
                    dummy.data = base64.b64encode(packet.data).decode()
                    self.queue.append(CommandEvent(record, self.i, dummy))
                    return

                # upgrade connection if necessary
                if not space_conn and command.command_id == 3:
                    self.in_space[record.conn_id] = True

                # prevent leaking sensitive information
                if space_conn and command.data['codec'] == 'LoginModelServer_login':
                    command.data['password'] = '*' * 12

                self.queue.append(CommandEvent(record, self.i, command))

            assert packet.bytesAvailable() == 0
        
        self.i += 1

    def __iter__(self):
        return self

    def __next__(self):
        while not self.queue:
            self._next_record()
        return self.queue.pop(0)

def dump_contents(fname):
    with open(fname, 'rb') as f:
        reader = ProtocolEventReader(f)
        date = datetime.datetime.fromtimestamp(reader.start / 1000)
        print('Recording begins at', date)
        for event in reader:
            if event.type == 'begin':
                print(f'[{event.connection_id}] {event.source} -> {event.destination}')
            elif event.type == 'command':
                prefix = 'CL' if event.outgoing else 'SV'
                print(f'[{event.connection_id}] {prefix}>', simplejson.dumps(event.command))

def dump_json(fname):
    events = list()
    with open(fname, 'rb') as f:
        reader = ProtocolEventReader(f)
        try:
            for event in reader:
                events.append(event.to_dict())
        except:
            traceback.print_exc()
    print(simplejson.dumps(events, indent=4, ignore_nan=True))

def dump_bin(fname):
    os.makedirs('dump', exist_ok=True)
    with open(fname, 'rb') as f:
        i = 0
        reader = PacketReader(f)
        for record in reader:
            if record.rec_type == RECORD_DATA:
                packet = util.ByteArray(record.data)
                protocol.decode_null_map(packet)
                length = packet.position
                packet.position = 0
                raw_optional = list(packet.readBytes(length))
                with open(f'dump/{i}.bin', 'wb') as f:
                    f.write(packet.readBytes())
                print(f'Saved {i}.bin, optional={raw_optional}')
            i += 1

def dump_raw(fname):
    with open(fname, 'rb') as f:
        packet = util.ByteArray(f.read())
    optional = protocol.decode_null_map(packet)
    print(optional)
    space = protocol.SpaceCommandDecoder()
    while packet.bytesAvailable():
        command = space.decode(packet, optional)
        print(simplejson.dumps(command.__dict__, indent=4, ignore_nan=True))

def dump_with_null_map(fname, optional):
    with open(fname, 'rb') as f:
        packet = util.ByteArray(f.read())
    space = protocol.SpaceCommandDecoder()
    while packet.bytesAvailable():
        command = space.decode(packet, optional)
        print(simplejson.dumps(command.__dict__, indent=4, ignore_nan=True))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('filename')
    parser.add_argument('-j', '--json', action='store_true', help='output as json')
    parser.add_argument('-b', '--bin', action='store_true', help='output a binary file for each packet')
    parser.add_argument('-r', '--raw', action='store_true', help='read file as raw packet with embedded null map')
    parser.add_argument('-n', '--null', nargs=1, help='read file as raw packet with provided null map')
    args = parser.parse_args()
    if not os.path.isfile(args.filename):
        parser.error(f'{args.filename} not found')
        sys.exit(1)

    if args.json:
        dump_json(args.filename)
    elif args.bin:
        dump_bin(args.filename)
    elif args.raw:
        dump_raw(args.filename)
    elif args.null:
        nulls = bytearray([int(x, 0) for x in args.null[0].split(',')])
        null_map = protocol.decode_null_map(util.ByteArray(nulls))
        dump_with_null_map(args.filename, null_map)
    else:
        dump_contents(args.filename)

if __name__ == '__main__':
    main()
