#!/usr/bin/env python3
"""chunk_table / chunk_pull 共通の Consumer 計測スクリプト（h1 で実行）。

両方式で受信・送信・時間計算のコードを共通にし、違いは Interest の送り方だけにする。

  --mode table : Interest を 1 本送る。スイッチ（または Producer）が全チャンクを返す
  --mode pull  : chunk 0 の Interest を送り、Data の total_chunks でチャンク数 N を知る
      --pull-strategy sequential : 前のチャンクが届いてから次の Interest を送る
      --pull-strategy burst      : chunk 0 が届いたら chunk 1..N-1 の Interest をまとめて送る

Data は AF_PACKET ソケットで直接受け取り、Interest は事前に組み立てたバイト列を送る。
pcap ファイルの読み直しや Scapy の送信処理がチャンクの間に入らないようにするため。

取得時間は試行がすべて終わった後に tcpdump の pcap 時刻から計算する。
  開始: その試行の最初の Interest が h1 から出た時刻
  終了: 全チャンクがそろった時刻（最後に届いた未受信チャンクの Data の時刻）
"""
import argparse
import os
import select
import signal
import socket
import statistics
import struct
import subprocess
import sys
import time

GATEWAY_MAC = "08:00:00:00:01:00"
INTEREST_ETHER_TYPE = 0x88B5
DATA_ETHER_TYPE = 0x88B6
ICN_TYPE = 0x11
CHUNK_SIZE = 256
MAX_CHUNKS = 10  # switch.p4 のキャッシュは content_id * 10 + chunk_id

# Data: Ethernet(14) + content_id(4) + total_chunks(2) + chunk_id(2) + flag(1) + source_switch(1) + data(256)
DATA_HDR = struct.Struct("!IHHBB")
DATA_HDR_OFFSET = 14
DATA_PAYLOAD_OFFSET = DATA_HDR_OFFSET + DATA_HDR.size

SOURCE_NAMES = {0: "h2", 1: "s1", 2: "s2", 3: "s3"}

RESULT_FIELDS = [
    "trial", "latency_ms", "interests", "chunks", "sources",
    "max_gap_ms", "verified", "status",
]


def get_iface():
    for name in sorted(os.listdir("/sys/class/net")):
        if "eth0" in name:
            return name
    sys.exit("eth0 インターフェースが見つからない")


def get_mac(iface):
    with open(f"/sys/class/net/{iface}/address") as f:
        return f.read().strip()


def mac_bytes(mac):
    return bytes(int(x, 16) for x in mac.split(":"))


def build_interest(mode, content_id, chunk_id, src_mac):
    eth = mac_bytes(GATEWAY_MAC) + mac_bytes(src_mac) + struct.pack("!H", INTEREST_ETHER_TYPE)
    if mode == "table":
        # chunk_table の ICNHeader: content_id, type, flag, source_switch
        return eth + struct.pack("!IHBB", content_id, ICN_TYPE, 1, 0)
    # chunk_pull の ICNHeader: 上に chunk_id を追加
    return eth + struct.pack("!IHBBH", content_id, ICN_TYPE, 1, 0, chunk_id)


def parse_data(frame):
    """Data フレームなら (content_id, total_chunks, chunk_id, source_switch, data) を返す。"""
    if len(frame) < DATA_PAYLOAD_OFFSET:
        return None
    if struct.unpack_from("!H", frame, 12)[0] != DATA_ETHER_TYPE:
        return None
    content_id, total, chunk_id, _flag, source = DATA_HDR.unpack_from(frame, DATA_HDR_OFFSET)
    data = frame[DATA_PAYLOAD_OFFSET:DATA_PAYLOAD_OFFSET + CHUNK_SIZE]
    return content_id, total, chunk_id, source, data


