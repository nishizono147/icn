#!/usr/bin/env python3
"""Measure IP/UDP content retrieval time on h1 (fair comparison with pit_table ICN).

One tcpdump capture; latency = pcap timestamp(UDP request) -> pcap timestamp(UDP response).
Same topology, images, payload size (256B), and trial pattern as benchmark_icn.py.
"""
import argparse
import os
import signal
import statistics
import struct
import subprocess
import sys
import time

from scapy.all import Ether, IP, UDP, get_if_hwaddr, get_if_list, rdpcap, sendp
from scapy.utils import PcapReader
from udp_content import CLIENT_PORT, REQUEST_LEN, REQUEST_PORT, udp_request

H1_IP = "10.0.1.1"
H2_IP = "10.0.2.2"
H1_GATEWAY_MAC = "08:00:00:00:01:00"


def get_if():
    for iface in get_if_list():
        if "eth0" in iface:
            return iface
    print("Cannot find eth0 interface", file=sys.stderr)
    sys.exit(1)


def build_request(content_id, src_mac):
    return (
        Ether(src=src_mac, dst=H1_GATEWAY_MAC)
        / IP(src=H1_IP, dst=H2_IP)
        / UDP(sport=CLIENT_PORT, dport=REQUEST_PORT)
        / udp_request(content_id=content_id, flag=1, hop_count=4)
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


def parse_request_content_id(pkt):
    if IP not in pkt or UDP not in pkt:
        return None
    if pkt[IP].src != H1_IP or pkt[IP].dst != H2_IP:
        return None
    if pkt[UDP].dport != REQUEST_PORT:
        return None
    payload = bytes(pkt[UDP].payload)
    if len(payload) < REQUEST_LEN:
        return None
    content_id = struct.unpack("!I", payload[:4])[0]
    return content_id


def parse_response_content_id(pkt):
    if IP not in pkt or UDP not in pkt:
        return None
    if pkt[IP].src != H2_IP or pkt[IP].dst != H1_IP:
        return None
    if pkt[UDP].sport != REQUEST_PORT:
        return None
    payload = bytes(pkt[UDP].payload)
    if len(payload) < 4:
        return None
    return struct.unpack("!I", payload[:4])[0]


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
            "host", H2_IP,
            "and", "udp", "port", str(REQUEST_PORT),
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


def wait_for_response(pcap_path, content_id, seen_count, timeout):
    deadline = time.time() + timeout
    t_request = None

    while time.time() < deadline:
        packets = read_packets(pcap_path)
        idx = seen_count
        while idx < len(packets):
            pkt = packets[idx]
            idx += 1
            req_id = parse_request_content_id(pkt)
            if req_id == content_id:
                t_request = float(pkt.time)
            elif t_request is not None:
                resp_id = parse_response_content_id(pkt)
                if resp_id == content_id:
                    latency_ms = max(0.0, (float(pkt.time) - t_request) * 1000.0)
                    return latency_ms, idx
        time.sleep(0.005)

    return None, seen_count


def run_benchmark(content_id, trials, interval, timeout, warm_start, pcap_path, iface):
    if content_id not in (1, 2, 3):
        print(f"Unknown content_id: {content_id}", file=sys.stderr)
        sys.exit(1)

    request_pkt = build_request(content_id, get_if_hwaddr(iface))
    tcpdump_proc = start_tcpdump(iface, pcap_path)
    seen_count = 0
    results = []

    print(f"content_id={content_id}, trials={trials}, interval={interval}s")
    print(f"protocol=UDP {H1_IP}:{CLIENT_PORT} -> {H2_IP}:{REQUEST_PORT}")
    print(f"capture={pcap_path} (tcpdump pcap timestamps)")
    print("trial,phase,latency_ms,status")

    try:
        for trial in range(1, trials + 1):
            phase = "cold" if trial == 1 else "warm"
            sendp(request_pkt, iface=iface, verbose=False)

            latency_ms, seen_count = wait_for_response(
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
    all_trials = ok
    warm = [r for i, r in enumerate(results, start=1) if r is not None and i >= warm_start]

    print("\n--- summary ---")
    if cold:
        print(f"cold (trial 1): {cold[0]:.3f} ms")
    print(
        f"all trials avg: avg={statistics.mean(all_trials):.3f} ms, "
        f"min={min(all_trials):.3f} ms, max={max(all_trials):.3f} ms, n={len(all_trials)}"
    )
    if warm:
        print(
            f"warm (trial {warm_start}-{trials}): "
            f"avg={statistics.mean(warm):.3f} ms, "
            f"min={min(warm):.3f} ms, max={max(warm):.3f} ms, n={len(warm)}"
        )
    print(
        "note: compare cold (trial 1) with ICN cold; IP has no in-network cache "
        "(warm trials still reach h2)."
    )

    failed = trials - len(ok)
    if failed:
        print(f"failed trials: {failed}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Measure UDP content retrieval latency on h1 (IP baseline)."
    )
    parser.add_argument("content_id", type=int, help="Content ID (1-3)")
    parser.add_argument("-n", "--trials", type=int, default=10)
    parser.add_argument("-i", "--interval", type=float, default=0.2)
    parser.add_argument("-t", "--timeout", type=float, default=5.0)
    parser.add_argument("--warm-start", type=int, default=4)
    parser.add_argument("--pcap", default="/tmp/benchmark_ip.pcap")
    parser.add_argument("--iface", default="eth0")
    args = parser.parse_args()

    if args.trials < 1:
        parser.error("trials must be >= 1")

    run_benchmark(
        content_id=args.content_id,
        trials=args.trials,
        interval=args.interval,
        timeout=args.timeout,
        warm_start=args.warm_start,
        pcap_path=args.pcap,
        iface=args.iface,
    )


if __name__ == "__main__":
    main()
