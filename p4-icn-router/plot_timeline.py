#!/usr/bin/env python3
"""1 回の取得の中で、各パケットがいつ、どのノードを通ったかを図にする（chunk_table と chunk_pull の比較用）。

run_compare_chunk_methods.py を --work-dir 付きで実行し、そのディレクトリに残った
h1 の記録（<方式>_s<番号>.pcap）と、BMv2 が各スイッチのポートで取った記録（<方式>_s<番号>/pcaps/）を読む。

  python3 plot_timeline.py <work_dir> --session 1 --trial 5 --out results/png/timeline_s1.png
  （trial 5 = s1 から返す回、trial 3 = s2 から返す回）

縦軸はノード（h1, s1, s2, s3）、横軸はその回の最初の Interest を h1 が送ってからの時間。
同じパケットがノードを通った時刻を線でつなぐ。スイッチの中にいた時間（受け取ってから送り出すまで）は横向きの太い線になる。
"""
import argparse
import os
import struct

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

try:
    import matplotlib_fontja  # noqa: F401,E402
except ImportError:
    plt.rcParams["font.sans-serif"] = ["Noto Sans CJK JP", "IPAexGothic", "DejaVu Sans"]

INTEREST, DATA = 0x88B5, 0x88B6
Y = {"h1": 0, "s1": 1, "s2": 2, "s3": 3}
COLOR = {"I": "#2a78d6", "D": "#eb6834"}
TEXT, TEXT2, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#fcfcfb"
SOURCE = {1: "h2", 2: "s3", 3: "s2"}
SERVE_NAME = {v: k for k, v in Y.items()}

# (ノード, 受け取るポートの pcap, 送り出すポートの pcap)。ポートの向きは topology.json に合わせる
#   s1: eth1 = h1 側, eth2 = s2 側 / s2: eth1 = s1 側, eth2 = s3 側 / s3: eth2 = s2 側, eth1 = h2 側
UP = [("s1", "s1-eth1_in", "s1-eth2_out"), ("s2", "s2-eth1_in", "s2-eth2_out"), ("s3", "s3-eth2_in", "s3-eth1_out")]
DOWN = [("s3", "s3-eth1_in", "s3-eth2_out"), ("s2", "s2-eth2_in", "s2-eth1_out"), ("s1", "s1-eth2_in", "s1-eth1_out")]


def read_pcap(path):
    if not os.path.exists(path):
        return []
    buf = open(path, "rb").read()
    if len(buf) < 24:
        return []
    magic = struct.unpack_from("<I", buf, 0)[0]
    endian = "<" if magic in (0xA1B2C3D4, 0xA1B23C4D) else ">"
    if endian == ">":
        magic = struct.unpack_from(">I", buf, 0)[0]
    frac = 1e-9 if magic == 0xA1B23C4D else 1e-6
    rec = struct.Struct(endian + "IIII")
    out, off = [], 24
    while off + rec.size <= len(buf):
        sec, sub, incl, _ = rec.unpack_from(buf, off)
        off += rec.size
        out.append((sec + sub * frac, buf[off:off + incl]))
        off += incl
    return out


def classify(frame, mode):
    """('I', chunk_id) か ('D', chunk_id) を返す。table の Interest は chunk_id を 0 とする。"""
    if len(frame) < 18:
        return None
    et = struct.unpack_from("!H", frame, 12)[0]
    if et == INTEREST:
        cid = struct.unpack_from("!H", frame, 22)[0] if mode == "pull" and len(frame) >= 24 else 0
        return ("I", cid)
    if et == DATA and len(frame) >= 22:
        return ("D", struct.unpack_from("!H", frame, 20)[0])
    return None


def first_times(packets, mode, t0, t1, kind):
    """時間の窓 [t0, t1] の中で、種類 kind の各チャンクが最初に現れた時刻（ms）。"""
    res = {}
    for ts, fr in packets:
        if not (t0 - 0.001 <= ts <= t1):
            continue
        k = classify(fr, mode)
        if k and k[0] == kind and k[1] not in res:
            res[k[1]] = (ts - t0) * 1000.0
    return res


