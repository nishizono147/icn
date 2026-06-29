#!/usr/bin/env python3
"""Measure IP/UDP multi-chunk content retrieval time on h1.

Latency = pcap timestamp(last UDP response chunk) - pcap timestamp(UDP request).
Same chunk layout and 256B chunk size as chunk_table.
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
from udp_content import CHUNK_SIZE, CLIENT_PORT, REQUEST_LEN, REQUEST_PORT, udp_request, udp_response

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
    if udp_request in pkt:
        return pkt[udp_request].content_id
    payload = bytes(pkt[UDP].payload)
    if len(payload) < REQUEST_LEN:
        return None
    return struct.unpack("!I", payload[:4])[0]


def start_tcpdump(iface, pcap_path):
    if os.path.exists(pcap_path):
        os.remove(pcap_path)
    proc = subprocess.Popen(
        [
            "tcpdump", "-i", iface, "-w", pcap_path, "-U", "-n",
            "host", H2_IP, "and", "udp", "port", str(REQUEST_PORT),
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


def wait_for_last_chunk(pcap_path, content_id, seen_count, timeout):
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
            elif t_request is not None and udp_response in pkt:
                resp = pkt[udp_response]
                if resp.content_id == content_id and resp.total_chunks > 0:
                    if resp.chunk_id == resp.total_chunks - 1:
                        latency_ms = max(0.0, (float(pkt.time) - t_request) * 1000.0)
                        return latency_ms, idx
        time.sleep(0.005)

    return None, seen_count


def run_benchmark(content_id, trials, interval, timeout, pcap_path, iface):
    request_pkt = build_request(content_id, get_if_hwaddr(iface))
    tcpdump_proc = start_tcpdump(iface, pcap_path)
    seen_count = 0
    results = []

    print(f"content_id={content_id}, trials={trials}, interval={interval}s")
    print(f"chunk_size={CHUNK_SIZE}B, metric=request->last UDP chunk")
    print(f"protocol=UDP {H1_IP}:{CLIENT_PORT} -> {H2_IP}:{REQUEST_PORT}")
    print(f"capture={pcap_path} (tcpdump pcap timestamps)")
    print("trial,latency_ms,status")

    try:
        for trial in range(1, trials + 1):
            sendp(request_pkt, iface=iface, verbose=False)
            latency_ms, seen_count = wait_for_last_chunk(
                pcap_path, content_id, seen_count, timeout
            )
            if latency_ms is None:
                print(f"{trial},,timeout", flush=True)
                results.append(None)
            else:
                print(f"{trial},{latency_ms:.3f},ok", flush=True)
                results.append(latency_ms)
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
    failed = trials - len(ok)
    if failed:
        print(f"failed trials: {failed}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Measure UDP multi-chunk retrieval latency on h1."
    )
    parser.add_argument("content_id", type=int, help="Content ID (4=image4.png)")
    parser.add_argument("-n", "--trials", type=int, default=10)
    parser.add_argument("-i", "--interval", type=float, default=0.2)
    parser.add_argument("-t", "--timeout", type=float, default=15.0)
    parser.add_argument("--pcap", default="/tmp/benchmark_ip_chunk.pcap")
    parser.add_argument("--iface", default="eth0")
    args = parser.parse_args()

    run_benchmark(
        content_id=args.content_id,
        trials=args.trials,
        interval=args.interval,
        timeout=args.timeout,
        pcap_path=args.pcap,
        iface=args.iface,
    )


if __name__ == "__main__":
    main()
