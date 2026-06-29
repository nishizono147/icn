#!/usr/bin/env python3
import argparse
import os
import sys
import time

from icn_header import icn
from payload_header import payload
from scapy.all import Ether, get_if_hwaddr, get_if_list, sendp, sniff

CONTENT_IMAGE_MAP = {
    1: "image1.png",
    2: "image2.png",
    3: "image3.png",
}

# P4 register<bit<2048>> — one 256-byte word per content_id
REGISTER_DATA_LEN = 256

CONTENT_CACHE = {}


def load_content_cache():
    """Load content into memory once at startup (like P4 content_cache.write)."""
    cache = {}
    for content_id, path in CONTENT_IMAGE_MAP.items():
        try:
            with open(path, "rb") as f:
                cache[content_id] = f.read(REGISTER_DATA_LEN)
        except FileNotFoundError:
            print(f"File not found: {path}", file=sys.stderr)
    return cache


def get_if():
    iface = None
    for i in get_if_list():
        if "eth0" in i:
            iface = i
            break
    if not iface:
        print("Cannot find eth0 interface")
        exit(1)
    return iface


def handle_pkt(packet, quiet=False):
    if icn in packet:
        if os.environ.get("BENCH_LOG"):
            with open("/tmp/h2_interests.log", "a") as f:
                f.write(f"{time.time()}\t{packet[icn].content_id}\n")
        if not quiet:
            print("got a packet")
            packet.show2()
        content_id = packet[icn].content_id
        image_data = CONTENT_CACHE.get(content_id)
        if not image_data:
            print(f"No cached content for content_id: {content_id}")
            return

        iface = get_if()
        pkt = Ether(src=get_if_hwaddr(iface), dst=packet[Ether].src, type=0x88B6)
        pkt = pkt / payload(
            content_id=packet[icn].content_id, flag=1, ttl=8, data=image_data
        )

        if not quiet:
            pkt.show2()
        sendp(pkt, iface=iface, verbose=False)
        sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser(
        description="Respond to ICN Interest packets with content Data (producer, h2)."
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true",
        help="Suppress per-packet debug output (useful during benchmarking)",
    )
    args = parser.parse_args()

    global CONTENT_CACHE
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    CONTENT_CACHE = load_content_cache()
    if not CONTENT_CACHE:
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
