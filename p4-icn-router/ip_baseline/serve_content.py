#!/usr/bin/env python3
"""UDP content server on h2 (producer). Responds to requests like pit_table send_content."""
import argparse
import os
import sys

from scapy.all import Ether, IP, UDP, get_if_hwaddr, sniff, sendp

H2_GATEWAY_MAC = "08:00:00:00:02:00"
H2_IP = "10.0.2.2"
from udp_content import REQUEST_PORT, udp_request, udp_response

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
    for iface in os.listdir("/sys/class/net/"):
        if "eth" in iface:
            return iface
    sys.exit("no eth interface")


def handle_pkt(pkt, quiet=False):
    if UDP not in pkt or udp_request not in pkt:
        return
    if pkt[UDP].dport != REQUEST_PORT:
        return

    content_id = pkt[udp_request].content_id
    if not quiet:
        print(f"request content_id={content_id}")
        pkt.show2()

    image_data = CONTENT_CACHE.get(content_id)
    if not image_data:
        print(f"No cached content for content_id={content_id}", file=sys.stderr)
        return

    iface = get_if()
    resp = (
        Ether(src=get_if_hwaddr(iface), dst=H2_GATEWAY_MAC)
        / IP(src=H2_IP, dst=pkt[IP].src)
        / UDP(sport=REQUEST_PORT, dport=pkt[UDP].sport)
        / udp_response(content_id=content_id, flag=1, data=image_data)
    )
    if not quiet:
        resp.show2()
    sendp(resp, iface=iface, verbose=False)
    sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser(
        description="Respond to UDP content requests on h2 (IP baseline producer)."
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true",
        help="Suppress per-packet debug output",
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
        print(f"listening on {iface} UDP port {REQUEST_PORT}")
    sys.stdout.flush()
    sniff(
        iface=iface,
        filter=f"udp and port {REQUEST_PORT}",
        prn=lambda p: handle_pkt(p, quiet=args.quiet),
    )


if __name__ == "__main__":
    main()