def load_trial(work_dir, system, session, trial):
    mode = "table" if system == "table" else "pull"
    # 以前の計測では pull を pull-burst という名前で保存している
    if system == "pull" and not os.path.exists(os.path.join(work_dir, f"pull_s{session}.pcap")):
        system = "pull-burst"
    h1 = read_pcap(os.path.join(work_dir, f"{system}_s{session}.pcap"))
    starts = []
    for ts, fr in h1:
        k = classify(fr, mode)
        if k and k[0] == "I" and k[1] == 0:
            starts.append(ts)
    t0 = starts[trial - 1]
    t1 = starts[trial] - 0.01 if trial < len(starts) else t0 + 0.2
    pc = os.path.join(work_dir, f"{system}_s{session}", "pcaps")
    sw = {name: read_pcap(os.path.join(pc, f"{name}.pcap")) for _, a, b in UP + DOWN for name in (a, b)}

    paths = []  # (種類, chunk, [(t, y), ...])
    h1_i = first_times(h1, mode, t0, t1, "I")
    h1_d = first_times(h1, mode, t0, t1, "D")
    for c, t in sorted(h1_i.items()):
        pts = [(t, Y["h1"])]
        for node, pin, pout in UP:
            ti = first_times(sw[pin], mode, t0, t1, "I").get(c)
            if ti is None:
                break
            pts.append((ti, Y[node]))
            to = first_times(sw[pout], mode, t0, t1, "I").get(c)
            if to is None:
                break  # このスイッチでキャッシュから返した（Interest はここで終わる）
            pts.append((to, Y[node]))
        paths.append(("I", c, pts))

    for c, t_h1 in sorted(h1_d.items()):
        pts = []
        for node, pin, pout in DOWN:
            ti = first_times(sw[pin], mode, t0, t1, "D").get(c)
            to = first_times(sw[pout], mode, t0, t1, "D").get(c)
            if to is None:
                continue
            if ti is not None:
                pts.append((ti, Y[node]))
            pts.append((to, Y[node]))
        pts.append((t_h1, Y["h1"]))
        paths.append(("D", c, pts))
    return paths, max(h1_d.values()) if h1_d else 0.0


def serving_events(paths):
    """キャッシュを持つスイッチの高さと、そこに Interest が届いた時刻・Data が出た時刻（チャンクごと）。"""
    i_arr, d_out = {}, {}
    serve_y = None
    for kind, c, pts in paths:
        if kind == "I":
            i_arr[c] = pts[-1][0]
            serve_y = pts[-1][1] if serve_y is None else serve_y
        else:
            d_out[c] = pts[0][0]
    return serve_y, i_arr, d_out


