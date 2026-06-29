#!/usr/bin/env python3
"""UDP multi-chunk producer on h2: memory cache + prebuilt payloads + kernel UDP.

Mirrors chunk_table producer strategy (startup preload, no runtime Scapy send).
"""
import argparse
import os
import socket
import struct
import sys

from udp_content import CHUNK_SIZE, REQUEST_PORT

H2_IP = "10.0.2.2"
CONTENT_ID = 4
IMAGE_PATH = "image4.png"

PREBUILT_PAYLOADS = []
TOTAL_CHUNKS = 0


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


def build_payload(content_id, total_chunks, chunk_id, chunk_data):
    header = struct.pack("!IHHBB", content_id, total_chunks, chunk_id, 1, 0)
    return header + chunk_data


def load_prebuilt(path):
    chunks = load_content_chunks(path)
    total = len(chunks)
    payloads = [
        build_payload(CONTENT_ID, total, chunk_id, chunk_data)
        for chunk_id, chunk_data in enumerate(chunks)
    ]
    return payloads, total


def serve(sock, quiet):
    while True:
        data, addr = sock.recvfrom(2048)
        if len(data) < 4:
            continue
        content_id = struct.unpack("!I", data[:4])[0]
        if content_id != CONTENT_ID:
            continue
        if not quiet:
            print(f"request content_id={content_id} from {addr}", flush=True)
        for payload in PREBUILT_PAYLOADS:
            sock.sendto(payload, addr)


def main():
    parser = argparse.ArgumentParser(
        description="UDP multi-chunk producer (h2): prebuilt payloads + kernel UDP."
    )
    parser.add_argument("-q", "--quiet", action="store_true")
    args = parser.parse_args()

    global PREBUILT_PAYLOADS, TOTAL_CHUNKS
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    if not os.path.exists(IMAGE_PATH):
        print(f"Missing {IMAGE_PATH}", file=sys.stderr)
        sys.exit(1)

    PREBUILT_PAYLOADS, TOTAL_CHUNKS = load_prebuilt(IMAGE_PATH)
    if TOTAL_CHUNKS == 0:
        print("No chunks loaded", file=sys.stderr)
        sys.exit(1)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((H2_IP, REQUEST_PORT))

    if not args.quiet:
        print(
            f"listening UDP {H2_IP}:{REQUEST_PORT}, "
            f"content_id={CONTENT_ID}, chunks={TOTAL_CHUNKS}, "
            f"chunk_size={CHUNK_SIZE}B (kernel UDP, prebuilt cache)",
            flush=True,
        )
    serve(sock, args.quiet)


if __name__ == "__main__":
    main()
