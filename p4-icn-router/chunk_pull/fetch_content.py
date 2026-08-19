#!/usr/bin/env python3
"""Method A consumer: pull chunks with per-chunk Interests.

1. Send Interest(chunk_id=0)
2. Learn total_chunks from first Data
3. Send Interest(chunk_id=1..N-1) for remaining chunks
4. Reassemble and optionally save image
"""
import argparse
import os
import signal
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
        while seen_count < len(packets):
            pkt = packets[seen_count]
            seen_count += 1
            if (
                payload in pkt
                and pkt[payload].content_id == content_id
                and pkt[payload].chunk_id == chunk_id
            ):
                return pkt, seen_count
        time.sleep(0.005)
    return None, seen_count


def save_image(data, content_id):
    directory = "received_image"
    os.makedirs(directory, exist_ok=True)
    filename = os.path.join(directory, f"image{content_id}.png")
    with open(filename, "wb") as f:
        f.write(data)
    print(f"Image saved as {filename}")


def fetch_content(content_id, iface, src_mac, timeout, pcap_path, save):
    """Return (buffers, total_chunks, sources)."""
    tcpdump_proc = start_tcpdump(iface, pcap_path)
    seen_count = 0
    buffers = {}
    sources = []
    total = None

    try:
        sendp(build_interest(content_id, 0, src_mac), iface=iface, verbose=False)
        resp, seen_count = wait_for_chunk(pcap_path, content_id, 0, seen_count, timeout)
        if resp is None:
            raise TimeoutError(f"timeout waiting for chunk 0")

        total = int(resp[payload].total_chunks)
        src_sw = int(resp[payload].source_switch)
        buffers[0] = bytes(resp[payload].data)
        sources.append(src_sw)
        print(
            f"Learned total_chunks={total} from chunk 0 (source_switch={src_sw})",
            flush=True,
        )
        print(
            f"Got chunk 1/{total} for content_id {content_id} (source_switch={src_sw})",
            flush=True,
        )

        for chunk_id in range(1, total):
            sendp(build_interest(content_id, chunk_id, src_mac), iface=iface, verbose=False)
            resp, seen_count = wait_for_chunk(
                pcap_path, content_id, chunk_id, seen_count, timeout
            )
            if resp is None:
                raise TimeoutError(f"timeout waiting for chunk {chunk_id}")
            src_sw = int(resp[payload].source_switch)
            buffers[chunk_id] = bytes(resp[payload].data)
            sources.append(src_sw)
            print(
                f"Got chunk {chunk_id + 1}/{total} for content_id {content_id} "
                f"(source_switch={src_sw})",
                flush=True,
            )
    finally:
        stop_tcpdump(tcpdump_proc)

    full = b"".join(buffers[i] for i in range(total))
    if save:
        save_image(full, content_id)
    print(f"Successfully reconstructed content_id {content_id} ({total} chunks)")
    return buffers, total, sources


def main():
    parser = argparse.ArgumentParser(
        description="Fetch ICN content using Method A (N Interests, pull model)."
    )
    parser.add_argument("content_id", type=int, help="Content ID (4=image4.png)")
    parser.add_argument(
        "-t", "--timeout", type=float, default=10.0,
        help="Seconds to wait per chunk (default: 10.0)",
    )
    parser.add_argument(
        "--pcap", default="/tmp/fetch_pull.pcap",
        help="tcpdump capture file",
    )
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args()

    iface = get_if()
    src_mac = get_if_hwaddr(iface)
    print(f"fetch content_id={args.content_id} on {iface} (Method A pull)")
    fetch_content(
        args.content_id,
        iface,
        src_mac,
        args.timeout,
        args.pcap,
        save=not args.no_save,
    )


if __name__ == "__main__":
    main()
