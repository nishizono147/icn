#!/usr/bin/env python3
import sys
import threading
import time

from icn_header import icn
from payload_header import payload
from scapy.all import AsyncSniffer, Ether, get_if_hwaddr, get_if_list, sendp

GATEWAY_MAC = "08:00:00:00:01:00"


def main():
    content_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    iface = next(i for i in get_if_list() if "eth0" in i)
    src = get_if_hwaddr(iface)
    event = threading.Event()
    result = {}

    def handle_pkt(pkt):
        if payload in pkt and pkt[payload].content_id == content_id and not event.is_set():
            result["ms"] = (time.perf_counter() - result["t"]) * 1000.0
            event.set()

    sniffer = AsyncSniffer(iface=iface, prn=handle_pkt)
    sniffer.start()
    time.sleep(0.05)
    pkt = Ether(src=src, dst=GATEWAY_MAC, type=0x88B5) / icn(
        content_id=content_id, type=0x11, hop_count=4, flag=1
    )
    result["t"] = time.perf_counter()
    sendp(pkt, iface=iface, verbose=False)
    event.wait(5)
    sniffer.stop()
    print(result.get("ms", ""))


if __name__ == "__main__":
    main()
