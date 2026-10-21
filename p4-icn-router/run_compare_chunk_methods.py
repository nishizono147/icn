#!/usr/bin/env python3
"""chunk_table と chunk_pull を同じ手順で交互に計測する。

1 セッション = Mininet 起動 → Producer 起動 → consumer_bench.py で連続 N 試行 → Mininet 停止。
全方式で同じ Consumer（consumer_bench.py）を使い、違いは Interest の送り方だけにする。
セッションごとに方式の実行順を入れ替え、時間による環境の変化が片方に偏らないようにする。

各試行で Data がどこから返ってきたか（source_switch）を記録し、MCD のキャッシュ移動
（1 回目 h2 → 2 回目 s3 → 3 回目 s2 → 4 回目以降 s1）と一致するかを確認する。

--content-id にカンマ区切りで複数の値を指定すると、1 セッションの中でコンテンツを順に計測する
（例: 1,2,...,10 でチャンク数ごとの取得時間）。コンテンツごとにキャッシュの位置（register の
index = content_id * 10 + chunk_id）が別なので、前のコンテンツの要求は次のコンテンツに影響しない。
コンテンツの順番はセッションごとに逆にする。

--link-delay を指定すると、全リンクに片道その遅延（Mininet の TCLink = tc netem）を付ける。
各方式の topology.json は書き換えず、遅延を書き足したものを作業フォルダに作って使う。
取得時間の開始は、遅延なしでは tcpdump の Interest の時刻、遅延ありでは Consumer が送信直前に
記録した時刻にする（tcpdump は h1 の送信パケットを遅延をかけた後に記録するため）。

root で実行する（root でなければ sudo PATH=$PATH を前に付ける）:
  python3 run_compare_chunk_methods.py -s 20 --content-id 10
  python3 run_compare_chunk_methods.py -s 20 --content-id 10 --link-delay 10ms
  python3 run_compare_chunk_methods.py -s 20 --content-id 1,2,3,4,5,6,7,8,9,10 --systems pull

以前の結果では、pull を pull-burst（残りの Interest をまとめて送る）と呼んでいた。
1 つずつ送る pull-sequential もあったが、使わないので削除した。
"""
import argparse
import csv
import json
import os
import statistics
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "..", "utils"))
from run_exercise import ExerciseRunner  # noqa: E402

CONSUMER = os.path.join(ROOT, "consumer_bench.py")
# content_id N = contentN.bin（N チャンク）。受け取った内容をこのファイルと照合する
CONTENT_FILES = {n: os.path.join(ROOT, "contents", f"content{n}.bin") for n in range(1, 11)}

SYSTEMS = {
    "table": {
        "dir": "chunk_table",
        "consumer_args": "--mode table",
    },
    "pull": {
        "dir": "chunk_pull",
        "consumer_args": "--mode pull",
    },
}
PRODUCER = "python3 send_content.py --quiet"
CHUNK_SIZE = 256


def expected_source(trial):
    """MCD のキャッシュ移動から期待される、その試行で Data を返す場所。"""
    return {1: "h2", 2: "s3", 3: "s2"}.get(trial, "s1")


def n_chunks(content_id):
    size = os.path.getsize(CONTENT_FILES[content_id])
    return (size + CHUNK_SIZE - 1) // CHUNK_SIZE


def build(dirs):
    for d in sorted(set(dirs)):
        subprocess.run(["make", "build"], cwd=os.path.join(ROOT, d), check=True,
                       stdout=subprocess.DEVNULL)


def parse_results(text):
    rows = []
    header = None
    for line in text.splitlines():
        if not line.startswith("RESULT,"):
            continue
        fields = line[len("RESULT,"):].split(",")
        if header is None:
            header = fields
            continue
        rows.append(dict(zip(header, fields)))
    return rows


def topology_file(project, tag, args, work_dir):
    """使う topology.json のパス。--link-delay があれば、全リンクに遅延を書き足したものを作る。"""
    if not args.link_delay:
        return "topology.json"
    with open(os.path.join(project, "topology.json")) as f:
        topo = json.load(f)
    # リンクは [node1, node2, latency, bandwidth]（latency と bandwidth は省略可）
    topo["links"] = [[link[0], link[1], args.link_delay] + link[3:] for link in topo["links"]]
    path = os.path.join(work_dir, f"{tag}_topology.json")
    with open(path, "w") as f:
        json.dump(topo, f, indent=2)
    return path


