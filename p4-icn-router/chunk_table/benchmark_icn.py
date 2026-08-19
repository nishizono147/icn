#!/usr/bin/env python3
"""Measure ICN chunk retrieval time (Interest -> last Data chunk).

Latency = pcap timestamp(last Data chunk) - pcap timestamp(Interest).
Uses chunk_table payload (256 B/chunk, total_chunks/chunk_id fields).
Logs received chunks and source_switch like receive.py.
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
CHUNK_SIZE = 256

SOURCE_NAMES = {
    0: "h2(Producer)",
    1: "s1",
    2: "s2",
    3: "s3",
}


def format_source(source_switch):
    name = SOURCE_NAMES.get(source_switch, "unknown")
    return f"{name} (id={source_switch})"


def get_if():
    for iface in get_if_list():
        if "eth0" in iface:
            return iface
    print("Cannot find eth0 interface", file=sys.stderr)
    sys.exit(1)


def build_interest(content_id, src_mac):
    return (
        Ether(src=src_mac, dst=GATEWAY_MAC, type=INTEREST_ETHER_TYPE)
        / icn(content_id=content_id, type=0x11, flag=1, source_switch=0)
    )


def read_packets(pcap_path):
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


def log_chunk_received(pkt, trial_state, quiet=False):
    """receive.py-style handler for each Data chunk."""
    cid = int(pkt[payload].content_id)
    chunk_id = int(pkt[payload].chunk_id)
    total = int(pkt[payload].total_chunks)
    src_sw = int(pkt[payload].source_switch)

    if not trial_state["started"]:
        trial_state["started"] = True
        trial_state["total"] = total
        trial_state["source_switch"] = src_sw
        if not quiet:
            print(
                f"Start receiving content_id {cid} ({total} chunks, source_switch={src_sw})",
                flush=True,
            )

    if not quiet:
        print(
            f"Got chunk {chunk_id + 1}/{total} for content_id {cid} (source_switch={src_sw})",
            flush=True,
        )

    return src_sw, chunk_id, total


def start_tcpdump(iface, pcap_path):
    if os.path.exists(pcap_path):
        os.remove(pcap_path)
    proc = subprocess.Popen(
        [
            "tcpdump", "-i", iface, "-w", pcap_path, "-U", "-n",
            "ether", "proto", f"0x{INTEREST_ETHER_TYPE:04x}",
            "or", "ether", "proto", f"0x{DATA_ETHER_TYPE:04x}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(0.3)
    if proc.poll() is not None:
        print("Failed to start tcpdump", file=sys.stderr)
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


def wait_for_last_chunk(pcap_path, content_id, seen_count, timeout, quiet=False):
    """Return (latency_ms, source_switch, new_seen_count) when last chunk arrives."""
    deadline = time.time() + timeout
    t_interest = None
    trial_state = {"started": False, "total": 0, "source_switch": None}

    while time.time() < deadline:
        packets = read_packets(pcap_path)
        idx = seen_count
        while idx < len(packets):
            pkt = packets[idx]
            idx += 1
            if icn in pkt and pkt[icn].content_id == content_id:
                t_interest = float(pkt.time)
                trial_state = {"started": False, "total": 0, "source_switch": None}
            elif (
                payload in pkt
                and pkt[payload].content_id == content_id
                and t_interest is not None
            ):
                src_sw, chunk_id, total = log_chunk_received(pkt, trial_state, quiet=quiet)
                if total > 0 and chunk_id == total - 1:
                    if not quiet:
                        print(
                            f"All chunks received for content_id {content_id} "
                            f"(source_switch={src_sw})",
                            flush=True,
                        )
                    latency_ms = max(0.0, (float(pkt.time) - t_interest) * 1000.0)
                    return latency_ms, src_sw, idx
        time.sleep(0.005)

    return None, None, seen_count


def run_benchmark(content_id, trials, interval, timeout, pcap_path, quiet):
    iface = get_if()
    src_mac = get_if_hwaddr(iface)
    interest_pkt = build_interest(content_id, src_mac)
    tcpdump_proc = start_tcpdump(iface, pcap_path)
    seen_count = 0
    results = []
    sources = []

    print(f"content_id={content_id}, trials={trials}, interval={interval}s")
    print(f"chunk_size={CHUNK_SIZE}B, metric=Interest->last Data chunk")
    print(f"capture={pcap_path} (tcpdump pcap timestamps)")
    print("trial,latency_ms,source_switch,status")

    try:
        for trial in range(1, trials + 1):
            sendp(interest_pkt, iface=iface, verbose=False)
            latency_ms, source_switch, seen_count = wait_for_last_chunk(
                pcap_path, content_id, seen_count, timeout, quiet=quiet
            )
            if latency_ms is None:
                print(f"{trial},,,timeout", flush=True)
                results.append(None)
                sources.append(None)
            else:
                print(f"{trial},{latency_ms:.3f},{source_switch},ok", flush=True)
                results.append(latency_ms)
                sources.append(source_switch)
            if trial < trials:
                time.sleep(interval)
    finally:
        stop_tcpdump(tcpdump_proc)

    ok = [r for r in results if r is not None]
    if not ok:
        print("\nNo successful trials.", file=sys.stderr)
        sys.exit(1)

    print("\n--- summary ---")
    print(
        f"all trials: avg={statistics.mean(ok):.3f} ms, "
        f"min={min(ok):.3f} ms, max={max(ok):.3f} ms, n={len(ok)}"
    )

    print("\n--- source per trial ---")
    for trial, src in enumerate(sources, start=1):
        if src is None:
            print(f"trial {trial}: timeout")
        else:
            print(f"trial {trial}: {format_source(src)}")

    failed = trials - len(ok)
    if failed:
        print(f"failed trials: {failed}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Measure ICN multi-chunk retrieval latency (chunk_table)."
    )
    parser.add_argument("content_id", type=int, help="Content ID (4=image4.png)")
    parser.add_argument("-n", "--trials", type=int, default=10)
    parser.add_argument("-i", "--interval", type=float, default=0.2)
    parser.add_argument("-t", "--timeout", type=float, default=15.0)
    parser.add_argument("--pcap", default="/tmp/benchmark_icn_chunk.pcap")
    parser.add_argument(
        "-q", "--quiet", action="store_true",
        help="Suppress receive.py-style per-chunk logs (CSV output remains)",
    )
    args = parser.parse_args()

    run_benchmark(
        content_id=args.content_id,
        trials=args.trials,
        interval=args.interval,
        timeout=args.timeout,
        pcap_path=args.pcap,
        quiet=args.quiet,
    )


if __name__ == "__main__":
    main()
