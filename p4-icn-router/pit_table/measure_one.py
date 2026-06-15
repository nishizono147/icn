#!/usr/bin/env python3
import argparse
import threading
import time

from icn_header import icn
from payload_header import payload
from scapy.all import AsyncSniffer, Ether, get_if_hwaddr, get_if_list, sendp

GATEWAY_MAC = "08:00:00:00:01:00"


def get_if():
    for iface in get_if_list():
        if "eth0" in iface:
            return iface
    raise RuntimeError("Cannot find eth0")


def measure_once(content_id, iface, src_mac):
    event = threading.Event()
    result = {}

    def handle_pkt(pkt):
        if payload in pkt and pkt[payload].content_id == content_id and not event.is_set():
            result["ms"] = (time.perf_counter() - result["t"]) * 1000.0
            event.set()

    sniffer = AsyncSniffer(iface=iface, prn=handle_pkt)
    sniffer.start()
    time.sleep(0.05)
    pkt = (
        Ether(src=src_mac, dst=GATEWAY_MAC, type=0x88B5)
        / icn(content_id=content_id, type=0x11, hop_count=4, flag=1)
    )
    result["t"] = time.perf_counter()
    sendp(pkt, iface=iface, verbose=False)
    event.wait(timeout=5)
    sniffer.stop()
    return result.get("ms")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("content_id", type=int)
    parser.add_argument("-n", type=int, default=10)
    args = parser.parse_args()

    iface = get_if()
    src_mac = get_if_hwaddr(iface)
    for trial in range(1, args.n + 1):
        ms = measure_once(args.content_id, iface, src_mac)
        if ms is None:
            print(f"{trial},timeout")
        else:
            print(f"{trial},{ms:.3f}")
        time.sleep(0.25)


if __name__ == "__main__":
    main()