def run_session(system, session, content_ids, args, work_dir):
    cfg = SYSTEMS[system]
    project = os.path.join(ROOT, cfg["dir"])
    tag = f"{system}_s{session}"
    log_dir = os.path.join(work_dir, tag, "logs")
    pcap_dir = os.path.join(work_dir, tag, "pcaps")
    os.makedirs(os.path.dirname(log_dir), exist_ok=True)

    prev_cwd = os.getcwd()
    os.chdir(project)
    runner = ExerciseRunner(
        topology_file(project, tag, args, work_dir), log_dir, pcap_dir, "build/switch.json",
        bmv2_exe="simple_switch_grpc", quiet=True,
    )
    runner.create_network()
    net = runner.net
    try:
        net.start()
        time.sleep(1)
        runner.program_hosts()
        runner.program_switches()
        time.sleep(2)
        h1, h2 = net.get("h1"), net.get("h2")
        h2.cmd(f"{PRODUCER} > {work_dir}/{tag}_producer.log 2>&1 &")
        time.sleep(args.producer_wait)
        results = {}
        for cid in content_ids:
            # コンテンツが 1 つなら今までと同じファイル名にする（plot_timeline.py が読む）
            name = tag if len(args.content_ids) == 1 else f"{tag}_c{cid}"
            expect = CONTENT_FILES.get(cid)
            cmd = (
                f"python3 {CONSUMER} {cid} {cfg['consumer_args']} "
                f"-n {args.trials} -i {args.interval} -q "
                f"--start-time {'script' if args.link_delay else 'pcap'} "
                f"--pcap {work_dir}/{name}.pcap"
                + (f" --expect-file {expect}" if expect else "")
            )
            out = h1.cmd(cmd)
            with open(os.path.join(work_dir, f"{name}_consumer.log"), "w") as f:
                f.write(out)
            results[cid] = parse_results(out)
        h2.cmd("pkill -f send_content.py")
        return results
    finally:
        net.stop()
        os.chdir(prev_cwd)


def summarize(rows, systems, content_ids, trials):
    summary = []
    for system in systems:
        for cid in content_ids:
            for t in range(1, trials + 1):
                vals = [float(r["latency_ms"]) for r in rows
                        if r["system"] == system and r["content_id"] == cid
                        and int(r["trial"]) == t and r["status"] == "ok"]
                summary.append({
                    "system": system,
                    "content_id": cid,
                    "n_chunks": n_chunks(cid),
                    "trial": t,
                    "mean_ms": statistics.mean(vals) if vals else None,
                    "std_ms": statistics.stdev(vals) if len(vals) > 1 else None,
                    "n": len(vals),
                })
    return summary


