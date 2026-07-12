#!/usr/bin/env python3
"""Generate final production-oriented fixed-length ICN packet header diagram."""

import os
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyBboxPatch

OUT = os.path.join(os.path.dirname(__file__), "architecture_packet_final.png")

for _font in ("Noto Sans CJK JP", "IPAGothic", "TakaoGothic", "VL Gothic"):
    try:
        plt.rcParams["font.family"] = _font
        break
    except Exception:
        pass


def band(ax, y, h, x0, w, fc, ec, lw=1.2):
    ax.add_patch(Rectangle((x0, y - h / 2), w, h, facecolor=fc, edgecolor=ec, lw=lw))


def fields(ax, y, h, x0, w, items, fs=7.5, ec="#333"):
    total = sum(s for _, s in items)
    cx = x0
    for name, share in items:
        fw = w * share / total
        ax.add_patch(Rectangle((cx, y - h / 2), fw, h, facecolor="white", edgecolor=ec, lw=0.8))
        ax.text(cx + fw / 2, y, name, ha="center", va="center", fontsize=fs)
        cx += fw


def label(ax, x, y, text, fs=9, bold=False):
    ax.text(
        x,
        y,
        text,
        ha="center",
        va="center",
        fontsize=fs,
        fontweight="bold" if bold else "normal",
    )


