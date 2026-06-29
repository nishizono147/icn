#!/usr/bin/env python3
"""Generate L1/L2/IP/ICN packet structure diagram."""

import os
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle

OUT_DIR = os.path.dirname(__file__)
OUT_PATH = os.path.join(OUT_DIR, "architecture_packet_structure.png")

# Japanese font if available
for _font in ("Noto Sans CJK JP", "IPAGothic", "TakaoGothic", "VL Gothic"):
    try:
        plt.rcParams["font.family"] = _font
        break
    except Exception:
        pass


def _layer_band(ax, y, h, x0, width, label, fc, ec, label_w=1.35):
    """Left label + main band."""
    ax.add_patch(
        FancyBboxPatch(
            (0.15, y - h / 2),
            label_w,
            h,
            boxstyle="round,pad=0.01,rounding_size=0.05",
            linewidth=1.2,
            edgecolor=ec,
            facecolor=fc,
            alpha=0.35,
        )
    )
    ax.text(0.15 + label_w / 2, y, label, ha="center", va="center", fontsize=9, fontweight="bold")
    ax.add_patch(
        Rectangle((x0, y - h / 2), width, h, linewidth=1.2, edgecolor=ec, facecolor=fc)
    )


def _fields(ax, y, h, x0, fields, fc="#ffffff", ec="#444444", fs=7.5):
    """Draw subdivided fields inside a layer."""
    total = sum(w for _, w in fields)
    cx = x0
    for name, w in fields:
        fw = w / total * sum(w for _, w in fields)
        # normalize: w is relative weight
        pass
    total_w = sum(w for _, w in fields)
    cx = x0
    for i, (name, w) in enumerate(fields):
        fw = w / total_w * (x0 + sum(w for _, w in fields) - x0)
        # fix: band width passed separately
        break

    # simpler: pass band_width
    return


def _field_row(ax, y, h, x0, band_w, fields, fs=7.5, ec="#444444"):
    total = sum(w for _, w in fields)
    cx = x0
    for name, w in fields:
        fw = band_w * (w / total)
        ax.add_patch(Rectangle((cx, y - h / 2), fw, h, linewidth=0.8, edgecolor=ec, facecolor="white"))
        ax.text(cx + fw / 2, y, name, ha="center", va="center", fontsize=fs)
        cx += fw


