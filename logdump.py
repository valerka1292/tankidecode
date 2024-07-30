#!/usr/bin/env python3
import argparse
import sys
import os

import altdump

FLASH_LOG = os.path.join(os.getenv('APPDATA'), 'Macromedia/Flash Player/Logs/flashlog.txt')
STEAM_LOG = os.path.join(os.getenv('APPDATA'), 'TankiOnline/Local Store/flashlog.txt')

def parse_log(log):
    records = list()
    in_packet = False
    data = dict()
    with open(log, 'r') as f:
        while True:
            try:
                line = next(f).rstrip()
            except StopIteration:
                records.append(data)
                break
            if line == '*****':
                if in_packet:
                    records.append(data)
                in_packet = True
                data = dict()
            elif in_packet and '=' in line:
                k, v = line.split('=', 2)
                data[k] = v
    return records

def convert_log(log, fname):
    records = parse_log(log)
    with altdump.PacketWriter(fname) as w:
        for record in records:
            conn_id = int(record['id'])
            if record['type'] == 'begin':
                src = ('127.0.0.1', 0)
                dst = (record['host'], int(record['port']))
                w.write(altdump.RecordBegin(conn_id, True, src, dst))
            elif record['type'] == 'data':
                outgoing = bool(int(record['outgoing']))
                data = bytearray.fromhex(record['hex'])
                w.write(altdump.RecordData(conn_id, outgoing, data))
            elif record['type'] == 'end':
                outgoing = bool(int(record['outgoing']))
                w.write(altdump.RecordEnd(conn_id, outgoing))
            print('wrote record')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('filename', nargs='?', default='flashlog.bin', help='packet dump file')
    parser.add_argument('-s', '--steam', action='store_true', help='use log from steam version')
    args = parser.parse_args()
    log = STEAM_LOG if args.steam else FLASH_LOG
    convert_log(log, args.filename)

if __name__ == '__main__':
    main()