def draw():
    fig, ax = plt.subplots(figsize=(15, 11))
    ax.set_xlim(0, 15)
    ax.set_ylim(0, 11)
    ax.axis("off")

    ax.text(
        7.5,
        10.55,
        "過渡期 ICN パケット構成（確定版・固定長 / P4 対応）",
        ha="center",
        fontsize=14,
        fontweight="bold",
    )
    ax.text(
        7.5,
        10.05,
        "Phase 2: L2 → IPv4 → ICN  |  可変長なし（常に固定 extract）  |  Data は 0 パディング",
        ha="center",
        fontsize=9,
        color="#555",
    )

    x0, bw = 2.0, 11.0
    lh = 0.72

    # ── Interest ──
    y = 9.0
    label(ax, 1.0, y, "Interest\nパケット", fs=10, bold=True)
    ax.plot([1.55, x0], [y, y], color="#888", lw=1)

    band(ax, y, lh * 0.85, x0, bw, "#fff3e0", "#e65100")
    fields(
        ax,
        y,
        lh * 0.72,
        x0 + 0.06,
        bw - 0.12,
        [("dst MAC (6B)", 6), ("src MAC (6B)", 6), ("EtherType 0x0800", 4)],
        fs=7.5,
        ec="#e65100",
    )
    ax.text(x0 + bw + 0.35, y, "L2\n14B", va="center", fontsize=8, color="#e65100")

    y -= lh + 0.12
    band(ax, y, lh * 1.05, x0, bw, "#e3f2fd", "#1565c0")
    fields(
        ax,
        y + 0.1,
        lh * 0.38,
        x0 + 0.06,
        bw - 0.12,
        [
            ("Ver/IHL", 2),
            ("Total Len", 2),
            ("TTL", 1),
            ("Proto=ICN", 1),
            ("Checksum", 2),
        ],
        fs=6.5,
        ec="#1565c0",
    )
    fields(
        ax,
        y - 0.22,
        lh * 0.38,
        x0 + 0.06,
        bw - 0.12,
        [("src IP = Consumer（転送時も維持）", 5), ("dst IP = 次ホップ IWP", 5)],
        fs=7,
        ec="#1565c0",
    )
    ax.text(x0 + bw + 0.35, y, "L3\nIPv4\n20B", va="center", fontsize=8, color="#1565c0")

    y -= lh + 0.28
    band(ax, y, lh * 0.9, x0, bw, "#e8f5e9", "#2e7d32")
    fields(
        ax,
        y,
        lh * 0.72,
        x0 + 0.06,
        bw - 0.12,
        [
            ("version (8)", 1),
            ("type (8)", 1),
            ("flags (8)", 1),
            ("hop_limit (8)", 1),
        ],
        fs=7.5,
        ec="#2e7d32",
    )
    ax.text(x0 + bw + 0.35, y, "ICN\nメタ\n4B", va="center", fontsize=8, color="#2e7d32")

    y -= lh + 0.05
    band(ax, y, lh * 1.35, x0, bw, "#c8e6c9", "#1b5e20")
    fields(
        ax,
        y,
        lh * 1.1,
        x0 + 0.06,
        bw - 0.12,
        [
            (
                "content_name (256B 固定)\n"
                "例: /jp/co/example/video/001 + 0x00 パディング\n"
                "→ FIB(LPM)  /  hash(name) → PIT・LCST・ECST",
                1,
            ),
        ],
        fs=8,
        ec="#1b5e20",
    )
    ax.text(x0 + bw + 0.35, y, "ICN\n260B\n計", va="center", fontsize=8, color="#1b5e20")

    y -= 0.55
    ax.text(
        x0 + bw / 2,
        y,
        "Interest 合計 ≈ 14 + 20 + 260 = 294 B",
        ha="center",
        fontsize=8.5,
        color="#333",
        style="italic",
    )

    # ── Data ──
    y = 4.55
    label(ax, 1.0, y, "Data\nパケット", fs=10, bold=True)
    ax.plot([1.55, x0], [y, y], color="#888", lw=1)

    band(ax, y, lh * 0.85, x0, bw, "#fff3e0", "#e65100")
    fields(
        ax,
        y,
        lh * 0.72,
        x0 + 0.06,
        bw - 0.12,
        [("dst MAC", 6), ("src MAC", 6), ("0x0800", 4)],
        fs=7.5,
        ec="#e65100",
    )

    y -= lh + 0.12
    band(ax, y, lh * 1.05, x0, bw, "#e3f2fd", "#1565c0")
    fields(
        ax,
        y + 0.1,
        lh * 0.38,
        x0 + 0.06,
        bw - 0.12,
        [("IPv4 固定部", 4), ("Proto=ICN", 2), ("Checksum 等", 4)],
        fs=6.5,
        ec="#1565c0",
    )
    fields(
        ax,
        y - 0.22,
        lh * 0.38,
        x0 + 0.06,
        bw - 0.12,
        [("src IP = 返却 IWP", 5), ("dst IP = Consumer", 5)],
        fs=7,
        ec="#1565c0",
    )

    y -= lh + 0.28
    band(ax, y, lh * 1.15, x0, bw, "#f3e5f5", "#6a1b9a")
    fields(
        ax,
        y + 0.18,
        lh * 0.38,
        x0 + 0.06,
        bw - 0.12,
        [("name_hash (128bit = 16B)", 4)],
        fs=7.5,
        ec="#6a1b9a",
    )
    fields(
        ax,
        y - 0.08,
        lh * 0.32,
        x0 + 0.06,
        bw - 0.12,
        [("chunk_id (32)", 2), ("total_chunks (32)", 2), ("flags (8)", 1), ("iwp_id (16)", 1.5), ("reserved (16)", 1.5)],
        fs=6.8,
        ec="#6a1b9a",
    )
    ax.text(
        x0 + bw + 0.35,
        y,
        "ICN\nメタ\n29B",
        va="center",
        fontsize=8,
        color="#6a1b9a",
    )

    y -= lh + 0.18
    band(ax, y, lh * 1.35, x0, bw, "#e1bee7", "#4a148c")
    fields(
        ax,
        y,
        lh * 1.1,
        x0 + 0.06,
        bw - 0.12,
        [
            (
                "chunk_data (1440B 固定)\n"
                "最終 chunk も 1440B（端数 + 0x00 パディング）\n"
                "→ PIT/LCST は name_hash + chunk_id",
                1,
            ),
        ],
        fs=8,
        ec="#4a148c",
    )
    ax.text(x0 + bw + 0.35, y, "ICN\n1469B\n計", va="center", fontsize=8, color="#4a148c")

    y -= 0.55
    ax.text(
        x0 + bw / 2,
        y,
        "Data 合計 ≈ 14 + 20 + 1469 = 1503 B（MTU 1500 環境では要調整 or ジャンボ）",
        ha="center",
        fontsize=8.5,
        color="#333",
        style="italic",
    )

    # Legend box
    y = 0.95
    ax.add_patch(
        FancyBboxPatch(
            (0.5, 0.15),
            14.0,
            1.55,
            boxstyle="round,pad=0.02,rounding_size=0.08",
            facecolor="#fafafa",
            edgecolor="#bbb",
        )
    )
    legend = (
        "【確定ルール】\n"
        "・Interest: コンテンツ名そのもの（256B 固定）→ FIB。PIT/LCST/ECST は hash(name)（ワイヤに載せない）\n"
        "・Data: name_hash のみ（名前全文なし）。chunk_data 1440B 固定、0 パディング。payload_len / content_length なし\n"
        "・Consumer IP: IPv4.srcAddr（ICN 層には載せない）"
    )
    ax.text(7.5, 0.92, legend, ha="center", va="center", fontsize=8.2, linespacing=1.45)

    fig.savefig(OUT, dpi=170, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return OUT


if __name__ == "__main__":
    path = draw()
    print(f"Wrote {path}")