def draw_packet_structure():
    fig, ax = plt.subplots(figsize=(14, 9))
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 10)
    ax.axis("off")

    ax.text(
        7,
        9.55,
        "過渡期 ICN パケット構成（Interest / Data 共通）",
        ha="center",
        va="center",
        fontsize=14,
        fontweight="bold",
    )
    ax.text(
        7,
        9.05,
        "L1 → L2 → IP → ICN → ペイロード   |   IP ルータは L3 まで処理 / IWP は ICN 層を解釈",
        ha="center",
        va="center",
        fontsize=9,
        color="#555555",
    )

    x0 = 1.6
    bw = 11.8
    lh = 0.95
    gap = 0.18

    layers = []

    # L1
    y = 7.8
    _layer_band(ax, y, lh * 0.75, x0, bw, "L1\n物理層", "#f5f5f5", "#999999")
    ax.text(x0 + bw / 2, y, "ケーブル / 光ファイバ（ビット伝送）", ha="center", va="center", fontsize=8, color="#666")

    # L2
    y -= lh + gap
    _layer_band(ax, y, lh, x0, bw, "L2\nデータ\nリンク層", "#fff3e0", "#e65100")
    _field_row(
        ax,
        y,
        lh * 0.82,
        x0 + 0.05,
        bw - 0.1,
        [
            ("dst MAC\n(6B)", 6),
            ("src MAC\n(6B)", 6),
            ("EtherType\n0x0800 (IPv4)", 4),
        ],
        fs=8,
        ec="#e65100",
    )
    ax.annotate(
        "",
        xy=(x0 + bw + 0.15, y),
        xytext=(x0 + bw + 0.15, y),
    )
    ax.text(
        x0 + bw + 0.25,
        y,
        "スイッチは\nMAC 転送",
        va="center",
        fontsize=7.5,
        color="#e65100",
    )

    # IP
    y -= lh + gap + 0.05
    _layer_band(ax, y, lh + 0.15, x0, bw, "L3\nIP層", "#e3f2fd", "#1565c0")
    _field_row(
        ax,
        y + 0.08,
        lh * 0.38,
        x0 + 0.05,
        bw - 0.1,
        [
            ("Ver/IHL", 2),
            ("TOS", 1),
            ("Total Len", 2),
            ("ID", 2),
            ("Flags/Frag", 2),
            ("TTL", 1),
            ("Proto\n(ICN)", 1),
            ("Checksum", 2),
        ],
        fs=6.5,
        ec="#1565c0",
    )
    _field_row(
        ax,
        y - 0.22,
        lh * 0.38,
        x0 + 0.05,
        bw - 0.1,
        [
            ("src IP\n(送信元)", 4),
            ("dst IP\n(次ホップ IWP / Consumer)", 4),
        ],
        fs=7.5,
        ec="#1565c0",
    )
    ax.text(
        x0 + bw + 0.25,
        y,
        "IP ルータは\nここまで処理\n(ICN は透過)",
        va="center",
        fontsize=7.5,
        color="#1565c0",
    )

    # ICN fixed header
    y -= lh + gap + 0.35
    _layer_band(ax, y, lh + 0.35, x0, bw, "ICN層\n(固定)", "#e8f5e9", "#2e7d32")
    _field_row(
        ax,
        y + 0.12,
        lh * 0.32,
        x0 + 0.05,
        bw - 0.1,
        [
            ("content_id\n(32b)", 4),
            ("type\n(16b)", 2),
            ("flags\n(8b)", 1),
            ("hop_limit\n(8b)", 1),
            ("consumer_ip\n(32b)", 4),
            ("chunk_id\n(16b)", 2),
            ("name_len\n(8b)", 1),
        ],
        fs=6.8,
        ec="#2e7d32",
    )
    ax.text(
        x0 + bw + 0.25,
        y,
        "IWP のみ\n解釈",
        va="center",
        fontsize=8,
        fontweight="bold",
        color="#2e7d32",
    )

    # ICN variable / payload
    y -= lh + gap + 0.2
    _layer_band(ax, y, lh, x0, bw, "ICN層\n(可変)", "#f3e5f5", "#6a1b9a")
    _field_row(
        ax,
        y,
        lh * 0.82,
        x0 + 0.05,
        bw - 0.1,
        [
            ("Interest: コンテンツ名 (可変長)\n例 /video/clips/001", 6),
            ("Data: チャンクデータ (最大 256B 等)", 6),
        ],
        fs=8,
        ec="#6a1b9a",
    )

    # Arrow showing parse direction
    ax.annotate(
        "",
        xy=(0.55, 2.8),
        xytext=(0.55, 8.5),
        arrowprops=dict(arrowstyle="-|>", color="#333333", lw=1.5),
    )
    ax.text(0.55, 5.6, "パケット\n先頭", ha="center", va="center", fontsize=8, rotation=90)

    # Legend: two packet types
    y -= lh + gap + 0.55
    ax.text(1.6, y, "パケット種別:", fontsize=9, fontweight="bold", ha="left")
    _field_row(
        ax,
        y - 0.55,
        0.7,
        3.2,
        4.5,
        [("Interest  type=0x0001", 1), ("Data  type=0x0010 / EtherType 0x88B6", 1)],
        fs=7.5,
        ec="#555555",
    )

    # Phase note
    ax.text(
        7,
        0.55,
        "Phase 1 (chunk_table): L2 カスタム EtherType 0x88B5 で ICN 層のみ  |  "
        "Phase 2 (本設計): IPv4 protocol フィールドで ICN を載せる",
        ha="center",
        fontsize=8,
        color="#777777",
        style="italic",
    )

    fig.savefig(OUT_PATH, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return OUT_PATH


def draw_side_by_side():
    """Compact side view: who reads which layer."""
    out = os.path.join(OUT_DIR, "architecture_packet_layers.png")
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 6)
    ax.axis("off")
    ax.set_title("各装置が参照するレイヤ", fontsize=13, fontweight="bold", pad=12)

    x0, bw, h = 2.0, 8.0, 0.55
    layers = [
        ("L1 物理層", "#f5f5f5", "#999"),
        ("L2 Ethernet", "#fff3e0", "#e65100"),
        ("L3 IPv4", "#e3f2fd", "#1565c0"),
        ("ICN 固定ヘッダ", "#e8f5e9", "#2e7d32"),
        ("ICN 可変部 / ペイロード", "#f3e5f5", "#6a1b9a"),
    ]
    y = 4.8
    for name, fc, ec in layers:
        ax.add_patch(Rectangle((x0, y - h / 2), bw, h, facecolor=fc, edgecolor=ec, lw=1.2))
        ax.text(x0 + bw / 2, y, name, ha="center", va="center", fontsize=9)
        y -= h + 0.12

    # Device columns
    devices = [
        (10.6, "IP ルータ", [0, 0, 1, 0, 0], "#fdebd0"),
        (10.6, "IWP", [0, 1, 1, 1, 1], "#d5f5e3"),
    ]
    # redraw with checkmarks per layer row
    y = 4.8
    checks_ip = [False, False, True, False, False]
    checks_iwp = [False, True, True, True, True]
    for i, (name, fc, ec) in enumerate(layers):
        yy = 4.8 - i * (h + 0.12)
        mark = "○" if checks_iwp[i] else "—"
        ax.text(10.15, yy, mark, ha="center", va="center", fontsize=11, color="#2e7d32")
        mark2 = "○" if checks_ip[i] else "—"
        ax.text(11.35, yy, mark2, ha="center", va="center", fontsize=11, color="#e67e22")

    ax.text(10.15, 5.45, "IWP", ha="center", fontsize=9, fontweight="bold", color="#2e7d32")
    ax.text(11.35, 5.45, "IPルータ", ha="center", fontsize=9, fontweight="bold", color="#e67e22")

    ax.text(
        6,
        1.2,
        "Interest / Data とも同じ積層構造  →  Data 返送時も IP ヘッダで consumer_ip へカプセル化",
        ha="center",
        fontsize=9,
        color="#444444",
    )

    fig.savefig(out, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out


if __name__ == "__main__":
    p1 = draw_packet_structure()
    p2 = draw_side_by_side()
    print(f"Wrote {p1}")
    print(f"Wrote {p2}")
