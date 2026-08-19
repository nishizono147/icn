#!/usr/bin/env python3
"""Benchmark Method A pull retrieval (Interest chunk 0 -> learn N -> Interests 1..N-1).

Latency = pcap timestamp(last Data) - pcap timestamp(first Interest).
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

SOURCE_NAMES = {0: "h2(Producer)", 1: "s1", 2: "s2", 3: "s3"}


def get_if():
    for iface in get_if_list():
        if "eth0" in iface:
            return iface
    print("Cannot find eth0 interface", file=sys.stderr)
    sys.exit(1)


def build_interest(content_id, chunk_id, src_mac):
    return (
        Ether(src=src_mac, dst=GATEWAY_MAC, type=INTEREST_ETHER_TYPE)
        / icn(
            content_id=content_id,
            type=0x11,
            flag=1,
            source_switch=0,
            chunk_id=chunk_id,
        )
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


def wait_for_chunk(pcap_path, content_id, chunk_id, seen_count, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        packets = read_packets(pcap_path)
        idx = seen_count
        while idx < len(packets):
            pkt = packets[idx]
            idx += 1
            if (
                payload in pkt
                and pkt[payload].content_id == content_id
                and pkt[payload].chunk_id == chunk_id
            ):
                return pkt, idx
        time.sleep(0.005)
    return None, seen_count


def pull_one_content(content_id, iface, src_mac, pcap_path, seen_count, timeout, quiet):
    """Fetch all chunks; return latency_ms, sources, new_seen_count."""
    t_start = None
    sources = []
    total = None

    pkt0 = build_interest(content_id, 0, src_mac)
    sendp(pkt0, iface=iface, verbose=False)

    packets = read_packets(pcap_path)
    deadline = time.time() + timeout
    while time.time() < deadline:
        packets = read_packets(pcap_path)
        while seen_count < len(packets):
            p = packets[seen_count]
            seen_count += 1
            if icn in p and p[icn].content_id == content_id and p[icn].chunk_id == 0:
                t_start = float(p.time)
                break
        if t_start is not None:
            break
        time.sleep(0.005)

    resp, seen_count = wait_for_chunk(pcap_path, content_id, 0, seen_count, timeout)
    if resp is None or t_start is None:
        return None, [], seen_count

    total = int(resp[payload].total_chunks)
    sources.append(int(resp[payload].source_switch))
    if not quiet:
        print(
            f"  chunk 0/{total}: source_switch={sources[-1]} "
            f"(learned total_chunks={total})",
            flush=True,
        )

    t_last = float(resp.time)
    for chunk_id in range(1, total):
        sendp(build_interest(content_id, chunk_id, src_mac), iface=iface, verbose=False)
        resp, seen_count = wait_for_chunk(
            pcap_path, content_id, chunk_id, seen_count, timeout
        )
        if resp is None:
            return None, sources, seen_count
        sources.append(int(resp[payload].source_switch))
        t_last = float(resp.time)
        if not quiet:
            print(
                f"  chunk {chunk_id + 1}/{total}: source_switch={sources[-1]}",
                flush=True,
            )

    latency_ms = max(0.0, (t_last - t_start) * 1000.0)
    return latency_ms, sources, seen_count


def run_benchmark(content_id, trials, interval, timeout, pcap_path, quiet):
    iface = get_if()
    src_mac = get_if_hwaddr(iface)
    tcpdump_proc = start_tcpdump(iface, pcap_path)
    seen_count = 0
    results = []
    all_sources = []

    print(f"content_id={content_id}, trials={trials}, model=Method A (pull)")
    print(f"chunk_size={CHUNK_SIZE}B, metric=first Interest(chunk=0)->last Data")
    print(f"capture={pcap_path}")
    print("trial,latency_ms,interests_sent,status")

    try:
        for trial in range(1, trials + 1):
            if not quiet:
                print(f"trial {trial}:", flush=True)
            latency_ms, sources, seen_count = pull_one_content(
                content_id, iface, src_mac, pcap_path, seen_count, timeout, quiet
            )
            n_interests = len(sources) if sources else 0
            if latency_ms is None:
                print(f"{trial},,,timeout", flush=True)
                results.append(None)
                all_sources.append(None)
            else:
                print(f"{trial},{latency_ms:.3f},{n_interests},ok", flush=True)
                results.append(latency_ms)
                all_sources.append(sources)
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
    print("\n--- source per trial (per chunk) ---")
    for trial, sources in enumerate(all_sources, start=1):
        if sources is None:
            print(f"trial {trial}: timeout")
        else:
            labels = [
                f"ch{i}:{SOURCE_NAMES.get(s, s)}" for i, s in enumerate(sources)
            ]
            print(f"trial {trial}: {', '.join(labels)}")

    if len(ok) < trials:
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark Method A pull ICN latency (chunk_pull)."
    )
    parser.add_argument("content_id", type=int, help="Content ID (4=image4.png)")
    parser.add_argument("-n", "--trials", type=int, default=10)
    parser.add_argument("-i", "--interval", type=float, default=0.2)
    parser.add_argument("-t", "--timeout", type=float, default=15.0)
    parser.add_argument("--pcap", default="/tmp/benchmark_pull.pcap")
    parser.add_argument("-q", "--quiet", action="store_true")
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