def start_tcpdump(iface, pcap_path):
    if os.path.exists(pcap_path):
        os.remove(pcap_path)
    proc = subprocess.Popen(
        [
            # --immediate-mode: 受け取ったパケットをためずにすぐ書き出す。
            # これがないと最大約 1 秒バッファされ、停止時に最後の試行が欠ける
            "tcpdump", "-i", iface, "-w", pcap_path, "-U", "-n", "--immediate-mode",
            "ether", "proto", f"0x{INTEREST_ETHER_TYPE:04x}",
            "or", "ether", "proto", f"0x{DATA_ETHER_TYPE:04x}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(0.3)
    if proc.poll() is not None:
        sys.exit("tcpdump の起動に失敗")
    return proc


def stop_tcpdump(proc):
    # 最後のパケットが書き出されるのを待ってから止める
    time.sleep(0.3)
    if proc.poll() is None:
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)


def read_pcap(pcap_path):
    """pcap を読み、(時刻[秒], フレーム) のリストを返す。"""
    with open(pcap_path, "rb") as f:
        buf = f.read()
    if len(buf) < 24:
        return []
    magic = struct.unpack_from("<I", buf, 0)[0]
    if magic in (0xA1B2C3D4, 0xA1B23C4D):
        endian = "<"
    else:
        endian = ">"
        magic = struct.unpack_from(">I", buf, 0)[0]
    frac = 1e-9 if magic == 0xA1B23C4D else 1e-6
    rec = struct.Struct(endian + "IIII")
    packets = []
    off = 24
    while off + rec.size <= len(buf):
        ts_sec, ts_frac, incl_len, _orig = rec.unpack_from(buf, off)
        off += rec.size
        packets.append((ts_sec + ts_frac * frac, buf[off:off + incl_len]))
        off += incl_len
    return packets


def analyze_pcap(packets, mode, content_id):
    """pcap を試行ごとに区切り、取得時間などを計算する。

    試行の区切りは「その試行の最初の Interest」。table では Interest 1 本ごと、
    pull では chunk 0 の Interest ごとに新しい試行とみなす。
    """
    trials = []
    cur = None
    for ts, frame in packets:
        if len(frame) < 18:
            continue
        ether_type = struct.unpack_from("!H", frame, 12)[0]
        if ether_type == INTEREST_ETHER_TYPE:
            if struct.unpack_from("!I", frame, 14)[0] != content_id:
                continue
            chunk_id = struct.unpack_from("!H", frame, 22)[0] if mode == "pull" else 0
            if mode == "table" or chunk_id == 0:
                cur = {"start": ts, "interests": [], "data": []}
                trials.append(cur)
            if cur is not None:
                cur["interests"].append(ts)
        elif ether_type == DATA_ETHER_TYPE and cur is not None:
            parsed = parse_data(frame)
            if parsed and parsed[0] == content_id:
                cur["data"].append((ts, parsed[1], parsed[2], parsed[3]))

    results = []
    for t in trials:
        first_seen = {}
        total = None
        end = None
        for ts, tot, chunk_id, source in t["data"]:
            total = tot
            if chunk_id not in first_seen:
                first_seen[chunk_id] = (ts, source)
                if total and len(first_seen) == total:
                    end = ts
                    break
        # チャンク間の空き時間: 2 本目以降の Interest が、直前に届いた Data から何 ms 後に出たか
        gaps = []
        for its in t["interests"][1:]:
            before = [ts for ts, *_ in t["data"] if ts <= its]
            if before:
                gaps.append((its - max(before)) * 1000.0)
        results.append({
            "latency_ms": None if end is None else (end - t["start"]) * 1000.0,
            "interests": len(t["interests"]),
            "chunks": len(first_seen),
            "sources": [first_seen[c][1] for c in sorted(first_seen)],
            "max_gap_ms": max(gaps) if gaps else None,
        })
    return results


def drain(sock):
    while True:
        r, _, _ = select.select([sock], [], [], 0)
        if not r:
            return
        sock.recv(65535)


def fetch_once(mode, strategy, content_id, rx, tx, interests, timeout):
    """1 試行分の取得。受信したチャンク {chunk_id: data} と送った Interest の数を返す。"""
    received = {}
    total = None
    sent = 1
    next_chunk = 1  # sequential で次に要求するチャンク
    burst_done = False
    tx.send(interests[0])
    deadline = time.monotonic() + timeout

    while total is None or len(received) < total:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        r, _, _ = select.select([rx], [], [], remaining)
        if not r:
            break
        parsed = parse_data(rx.recv(65535))
        if not parsed or parsed[0] != content_id:
            continue
        _cid, tot, chunk_id, _source, data = parsed
        if chunk_id in received:
            continue
        received[chunk_id] = data
        total = tot
        if total > MAX_CHUNKS:
            sys.exit(f"total_chunks={total} が上限 {MAX_CHUNKS} を超えている")

        if mode == "pull":
            if strategy == "burst" and not burst_done:
                for c in range(1, total):
                    tx.send(interests[c])
                sent += total - 1
                burst_done = True
            elif strategy == "sequential" and chunk_id == next_chunk - 1 and next_chunk < total:
                tx.send(interests[next_chunk])
                sent += 1
                next_chunk += 1
    return received, total, sent


def verify(received, total, expected):
    if expected is None:
        return "-"
    if total is None or len(received) < total:
        return "no"
    body = b"".join(received[c] for c in range(total))
    ok = body[:len(expected)] == expected and not body[len(expected):].strip(b"\x00")
    return "yes" if ok else "no"


def run(args):
    iface = get_iface()
    src_mac = get_mac(iface)
    n_interests = 1 if args.mode == "table" else MAX_CHUNKS
    interests = [build_interest(args.mode, args.content_id, c, src_mac) for c in range(n_interests)]

    expected = None
    if args.expect_file:
        with open(args.expect_file, "rb") as f:
            expected = f.read()

    rx = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(DATA_ETHER_TYPE))
    rx.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
    rx.bind((iface, DATA_ETHER_TYPE))
    tx = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, 0)
    tx.bind((iface, 0))

    label = args.mode if args.mode == "table" else f"pull-{args.pull_strategy}"
    print(f"# mode={label} content_id={args.content_id} trials={args.trials} "
          f"interval={args.interval}s iface={iface}", flush=True)

    tcpdump = start_tcpdump(iface, args.pcap)
    script_side = []
    try:
        for trial in range(1, args.trials + 1):
            drain(rx)
            received, total, sent = fetch_once(
                args.mode, args.pull_strategy, args.content_id, rx, tx, interests, args.timeout,
            )
            complete = total is not None and len(received) == total
            script_side.append((complete, sent, verify(received, total, expected)))
            if not args.quiet:
                state = "ok" if complete else f"timeout ({len(received)}/{total} chunks)"
                print(f"# trial {trial}: {state}", flush=True)
            if trial < args.trials:
                time.sleep(args.interval)
    finally:
        stop_tcpdump(tcpdump)
        rx.close()
        tx.close()

    pcap_results = analyze_pcap(read_pcap(args.pcap), args.mode, args.content_id)
    if len(pcap_results) != args.trials:
        print(f"# WARNING: pcap 上の試行数 {len(pcap_results)} が実行した試行数 {args.trials} と一致しない",
              flush=True)

    print("RESULT," + ",".join(RESULT_FIELDS), flush=True)
    latencies = []
    for i in range(args.trials):
        complete, sent, verified = script_side[i]
        p = pcap_results[i] if i < len(pcap_results) else None
        if p is None or not complete or p["latency_ms"] is None:
            status = "timeout"
            latency = ""
        else:
            status = "ok"
            latency = f"{p['latency_ms']:.3f}"
            latencies.append(p["latency_ms"])
        row = [
            str(i + 1),
            latency,
            str(p["interests"] if p else sent),
            str(p["chunks"] if p else 0),
            ";".join(SOURCE_NAMES.get(s, str(s)) for s in p["sources"]) if p else "",
            "" if not p or p["max_gap_ms"] is None else f"{p['max_gap_ms']:.3f}",
            verified,
            status,
        ]
        print("RESULT," + ",".join(row), flush=True)

    if latencies:
        print(f"# summary: ok={len(latencies)}/{args.trials} "
              f"mean={statistics.mean(latencies):.3f} ms "
              f"min={min(latencies):.3f} ms max={max(latencies):.3f} ms", flush=True)
    return 0 if len(latencies) == args.trials else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("content_id", type=int, help="コンテンツ ID（4 = image4.png）")
    parser.add_argument("--mode", choices=["table", "pull"], required=True)
    parser.add_argument("--pull-strategy", choices=["sequential", "burst"], default="burst")
    parser.add_argument("-n", "--trials", type=int, default=10)
    parser.add_argument("-i", "--interval", type=float, default=0.2)
    parser.add_argument("-t", "--timeout", type=float, default=5.0, help="1 試行のタイムアウト（秒）")
    parser.add_argument("--pcap", default="/tmp/consumer_bench.pcap")
    parser.add_argument("--expect-file", help="受信内容を照合する元ファイル")
    parser.add_argument("-q", "--quiet", action="store_true")
    sys.exit(run(parser.parse_args()))


if __name__ == "__main__":
    main()