def fmt(v, digits=2):
    return "-" if v is None else f"{v:.{digits}f}"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-s", "--sessions", type=int, default=10)
    parser.add_argument("-n", "--trials", type=int, default=10)
    parser.add_argument("-i", "--interval", type=float, default=0.2)
    parser.add_argument("--content-id", default="4",
                        help="コンテンツ ID（N = contentN.bin、N チャンク）。カンマ区切りで複数指定できる")
    parser.add_argument("--systems", default="table,pull",
                        help="カンマ区切り: " + ", ".join(SYSTEMS))
    parser.add_argument("--producer-wait", type=float, default=2.5)
    parser.add_argument("--link-delay", default="",
                        help="全リンクに付ける片道の遅延（例: 10ms）。省略すると遅延なし")
    parser.add_argument("--work-dir", default="/tmp/compare_chunk_methods",
                        help="BMv2 のログ・pcap・各セッションの出力の置き場所")
    parser.add_argument("--out-prefix", default=os.path.join(ROOT, "results", "csv", "compare_chunk_methods"))
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()

    systems = [s.strip() for s in args.systems.split(",") if s.strip()]
    args.content_ids = [int(c) for c in args.content_id.split(",") if c.strip()]
    for c in args.content_ids:
        if c not in CONTENT_FILES:
            parser.error(f"不明なコンテンツ ID: {c}")
    for s in systems:
        if s not in SYSTEMS:
            parser.error(f"不明な方式: {s}")
    if os.geteuid() != 0:
        sys.exit("root で実行すること（Mininet のため）")

    os.makedirs(args.work_dir, exist_ok=True)
    if not args.skip_build:
        build(SYSTEMS[s]["dir"] for s in systems)

    rows = []
    for session in range(1, args.sessions + 1):
        order = systems if session % 2 == 1 else list(reversed(systems))
        content_order = args.content_ids if session % 2 == 1 else list(reversed(args.content_ids))
        for system in order:
            print(f"=== session {session}/{args.sessions}: {system} ===", flush=True)
            per_content = run_session(system, session, content_order, args, args.work_dir)
            for cid in content_order:
                results = per_content[cid]
                if len(results) != args.trials:
                    print(f"  WARNING: content {cid} の結果が {len(results)} 試行分しかない", flush=True)
                for r in results:
                    r.update({"system": system, "session": session,
                              "content_id": cid, "n_chunks": n_chunks(cid),
                              "link_delay": args.link_delay or "0ms",
                              "start_time": "script" if args.link_delay else "pcap",
                              "expected_source": expected_source(int(r["trial"]))})
                    rows.append(r)
                ok = [float(r["latency_ms"]) for r in results if r["status"] == "ok"]
                if ok:
                    print(f"  content {cid}: ok={len(ok)}/{args.trials} trial1={ok[0]:.2f} ms "
                          f"mean={statistics.mean(ok):.2f} ms", flush=True)
            time.sleep(0.5)

    os.makedirs(os.path.dirname(args.out_prefix), exist_ok=True)
    raw_path = args.out_prefix + "_raw.csv"
    fields = ["system", "session", "content_id", "n_chunks", "trial", "link_delay", "start_time", "latency_ms", "latency_pcap_ms",
              "send_offset_ms", "status", "interests", "chunks",
              "sources", "expected_source", "max_gap_ms", "verified"]
    with open(raw_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    summary = summarize(rows, systems, args.content_ids, args.trials)
    summary_path = args.out_prefix + "_summary.csv"
    with open(summary_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["system", "content_id", "n_chunks", "trial", "mean_ms", "std_ms", "n"])
        w.writeheader()
        for s in summary:
            w.writerow({k: ("" if v is None else (f"{v:.4f}" if isinstance(v, float) else v))
                        for k, v in s.items()})

    # 取得時間（平均 ± 標準偏差）
    for cid in args.content_ids:
        print(f"\n=== content {cid}（{n_chunks(cid)} チャンク）: 取得時間 ms（平均 ± 標準偏差, n=成功セッション数）===")
        print("trial  返す場所  " + "  ".join(f"{s:>24}" for s in systems))
        for t in range(1, args.trials + 1):
            cells = []
            for s in systems:
                x = next(v for v in summary
                         if v["system"] == s and v["content_id"] == cid and v["trial"] == t)
                cells.append(f"{fmt(x['mean_ms']):>8} ± {fmt(x['std_ms']):>6} (n={x['n']:>2})")
            print(f"{t:>5}  {expected_source(t):>8}  " + "  ".join(f"{c:>24}" for c in cells))

    # 確認項目
    print("\n=== 確認 ===")
    for s in systems:
        rs = [r for r in rows if r["system"] == s]
        failed = [r for r in rs if r["status"] != "ok"]
        src_mismatch = [r for r in rs if r["status"] == "ok"
                        and set(r["sources"].split(";")) != {r["expected_source"]}]
        not_verified = [r for r in rs if r["status"] == "ok" and r.get("verified") not in ("yes", "-")]
        gaps = [float(r["max_gap_ms"]) for r in rs if r.get("max_gap_ms")]
        offsets = [float(r["send_offset_ms"]) for r in rs if r.get("send_offset_ms")]
        print(f"{s}: 試行 {len(rs)}, 失敗 {len(failed)}, "
              f"返す場所が想定と違う {len(src_mismatch)}, 内容不一致 {len(not_verified)}"
              + (f", チャンク間の空き 最大 {max(gaps):.3f} ms / 平均 {statistics.mean(gaps):.3f} ms"
                 if gaps else ""))
        if offsets:
            # pcap の最初の Interest の時刻 − Consumer が記録した送信時刻。遅延なしでほぼ 0、h1 のリンクに片道 d なら約 d
            print(f"  送信時刻のずれ（pcap − 記録）: 平均 {statistics.mean(offsets):.3f} ms, "
                  f"最小 {min(offsets):.3f} ms, 最大 {max(offsets):.3f} ms")
        for r in src_mismatch[:5]:
            print(f"  session {r['session']} content {r['content_id']} trial {r['trial']}: "
                  f"sources={r['sources']} expected={r['expected_source']}")

    print(f"\nSaved: {raw_path}\nSaved: {summary_path}")


if __name__ == "__main__":
    main()
