#!/usr/bin/env python3
import argparse
import os
import sys

from icn_header import icn
from payload_header import payload
from scapy.all import Ether, get_if_hwaddr, get_if_list, sendp, sniff

CONTENT_IMAGE_MAP = {
    1: "image1.png",
    2: "image2.png",
    3: "image3.png",
    4: "image4.png",
    5: "image5.png",
}

CHUNK_SIZE = 256
CONTENT_CHUNKS = {}


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


def load_all_content():
    cache = {}
    for content_id, path in CONTENT_IMAGE_MAP.items():
        try:
            cache[content_id] = load_content_chunks(path)
        except FileNotFoundError:
            print(f"File not found: {path}", file=sys.stderr)
    return cache


def get_if():
    for i in get_if_list():
        if "eth0" in i:
            return i
    print("Cannot find eth0 interface")
    exit(1)


def handle_pkt(packet, quiet=False):
    if icn not in packet:
        return

    content_id = packet[icn].content_id
    chunks = CONTENT_CHUNKS.get(content_id)
    if not chunks:
        if not quiet:
            print(f"No cached content for content_id: {content_id}")
        return

    if not quiet:
        print("got a packet")
        packet.show2()

    iface = get_if()
    total_chunks = len(chunks)
    for chunk_id, chunk_data in enumerate(chunks):
        pkt = Ether(src=get_if_hwaddr(iface), dst=packet[Ether].src, type=0x88B6)
        pkt = pkt / payload(
            content_id=content_id,
            total_chunks=total_chunks,
            chunk_id=chunk_id,
            flag=1,
            source_switch=0,
            data=chunk_data,
        )
        sendp(pkt, iface=iface, verbose=False)
        if not quiet:
            print(f"Sent chunk {chunk_id + 1}/{total_chunks}")
    sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser(
        description="Respond to ICN Interest packets with chunked Data (producer, h2)."
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true",
        help="Suppress per-packet debug output",
    )
    args = parser.parse_args()

    global CONTENT_CHUNKS
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    CONTENT_CHUNKS = load_all_content()
    if not CONTENT_CHUNKS:
        print("No content loaded into cache", file=sys.stderr)
        sys.exit(1)

    ifaces = [i for i in os.listdir("/sys/class/net/") if "eth" in i]
    iface = ifaces[0]
    if not args.quiet:
        print("sniffing on %s" % iface)
    sys.stdout.flush()
    sniff(iface=iface, prn=lambda x: handle_pkt(x, quiet=args.quiet))


if __name__ == "__main__":
    main()
