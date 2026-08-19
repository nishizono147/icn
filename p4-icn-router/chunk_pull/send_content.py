#!/usr/bin/env python3
"""ICN pull producer (Method A): one Data chunk per Interest.

Interest header includes chunk_id; responds with only that chunk.
Uses prebuilt frames + AF_PACKET (same load model as chunk_table).
"""
import argparse
import os
import socket
import struct
import sys

from scapy.all import Ether, raw
from payload_header import payload

INTEREST_TYPE = 0x88B5
DATA_TYPE = 0x88B6
H2_MAC = "08:00:00:00:02:22"
CHUNK_SIZE = 256

# Reuse content files from chunk_table
CONTENT_DIR = os.path.join(os.path.dirname(__file__), "..", "chunk_table")
CONTENT_IMAGE_MAP = {
    1: "image1.png",
    2: "image2.png",
    3: "image3.png",
    4: "image4.png",
    5: "image5.png",
}

PREBUILT = {}


def mac_bytes(mac):
    return bytes(int(x, 16) for x in mac.split(":"))


def load_content_chunks(path):
    with open(path, "rb") as f:
        data = f.read()
    chunks = []
    for i in range(0, len(data), CHUNK_SIZE):
        chunk = data[i:i + CHUNK_SIZE]
        if len(chunk) < CHUNK_SIZE:
            chunk = chunk.ljust(CHUNK_SIZE, b"\x00")
        chunks.append(chunk)
    return chunks


def build_prebuilt(content_id, chunks, h2_mac):
    total = len(chunks)
    h2 = mac_bytes(h2_mac)
    frames = []
    for chunk_id, chunk_data in enumerate(chunks):
        pkt = Ether(src=h2, dst="00:00:00:00:00:00", type=DATA_TYPE) / payload(
            content_id=content_id,
            total_chunks=total,
            chunk_id=chunk_id,
            flag=1,
            source_switch=0,
            data=chunk_data,
        )
        frames.append(bytearray(raw(pkt)))
    return frames


def load_all_prebuilt(h2_mac):
    cache = {}
    for content_id, name in CONTENT_IMAGE_MAP.items():
        path = os.path.join(CONTENT_DIR, name)
        try:
            chunks = load_content_chunks(path)
            cache[content_id] = build_prebuilt(content_id, chunks, h2_mac)
        except FileNotFoundError:
            print(f"File not found: {path}", file=sys.stderr)
    return cache


def parse_interest(frame):
    if len(frame) < 24:
        return None
    if struct.unpack("!H", frame[12:14])[0] != INTEREST_TYPE:
        return None
    content_id = struct.unpack("!I", frame[14:18])[0]
    chunk_id = struct.unpack("!H", frame[22:24])[0]
    return content_id, chunk_id


def serve(sock, quiet):
    h2 = mac_bytes(H2_MAC)
    while True:
        frame = sock.recv(65535)
        parsed = parse_interest(frame)
        if not parsed:
            continue
        content_id, chunk_id = parsed
        templates = PREBUILT.get(content_id)
        if not templates or chunk_id >= len(templates):
            continue
        dst_mac = frame[6:12]
        if not quiet:
            print(
                f"Interest content_id={content_id} chunk_id={chunk_id} "
                f"-> Data 1 packet",
                flush=True,
            )
        tmpl = templates[chunk_id]
        out = tmpl[:]
        out[0:6] = dst_mac
        out[6:12] = h2
        sock.send(out)


def main():
    parser = argparse.ArgumentParser(
        description="Pull-model ICN producer: one chunk per Interest (h2)."
    )
    parser.add_argument("-q", "--quiet", action="store_true")
    args = parser.parse_args()

    global PREBUILT
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    PREBUILT = load_all_prebuilt(H2_MAC)
    if not PREBUILT:
        print("No content loaded", file=sys.stderr)
        sys.exit(1)

    sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(INTEREST_TYPE))
    sock.bind(("eth0", 0))
    if not args.quiet:
        print("listening on eth0 (Method A: 1 Interest -> 1 Data chunk)", flush=True)
    serve(sock, args.quiet)


if __name__ == "__main__":
    main()
