#!/usr/bin/env python3
"""Measure ICN content retrieval time (Interest send -> Data receive).

Uses a single tcpdump capture and pcap packet timestamps (kernel/libpcap time)
instead of Scapy AsyncSniffer callbacks, avoiding userspace delivery jitter.

Pattern A: run multiple consecutive trials in the same Mininet session to
observe cache warm-up (trial 1 = cold, later trials = warm).
"""
import argparse
import os
import signal
import statistics
import subprocess
import sys
import time

from icn_header import icn
from payload_header import payload
from scapy.all import Ether, get_if_hwaddr, get_if_list, rdpcap, sendp
from scapy.utils import PcapReader

GATEWAY_MAC = "08:00:00:00:01:00"
INTEREST_ETHER_TYPE = 0x88B5
DATA_ETHER_TYPE = 0x88B6


def get_if():
    for iface in get_if_list():
        if "eth0" in iface:
            return iface
    print("Cannot find eth0 interface", file=sys.stderr)
    sys.exit(1)


def build_interest(content_id, src_mac):
    return (
        Ether(src=src_mac, dst=GATEWAY_MAC, type=INTEREST_ETHER_TYPE)
        / icn(content_id=content_id, type=0x11, hop_count=4, flag=1)
    )


def read_packets(pcap_path):
    """Read all packets from a pcap file; tolerate in-progress writes."""
    if not os.path.exists(pcap_path) or os.path.getsize(pcap_path) < 24:
        return []
    try:
        return rdpcap(pcap_path)
    except Exception:
        packets = []
        try:
            with PcapReader(pcap_path) as reader:
                for pkt in reader:
                    packets.append(pkt)
        except Exception:
            return packets
        return packets


def start_tcpdump(iface, pcap_path):
    if os.path.exists(pcap_path):
        os.remove(pcap_path)
    proc = subprocess.Popen(
        [
            "tcpdump",
            "-i", iface,
            "-w", pcap_path,
            "-U",
            "-n",
            "ether", "proto", f"0x{INTEREST_ETHER_TYPE:04x}",
            "or", "ether", "proto", f"0x{DATA_ETHER_TYPE:04x}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(0.3)
    if proc.poll() is not None:
        print("Failed to start tcpdump (is it installed?)", file=sys.stderr)
        sys.exit(1)
    return proc


def stop_tcpdump(proc):
    if proc.poll() is None:
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)


def wait_for_data(pcap_path, content_id, seen_count, timeout):
    """Return (latency_ms, new_seen_count) using pcap Interest->Data timestamps."""
    deadline = time.time() + timeout
    t_interest = None

    while time.time() < deadline:
        packets = read_packets(pcap_path)
        idx = seen_count
        while idx < len(packets):
            pkt = packets[idx]
            idx += 1
            if icn in pkt and pkt[icn].content_id == content_id:
                t_interest = float(pkt.time)
            elif (
                payload in pkt
                and pkt[payload].content_id == content_id
                and t_interest is not None
            ):
                latency_ms = max(0.0, (float(pkt.time) - t_interest) * 1000.0)
                return latency_ms, idx
        time.sleep(0.005)

    return None, seen_count


def run_benchmark(content_id, trials, interval, timeout, warm_start, pcap_path):
    iface = get_if()
    src_mac = get_if_hwaddr(iface)
    interest_pkt = build_interest(content_id, src_mac)

    tcpdump_proc = start_tcpdump(iface, pcap_path)
    seen_count = 0

    results = []
    print(f"content_id={content_id}, trials={trials}, interval={interval}s")
    print(f"capture={pcap_path} (tcpdump pcap timestamps)")
    print("trial,phase,latency_ms,status")

    try:
        for trial in range(1, trials + 1):
            phase = "cold" if trial == 1 else "warm"
            sendp(interest_pkt, iface=iface, verbose=False)

            latency_ms, seen_count = wait_for_data(
                pcap_path, content_id, seen_count, timeout
            )

            if latency_ms is None:
                print(f"{trial},{phase},,timeout", flush=True)
                results.append(None)
            else:
                print(f"{trial},{phase},{latency_ms:.3f},ok", flush=True)
                results.append(latency_ms)

            if trial < trials:
                time.sleep(interval)
    finally:
        stop_tcpdump(tcpdump_proc)

    ok = [r for r in results if r is not None]
    if not ok:
        print("\nNo successful trials.", file=sys.stderr)
        sys.exit(1)

    cold = [results[0]] if results[0] is not None else []
    warm = [r for i, r in enumerate(results, start=1) if r is not None and i >= warm_start]

    print("\n--- summary ---")
    if cold:
        print(f"cold (trial 1): {cold[0]:.3f} ms")
    if warm:
        print(
            f"warm (trial {warm_start}-{trials}): "
            f"avg={statistics.mean(warm):.3f} ms, "
            f"min={min(warm):.3f} ms, "
            f"max={max(warm):.3f} ms, "
            f"n={len(warm)}"
        )
    if cold and warm:
        print(f"speedup (cold / warm avg): {cold[0] / statistics.mean(warm):.2f}x")

    failed = trials - len(ok)
    if failed:
        print(f"failed trials: {failed}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Measure ICN content retrieval latency on the consumer (h1)."
    )
    parser.add_argument("content_id", type=int, help="Content ID to request")
    parser.add_argument(
        "-n", "--trials", type=int, default=10, help="Number of consecutive trials (default: 10)"
    )
    parser.add_argument(
        "-i", "--interval", type=float, default=1.0,
        help="Seconds between trials (default: 1.0)"
    )
    parser.add_argument(
        "-t", "--timeout", type=float, default=5.0,
        help="Seconds to wait for Data per trial (default: 5.0)"
    )
    parser.add_argument(
        "--warm-start", type=int, default=4,
        help="First trial index counted as warm in summary (default: 4)"
    )
    parser.add_argument(
        "--pcap", default="/tmp/benchmark_icn.pcap",
        help="Path for tcpdump capture file (default: /tmp/benchmark_icn.pcap)"
    )
    args = parser.parse_args()

    if args.trials < 1:
        parser.error("trials must be >= 1")
    if args.warm_start < 2:
        parser.error("warm-start must be >= 2")
    if args.warm_start > args.trials:
        parser.error("warm-start must be <= trials")

    run_benchmark(
        content_id=args.content_id,
        trials=args.trials,
        interval=args.interval,
        timeout=args.timeout,
        warm_start=args.warm_start,
        pcap_path=args.pcap,
    )


if __name__ == "__main__":
    main()
