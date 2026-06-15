#!/usr/bin/env python3
"""Measure ICN content retrieval time (Interest send -> Data receive).

Pattern A: run multiple consecutive trials in the same Mininet session to
observe cache warm-up (trial 1 = cold, later trials = warm).
"""
import argparse
import statistics
import sys
import threading
import time

from icn_header import icn
from payload_header import payload
from scapy.all import AsyncSniffer, Ether, get_if_hwaddr, get_if_list, sendp

GATEWAY_MAC = "08:00:00:00:01:00"
INTEREST_ETHER_TYPE = 0x88B5


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


def run_benchmark(content_id, trials, interval, timeout, warm_start):
    iface = get_if()
    src_mac = get_if_hwaddr(iface)
    interest_pkt = build_interest(content_id, src_mac)

    trial_state = {"t_start": None, "event": None}

    def handle_pkt(pkt):
        if payload not in pkt:
            return
        if pkt[payload].content_id != content_id:
            return
        event = trial_state.get("event")
        t_start = trial_state.get("t_start")
        if event is None or t_start is None or event.is_set():
            return
        trial_state["latency_ms"] = (time.perf_counter() - t_start) * 1000.0
        event.set()

    sniffer = AsyncSniffer(iface=iface, prn=handle_pkt)
    sniffer.start()
    time.sleep(0.2)

    results = []
    print(f"content_id={content_id}, trials={trials}, interval={interval}s")
    print("trial,phase,latency_ms,status")

    for trial in range(1, trials + 1):
        phase = "cold" if trial == 1 else "warm"
        event = threading.Event()
        trial_state["t_start"] = None
        trial_state["event"] = event
        trial_state["latency_ms"] = None

        trial_state["t_start"] = time.perf_counter()
        sendp(interest_pkt, iface=iface, verbose=False)

        if not event.wait(timeout=timeout):
            print(f"{trial},{phase},,timeout", flush=True)
            results.append(None)
        else:
            latency_ms = trial_state["latency_ms"]
            print(f"{trial},{phase},{latency_ms:.3f},ok", flush=True)
            results.append(latency_ms)

        if trial < trials:
            time.sleep(interval)

    sniffer.stop()

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
        "-i", "--interval", type=float, default=0.2,
        help="Seconds between trials (default: 0.2)"
    )
    parser.add_argument(
        "-t", "--timeout", type=float, default=5.0,
        help="Seconds to wait for Data per trial (default: 5.0)"
    )
    parser.add_argument(
        "--warm-start", type=int, default=4,
        help="First trial index counted as warm in summary (default: 4)"
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
    )


if __name__ == "__main__":
    main()
