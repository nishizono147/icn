#!/usr/bin/env python3
"""Per-trial diagnostic: log all Data packets received on h1."""
import argparse
import os
import sys
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
    sys.exit(1)


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    parser = argparse.ArgumentParser()
    parser.add_argument("content_id", type=int)
    parser.add_argument("-n", type=int, default=10)
    args = parser.parse_args()

    iface = get_if()
    src_mac = get_if_hwaddr(iface)
    interest = (
        Ether(src=src_mac, dst=GATEWAY_MAC, type=0x88B5)
        / icn(content_id=args.content_id, type=0x11, hop_count=4, flag=1)
    )

    trial_state = {"trial": 0, "t_start": None, "packets": []}
    lock = threading.Lock()

    def handle_pkt(pkt):
        if payload not in pkt or pkt[payload].content_id != args.content_id:
            return
        with lock:
            if trial_state["t_start"] is None:
                return
            dt = (time.perf_counter() - trial_state["t_start"]) * 1000.0
            trial_state["packets"].append(dt)

    sniffer = AsyncSniffer(iface=iface, prn=handle_pkt)
    sniffer.start()
    time.sleep(0.2)

    print("trial,first_data_ms,num_data_packets,all_data_ms")

    for trial in range(1, args.n + 1):
        with lock:
            trial_state["trial"] = trial
            trial_state["t_start"] = None
            trial_state["packets"] = []

        with lock:
            trial_state["t_start"] = time.perf_counter()
        sendp(interest, iface=iface, verbose=False)

        time.sleep(0.3)
        with lock:
            pkts = list(trial_state["packets"])
            trial_state["t_start"] = None

        if pkts:
            print(f"{trial},{pkts[0]:.3f},{len(pkts)}," + "|".join(f"{x:.3f}" for x in pkts))
        else:
            print(f"{trial},,0,")

    sniffer.stop()


if __name__ == "__main__":
    main()
