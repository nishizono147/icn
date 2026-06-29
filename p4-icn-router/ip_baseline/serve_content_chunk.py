#!/usr/bin/env python3
"""UDP multi-chunk content server on h2 (fair comparison with chunk_table).

Serves image4.png (content_id=4) as 256-byte chunks from memory cache.
"""
import argparse
import os
import sys

from scapy.all import Ether, IP, UDP, get_if_hwaddr, sniff, sendp

H2_GATEWAY_MAC = "08:00:00:00:02:00"
H2_IP = "10.0.2.2"
from udp_content import CHUNK_SIZE, REQUEST_PORT, udp_request, udp_response

CONTENT_ID = 4
IMAGE_PATH = "image4.png"

CONTENT_CHUNKS = []
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
    if content_id != CONTENT_ID:
        if not quiet:
            print(f"unsupported content_id={content_id}", file=sys.stderr)
        return

    if not quiet:
        print(f"request content_id={content_id}, sending {TOTAL_CHUNKS} chunks")

    iface = get_if()
    src_mac = get_if_hwaddr(iface)
    dst_ip = pkt[IP].src
    dst_port = pkt[UDP].sport

    for chunk_id, chunk_data in enumerate(CONTENT_CHUNKS):
        resp = (
            Ether(src=src_mac, dst=H2_GATEWAY_MAC)
            / IP(src=H2_IP, dst=dst_ip)
            / UDP(sport=REQUEST_PORT, dport=dst_port)
            / udp_response(
                content_id=CONTENT_ID,
                total_chunks=TOTAL_CHUNKS,
                chunk_id=chunk_id,
                flag=1,
                reserved=0,
                data=chunk_data,
            )
        )
        sendp(resp, iface=iface, verbose=False)
    sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser(
        description="Respond to UDP content requests with multi-chunk image4 (h2)."
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true",
        help="Suppress per-packet debug output",
    )
    args = parser.parse_args()

    global CONTENT_CHUNKS, TOTAL_CHUNKS
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    if not os.path.exists(IMAGE_PATH):
        print(f"Missing {IMAGE_PATH}", file=sys.stderr)
        sys.exit(1)
    CONTENT_CHUNKS = load_content_chunks(IMAGE_PATH)
    TOTAL_CHUNKS = len(CONTENT_CHUNKS)
    if TOTAL_CHUNKS == 0:
        print("No chunks loaded", file=sys.stderr)
        sys.exit(1)

    ifaces = [i for i in os.listdir("/sys/class/net/") if "eth" in i]
    iface = ifaces[0]
    if not args.quiet:
        print(
            f"listening on {iface} UDP port {REQUEST_PORT}, "
            f"content_id={CONTENT_ID}, chunks={TOTAL_CHUNKS}, "
            f"chunk_size={CHUNK_SIZE}B"
        )
    sys.stdout.flush()
    sniff(
        iface=iface,
        filter=f"udp and port {REQUEST_PORT}",
        prn=lambda p: handle_pkt(p, quiet=args.quiet),
    )


if __name__ == "__main__":
    main()