def draw(ax, paths, total, title, ymax, mode):
    serve_y, i_arr, d_out = serving_events(paths)
    for kind, c, pts in paths:
        xs, ys = zip(*pts)
        ax.plot(xs, ys, color=COLOR[kind], linewidth=1.2, alpha=0.9, solid_capstyle="round")
        # スイッチの中にいた時間（同じ高さの 2 点）を太く描く。隣り合うチャンクは少し上下にずらす
        off = (0.07 if c % 2 else -0.07) if kind == "D" else 0.0
        for (xa, ya), (xb, yb) in zip(pts, pts[1:]):
            if ya == yb and ya > 0:
                ax.plot([xa, xb], [ya + off] * 2, color=COLOR[kind], linewidth=4, alpha=0.55,
                        solid_capstyle="butt")
        ax.plot(xs[-1], ys[-1], "o", color=COLOR[kind], markersize=4, markeredgecolor=SURFACE,
                markeredgewidth=0.8)

    # キャッシュを持つスイッチの中：Interest が届いてから Data を出すまで（点線）
    y = serve_y
    if mode == "table":
        if 0 in i_arr and 0 in d_out:
            ax.plot([i_arr[0], d_out[0]], [y, y], color=TEXT2, linewidth=1.5, linestyle=":")
        for c in sorted(d_out)[1:]:
            ax.plot([d_out[c - 1], d_out[c]], [y + 0.12] * 2, color=TEXT2, linewidth=1.5, linestyle=":")
    else:
        for c in sorted(d_out):
            if c in i_arr:
                ax.plot([i_arr[c], d_out[c]], [y + (0.12 if c else 0)] * 2, color=TEXT2, linewidth=1.5,
                        linestyle=":")
        if 0 in d_out and 1 in i_arr:  # chunk 0 を出してから、残りの最初の Interest が届くまでの待ち
            w0, w1 = d_out[0], i_arr[1]
            ax.annotate("", xy=(w1, y + 0.38), xytext=(w0, y + 0.38),
                        arrowprops=dict(arrowstyle="<->", color=TEXT2, linewidth=1))
            ax.annotate(f"{SERVE_NAME[y]} の待ち {w1 - w0:.2f} ms", ((w0 + w1) / 2, y + 0.42),
                        ha="center", va="bottom", fontsize=8, color=TEXT2)
    gaps = [d_out[c] - d_out[c - 1] for c in sorted(d_out)[2:] if c - 1 in d_out]
    if gaps:
        ax.annotate(f"{SERVE_NAME[y]} が chunk 1 以降の Data を出す間隔：平均 {sum(gaps) / len(gaps):.2f} ms",
                    (0.01, 0.02), xycoords="axes fraction", fontsize=8, color=TEXT2)

    ax.axvline(total, color=MUTED, linewidth=1, linestyle="--")
    ax.annotate(f"最後のチャンクが届く {total:.2f} ms", (total, ymax + 0.55), ha="right", va="bottom",
                fontsize=8, color=TEXT2, xytext=(-3, 0), textcoords="offset points")
    ax.set_title(title, loc="left", fontsize=10, color=TEXT)
    ax.set_yticks(range(ymax + 1))
    ax.set_yticklabels([n for n, _ in sorted(Y.items(), key=lambda x: x[1])][:ymax + 1])
    ax.set_ylim(-0.4, ymax + 0.9)
    ax.grid(True, axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(MUTED)
    ax.tick_params(colors=MUTED, labelcolor=TEXT2)
    ax.set_facecolor(SURFACE)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("work_dir")
    ap.add_argument("--session", type=int, default=1)
    ap.add_argument("--trial", type=int, required=True, help="何回目の取得か（MCD で返す場所が決まる: 3 = s2, 5 = s1）")
    ap.add_argument("--chunks", type=int, default=10, help="図の見出し用")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    where = SOURCE.get(args.trial, "s1")
    ymax = {"h2": 3, "s3": 3, "s2": 2, "s1": 1}[where]
    t_tab, total_t = load_trial(args.work_dir, "table", args.session, args.trial)
    t_pul, total_p = load_trial(args.work_dir, "pull", args.session, args.trial)
    xmax = max(total_t, total_p) * 1.06

    fig, axes = plt.subplots(2, 1, figsize=(10, 2.2 + 1.3 * (ymax + 1)), sharex=True)
    fig.patch.set_facecolor(SURFACE)
    draw(axes[0], t_tab, total_t, "chunk_table（Interest 1 本、スイッチがループで 1 つずつ作る）", ymax, "table")
    draw(axes[1], t_pul, total_p, "chunk_pull（chunk 0 の後に残りの Interest をまとめて送る）", ymax, "pull")
    axes[1].set_xlim(-0.1, xmax)
    axes[1].set_xlabel("最初の Interest を送ってからの時間 (ms)", fontsize=9, color=TEXT2)

    handles = [plt.Line2D([], [], color=COLOR["I"], linewidth=2, label="Interest"),
               plt.Line2D([], [], color=COLOR["D"], linewidth=2, label="Data"),
               plt.Line2D([], [], color=MUTED, linewidth=4, alpha=0.55, label="スイッチの中にいた時間（太線）"),
               plt.Line2D([], [], color=TEXT2, linewidth=1.5, linestyle=":",
                          label="キャッシュを持つスイッチ：Interest が届いてから Data を出すまで／table のループの間隔（点線）")]
    fig.suptitle(f"{args.chunks} チャンクを {where} から返す場合のパケットの動き（1 回の取得の例）",
                 fontsize=11, color=TEXT, x=0.01, ha="left", y=0.99)
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.01, 0.94), ncol=2, frameon=False,
               fontsize=9, labelcolor=TEXT)
    fig.tight_layout(rect=(0, 0, 1, 0.86))
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    fig.savefig(args.out, dpi=150, facecolor=SURFACE)
    print(f"Saved: {args.out}")


if __name__ == "__main__":
    main()
