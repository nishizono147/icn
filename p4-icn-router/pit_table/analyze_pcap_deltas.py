#!/usr/bin/env python3
"""Print raw Interest->Data pcap timestamp deltas for each trial."""
import sys

from icn_header import icn
from payload_header import payload
from scapy.all import rdpcap

pcap = sys.argv[1] if len(sys.argv) > 1 else "/tmp/bench_detail.pcap"
content_id = int(sys.argv[2]) if len(sys.argv) > 2 else 1

pkts = rdpcap(pcap)
trial = 0
t_interest = None

print("trial,interest_ts,data_ts,delta_us,delta_ms")
for pkt in pkts:
    if icn in pkt and pkt[icn].content_id == content_id:
        trial += 1
        t_interest = float(pkt.time)
    elif payload in pkt and pkt[payload].content_id == content_id and t_interest is not None:
        t_data = float(pkt.time)
        delta_us = (t_data - t_interest) * 1_000_000
        print(f"{trial},{t_interest:.9f},{t_data:.9f},{delta_us:.3f},{delta_us/1000:.6f}")
        t_interest = None
