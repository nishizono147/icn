#!/usr/bin/env python3
"""Send a single Interest with chunk_id (manual test)."""
import argparse

from icn_header import icn
from scapy.all import Ether, get_if_hwaddr, get_if_list, sendp

GATEWAY_MAC = "08:00:00:00:01:00"


def get_if():
    for iface in get_if_list():
        if "eth0" in iface:
            return iface
    raise SystemExit("Cannot find eth0 interface")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("content_id", type=int)
    parser.add_argument("chunk_id", type=int, nargs="?", default=0)
    args = parser.parse_args()

    iface = get_if()
    pkt = (
        Ether(src=get_if_hwaddr(iface), dst=GATEWAY_MAC, type=0x88B5)
        / icn(
            content_id=args.content_id,
            type=0x11,
            flag=1,
            source_switch=0,
            chunk_id=args.chunk_id,
        )
    )
    pkt.show2()
    sendp(pkt, iface=iface, verbose=False)


if __name__ == "__main__":
    main()
