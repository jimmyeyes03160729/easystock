#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""EasyStock LINE compact card renderer (V6.0.0 - Crisp White Theme).

Modern Crisp White Redesign matching the reference layout:
- Pure white background (#FFFFFF) with delicate gray borders (#E5E7EB).
- Taiwan market color standard: UP is Red (#DC2626), DOWN is Green (#059669).
- Vertical compact card aspect ratio (~1:1.18), optimized for LINE and Telegram mobile chat previews.
- P-card: Left-column HUD metrics (開/高/低/參考/量), right-column intraday area chart with +/-% scales,
  time-volume bars, and bottom statistics (昨量/估量/漲跌家數/漲跌停).
- K-card: Period selector ribbon (1分 5分 15分 30分 60分 [日K] 週 月), MA indicator legend (5MA/20MA/60MA),
  Japanese candlesticks with floating OHLCV box, and volume histogram.
- T-card: Foreign, Investment Trust, and Dealer institutional panels with net buy/sell bars and holdings.
- Bottom visual action bar: [ 即時 ] [ K 線 ] [ 法人 ] with current mode yellow highlighted.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle, Circle
from matplotlib.ticker import FuncFormatter

# Register Noto Sans CJK on Linux / Ubuntu
for _font_path in (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
):
    try:
        if Path(_font_path).exists():
            fm.fontManager.addfont(_font_path)
    except Exception:
        pass


def _font_family() -> str:
    candidates = [
        "Noto Sans CJK TC",
        "Noto Sans CJK JP",
        "Noto Sans TC",
        "Microsoft JhengHei",
        "PingFang TC",
        "Arial Unicode MS",
        "DejaVu Sans",
    ]
    installed = {f.name for f in fm.fontManager.ttflist}
    for name in candidates:
        if name in installed:
            return name
    return "DejaVu Sans"


FONT = _font_family()
plt.rcParams["font.family"] = FONT
plt.rcParams["axes.unicode_minus"] = False

# ==========================================
# Crisp White Color Palette
# ==========================================
BRAND = "EasyStock · 智慧量化看板"
BG = "#FFFFFF"                  # Pure white canvas
CARD = "#FFFFFF"                # Card background
CARD_BORDER = "#E5E7EB"         # Gray-200 border
PANEL_BG = "#F9FAFB"            # Gray-50 soft panel
PANEL_BORDER = "#E5E7EB"        # Soft border
TEXT_MAIN = "#111827"           # Gray-900 primary text
TEXT_MUTED = "#6B7280"          # Gray-500 secondary text
TEXT_LIGHT = "#9CA3AF"          # Gray-400 subtle/meta text
GRID_COLOR = "#F3F4F6"          # Gray-100 chart grid
BORDER_LIGHT = "#E5E7EB"        # Dividing lines

# Taiwan conventions: 漲紅跌綠
RED = "#DC2626"                 # Taiwan Up (Red-600)
RED_BG = "#FEE2E2"              # Red-100 pill
RED_BORDER = "#FCA5A5"          # Red-300

GREEN = "#059669"               # Taiwan Down (Emerald-600)
GREEN_BG = "#D1FAE5"            # Emerald-100 pill
GREEN_BORDER = "#6EE7B7"        # Emerald-300

FLAT = "#6B7280"                # Flat / Neutral (Gray-500)
FLAT_BG = "#F3F4F6"             # Gray-100
FLAT_BORDER = "#E5E7EB"

# Accents & Indicators
AMBER = "#D97706"               # Amber-600 (Volume / Highlights)
AMBER_LIGHT = "#FEF3C7"         # Amber-100
BLUE = "#2563EB"                # Blue-600 (5MA)
MA20 = "#DC2626"                # Red-600 (20MA)
MA60 = "#D97706"                # Amber-600 (60MA)
BTN_YELLOW_BG = "#FEF9C3"       # Yellow-100 active tab
BTN_YELLOW_BORDER = "#F59E0B"   # Amber-500 active tab border


def _num(v: Any, default: float | None = None) -> float | None:
    try:
        if v is None:
            return default
        if isinstance(v, str):
            v = v.replace(",", "").replace("%", "").strip()
        return float(v)
    except Exception:
        return default


def _p(v: Any) -> str:
    x = _num(v)
    if x is None:
        return "--"
    if abs(x) >= 10000:
        return f"{x:,.1f}"
    if abs(x) >= 1000:
        return f"{x:,.2f}"
    return f"{x:.2f}"


def _compact(v: Any) -> str:
    x = _num(v)
    if x is None:
        return "--"
    if abs(x) >= 1000:
        return f"{x:,.0f}"
    if float(x).is_integer():
        return str(int(x))
    return f"{x:.2f}".rstrip("0").rstrip(".")


def _lots(v: Any) -> str:
    x = _num(v)
    if x is None:
        return "--"
    return f"{x:,.0f}"


def _money_100m(v: Any) -> str:
    x = _num(v)
    if x is None:
        return "--"
    return f"{x / 100_000_000:,.1f} 億"


def _signed(v: Any, decimals: int = 2, suffix: str = "") -> str:
    x = _num(v)
    if x is None:
        return "--"
    sign = "+" if x > 0 else ""
    return f"{sign}{x:,.{decimals}f}{suffix}"


def _direction(change: Any) -> tuple[str, str, str, str]:
    x = _num(change, 0.0) or 0.0
    if x > 0:
        return "▲", RED, RED_BG, RED_BORDER
    if x < 0:
        return "▼", GREEN, GREEN_BG, GREEN_BORDER
    return "－", FLAT, FLAT_BG, FLAT_BORDER


def _dt_text(snapshot: dict) -> str:
    text = str(snapshot.get("timestamp_text") or "").strip()
    if text:
        return text
    return datetime.now().strftime("%m/%d %H:%M:%S")


def _new_figure():
    # 6.4 x 6.4 inches @ 130 dpi = 832 x 832 px (1:1 aspect ratio)
    fig = plt.figure(figsize=(6.4, 6.4), dpi=130, facecolor=BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    return fig, ax


def _rounded(ax, xy, width, height, radius=0.015, face=CARD, edge=CARD_BORDER, lw=1.0, zorder=1):
    p = FancyBboxPatch(
        xy, width, height,
        boxstyle=f"round,pad=0.002,rounding_size={radius}",
        facecolor=face, edgecolor=edge, linewidth=lw,
        transform=ax.transAxes, zorder=zorder,
    )
    ax.add_patch(p)
    return p


def _draw_header(
    canvas,
    *,
    title: str,
    code: str,
    category: str,
    price: Any,
    change: Any,
    rate: Any,
    timestamp: str,
    is_market: bool = False,
) -> str:
    """Header in crisp white with clean stock info and zero decorative fluff."""
    arrow, color, _, _ = _direction(change)

    # 1. Main Title & Code
    canvas.text(0.045, 0.932, title, transform=canvas.transAxes,
                fontsize=21.0, fontweight="bold", color=TEXT_MAIN, va="center")
    if code:
        title_offset = 0.045 + (len(title) * 0.046)
        canvas.text(title_offset, 0.928, f"({code})",
                    transform=canvas.transAxes, fontsize=12.5, fontweight="bold",
                    color=TEXT_MUTED, va="center")

    # 2. Badges: [上市] [電子-半導體] / [上市] [指數]
    tags = ["上市", category or ("指數" if is_market else "個股")]
    badge_x = 0.045
    for tag in tags:
        tw = len(tag) * 0.026 + 0.042
        _rounded(canvas, (badge_x, 0.865), tw, 0.030, radius=0.007,
                 face="#F3F4F6", edge="#E5E7EB", lw=0.8, zorder=2)
        canvas.text(badge_x + tw / 2, 0.880, tag, transform=canvas.transAxes,
                    fontsize=8.5, color=TEXT_MUTED, ha="center", va="center", zorder=3)
        badge_x += tw + 0.015

    # 3. Right side Price & Change
    p_num = _num(price)
    if is_market and p_num is not None:
        p_str = f"{p_num:,.1f}"
    else:
        p_str = _p(price)

    canvas.text(0.480, 0.924, p_str, transform=canvas.transAxes,
                fontsize=26.0, fontweight="bold", color=color, va="center")

    ch = abs(_num(change, 0.0) or 0.0)
    rt = abs(_num(rate, 0.0) or 0.0)
    sign = "-" if (_num(change, 0.0) or 0.0) < 0 else ("+" if (_num(change, 0.0) or 0.0) > 0 else "")
    ch_text = f"{arrow} {sign}{ch:,.2f}"
    rt_text = f"({sign}{rt:.2f}%)"

    canvas.text(0.795, 0.938, ch_text, transform=canvas.transAxes,
                fontsize=11.5, fontweight="bold", color=color, va="center")
    canvas.text(0.795, 0.908, rt_text, transform=canvas.transAxes,
                fontsize=11.0, fontweight="bold", color=color, va="center")

    # 4. Update timestamp
    lbl = "指數更新時間" if is_market else "股價更新時間"
    canvas.text(0.955, 0.870, f"{lbl}: {timestamp}", transform=canvas.transAxes,
                fontsize=8.0, color=TEXT_LIGHT, ha="right", va="center")

    return color


def _style_chart_white(ax):
    ax.set_facecolor(BG)
    ax.grid(True, color=GRID_COLOR, linestyle="-", linewidth=0.6, alpha=0.9)
    ax.tick_params(colors=TEXT_MUTED, labelsize=7.5, length=2, width=0.6)
    for s in ax.spines.values():
        s.set_color(BORDER_LIGHT)
        s.set_linewidth(0.7)


def _save(fig, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=BG, bbox_inches=None, pad_inches=0)
    plt.close(fig)
    return path


# ==========================================
# 1. Stock Intraday Card (P2330)
# ==========================================
def render_stock_intraday_card(snapshot: dict, rows: list[dict], path: Path) -> Path:
    fig, canvas = _new_figure()

    name = snapshot.get("name", "股票")
    code = snapshot.get("code", "")
    category = snapshot.get("category", "半導體")
    ref = _num(snapshot.get("reference"))
    avg = _num(snapshot.get("average_price"))

    color = _draw_header(
        canvas,
        title=str(name),
        code=str(code),
        category=str(category),
        price=snapshot.get("close"),
        change=snapshot.get("change_price"),
        rate=snapshot.get("change_rate"),
        timestamp=_dt_text(snapshot),
        is_market=False,
    )

    # ---------------------------------------------
    # Left HUD Column (x: 0.045 to 0.220)
    # ---------------------------------------------
    hud_items = [
        ("開盤", snapshot.get("open"), None),
        ("最高", snapshot.get("high"), RED),
        ("最低", snapshot.get("low"), GREEN),
        ("參考", ref, TEXT_MAIN),
        ("成交量", snapshot.get("total_volume"), AMBER),
    ]

    hud_y = 0.790
    for label, val, c_override in hud_items:
        canvas.text(0.120, hud_y, label, transform=canvas.transAxes,
                    fontsize=8.5, color=TEXT_MUTED, ha="center", va="center")
        val_str = _lots(val) if label == "成交量" else _p(val)
        if c_override:
            c = c_override
        else:
            c = RED if (_num(val) or 0) > (ref or 0) else (GREEN if (_num(val) or 0) < (ref or 0) else TEXT_MAIN)
        canvas.text(0.120, hud_y - 0.030, val_str, transform=canvas.transAxes,
                    fontsize=10.5, fontweight="bold", color=c, ha="center", va="center")
        hud_y -= 0.082

    # Left Bottom Tag: [ 盤中即時 ]
    _rounded(canvas, (0.055, hud_y + 0.010), 0.130, 0.028, radius=0.007,
             face="#FEF9C3", edge=BTN_YELLOW_BORDER, lw=0.8, zorder=2)
    canvas.text(0.120, hud_y + 0.024, "盤中即時", transform=canvas.transAxes,
                fontsize=7.8, fontweight="bold", color="#B45309",
                ha="center", va="center", zorder=3)

    # ---------------------------------------------
    # Right Chart Area (x: 0.260 to 0.955)
    # ---------------------------------------------
    ax = fig.add_axes([0.260, 0.335, 0.695, 0.485])
    axv = fig.add_axes([0.260, 0.225, 0.695, 0.110], sharex=ax)

    valid = [r for r in rows if r.get("close") is not None]
    if valid:
        times = [r["time"] for r in valid]
        closes = [float(r["close"]) for r in valid]
        vols = [float(r.get("volume") or 0) for r in valid]

        xvals = [(t.hour * 60 + t.minute) - 540 for t in times]
        base = ref if ref is not None else closes[0]

        all_pts = closes + ([base] if base else []) + ([avg] if avg else [])
        min_p, max_p = min(all_pts), max(all_pts)
        max_diff = max(abs(max_p - base), abs(base - min_p), 1.0)
        ax.set_ylim(base - max_diff * 1.15, base + max_diff * 1.15)

        # Baseline
        ax.axhline(base, color="#9CA3AF", lw=0.8, ls="--", alpha=0.9, zorder=2)

        # Filled area
        ax.fill_between(xvals, closes, base, where=[c >= base for c in closes],
                        color=RED, alpha=0.14, interpolate=True, zorder=2)
        ax.fill_between(xvals, closes, base, where=[c < base for c in closes],
                        color=GREEN, alpha=0.14, interpolate=True, zorder=2)

        curve_color = GREEN if closes[-1] < base else RED
        ax.plot(xvals, closes, color=curve_color, lw=1.4, zorder=4)

        if avg:
            ax.axhline(avg, color=AMBER, lw=0.8, ls=":", alpha=0.85, zorder=3)

        hi_idx = max(range(len(closes)), key=lambda i: closes[i])
        lo_idx = min(range(len(closes)), key=lambda i: closes[i])
        hx, hy = xvals[hi_idx], closes[hi_idx]
        lx, ly = xvals[lo_idx], closes[lo_idx]

        ax.scatter([hx], [hy], s=16, color=RED, zorder=5)
        ax.text(hx, hy + (max_diff * 0.05), f"{hy:.2f}", color=RED,
                fontsize=7.5, fontweight="bold", ha="center", va="bottom", zorder=6)

        ax.scatter([lx], [ly], s=16, color=GREEN, zorder=5)
        ax.text(lx, ly - (max_diff * 0.05), f"{ly:.2f}", color=GREEN,
                fontsize=7.5, fontweight="bold", ha="center", va="top", zorder=6)

        ax.scatter([xvals[-1]], [closes[-1]], s=24, color=curve_color,
                   edgecolors="#FFFFFF", linewidths=1.2, zorder=7)

        ticks = [0, 60, 120, 180, 240, 270]
        labels = ["09:00", "10:00", "11:00", "12:00", "13:00", ""]
        ax.set_xlim(0, 270)
        ax.set_xticks(ticks)
        ax.tick_params(axis="x", labelbottom=False)

        # Right Y-axis
        y_ticks = ax.get_yticks()
        ax_r = ax.twinx()
        ax_r.set_ylim(ax.get_ylim())
        r_labels = [f"{(y - base) / base * 100:+.1f}%" if base else "" for y in y_ticks]
        ax_r.set_yticks(y_ticks)
        ax_r.set_yticklabels(r_labels, fontsize=7.2)
        ax_r.tick_params(colors=TEXT_MUTED, length=2, width=0.6)
        for s in ax_r.spines.values():
            s.set_visible(False)

        # Volume bars in warm amber
        axv.bar(xvals, vols, width=0.9, color="#F59E0B", alpha=0.85)
        axv.set_xlim(0, 270)
        axv.set_xticks(ticks)
        axv.set_xticklabels(labels, fontsize=7.5)
        axv.tick_params(axis="y", labelleft=False)
    else:
        ax.text(0.5, 0.5, "盤中暫無即時走勢資料", transform=ax.transAxes,
                ha="center", va="center", color=TEXT_MUTED, fontsize=10)

    _style_chart_white(ax)
    _style_chart_white(axv)

    # ---------------------------------------------
    # Bottom Stats (昨量 / 估量 / 均價 / 振幅)
    # ---------------------------------------------
    stats_y = 0.140
    canvas.text(0.260, stats_y, "昨量", transform=canvas.transAxes,
                fontsize=9.0, color=TEXT_MUTED, va="center")
    canvas.text(0.480, stats_y, _lots(snapshot.get("yesterday_volume")), transform=canvas.transAxes,
                fontsize=11.5, fontweight="bold", color=TEXT_MAIN, ha="right", va="center")

    canvas.text(0.600, stats_y, "估量", transform=canvas.transAxes,
                fontsize=9.0, color=TEXT_MUTED, va="center")
    canvas.text(0.850, stats_y, _lots(snapshot.get("estimated_volume")), transform=canvas.transAxes,
                fontsize=11.5, fontweight="bold", color=TEXT_MAIN, ha="right", va="center")

    stats_y2 = 0.075
    canvas.text(0.260, stats_y2, "均價", transform=canvas.transAxes,
                fontsize=9.0, color=TEXT_MUTED, va="center")
    canvas.text(0.480, stats_y2, _p(avg), transform=canvas.transAxes,
                fontsize=11.0, fontweight="bold", color=AMBER, ha="right", va="center")

    amplitude = None
    if snapshot.get("high") and snapshot.get("low") and ref:
        amplitude = (float(snapshot["high"]) - float(snapshot["low"])) / float(ref) * 100
    canvas.text(0.600, stats_y2, "振幅", transform=canvas.transAxes,
                fontsize=9.0, color=TEXT_MUTED, va="center")
    canvas.text(0.850, stats_y2, f"{amplitude:.2f}%" if amplitude else "--", transform=canvas.transAxes,
                fontsize=11.0, fontweight="bold", color=TEXT_MAIN, ha="right", va="center")

    return _save(fig, path)


def render_stock_sparkline(snapshot: dict, rows: list[dict], path: Path) -> Path:
    """Pure sparkline intraday chart (no duplicate header/text) for the Stitch hybrid Flex layout."""
    fig = plt.figure(figsize=(5.4, 3.0), dpi=140, facecolor=BG)
    ax = fig.add_axes([0.085, 0.26, 0.805, 0.65])
    axv = fig.add_axes([0.085, 0.08, 0.805, 0.17], sharex=ax)

    ref = _num(snapshot.get("reference"))
    avg = _num(snapshot.get("average_price"))
    valid = [r for r in rows if r.get("close") is not None]
    if valid:
        times = [r["time"] for r in valid]
        closes = [float(r["close"]) for r in valid]
        vols = [float(r.get("volume") or 0) for r in valid]

        xvals = [(t.hour * 60 + t.minute) - 540 for t in times]
        base = ref if ref is not None else closes[0]

        all_pts = closes + ([base] if base else []) + ([avg] if avg else [])
        min_p, max_p = min(all_pts), max(all_pts)
        max_diff = max(abs(max_p - base), abs(base - min_p), 1.0)
        ax.set_ylim(base - max_diff * 1.25, base + max_diff * 1.25)

        # Baseline
        ax.axhline(base, color="#9CA3AF", lw=0.8, ls="--", alpha=0.9, zorder=2)

        # Filled area
        ax.fill_between(xvals, closes, base, where=[c >= base for c in closes],
                        color=RED, alpha=0.14, interpolate=True, zorder=2)
        ax.fill_between(xvals, closes, base, where=[c < base for c in closes],
                        color=GREEN, alpha=0.14, interpolate=True, zorder=2)

        curve_color = GREEN if closes[-1] < base else RED
        ax.plot(xvals, closes, color=curve_color, lw=1.8, zorder=4)

        if avg:
            ax.axhline(avg, color=AMBER, lw=0.8, ls=":", alpha=0.85, zorder=3)

        hi_idx = max(range(len(closes)), key=lambda i: closes[i])
        lo_idx = min(range(len(closes)), key=lambda i: closes[i])
        hx, hy = xvals[hi_idx], closes[hi_idx]
        lx, ly = xvals[lo_idx], closes[lo_idx]

        ax.scatter([hx], [hy], s=20, color=RED, zorder=5)
        ax.text(hx, hy + (max_diff * 0.05), f"{hy:.2f}", color=RED,
                fontsize=8.0, fontweight="bold", ha="center", va="bottom", zorder=6)

        ax.scatter([lx], [ly], s=20, color=GREEN, zorder=5)
        ax.text(lx, ly - (max_diff * 0.05), f"{ly:.2f}", color=GREEN,
                fontsize=8.0, fontweight="bold", ha="center", va="top", zorder=6)

        ax.scatter([xvals[-1]], [closes[-1]], s=28, color=curve_color,
                   edgecolors="#FFFFFF", linewidths=1.3, zorder=7)

        ticks = [0, 60, 120, 180, 240, 270]
        labels = ["09:00", "10:00", "11:00", "12:00", "13:00", ""]
        ax.set_xlim(0, 270)
        ax.set_xticks(ticks)
        ax.tick_params(axis="x", labelbottom=False)

        # Right Y-axis
        y_ticks = ax.get_yticks()
        ax_r = ax.twinx()
        ax_r.set_ylim(ax.get_ylim())
        r_labels = [f"{(y - base) / base * 100:+.1f}%" if base else "" for y in y_ticks]
        ax_r.set_yticks(y_ticks)
        ax_r.set_yticklabels(r_labels, fontsize=7.2)
        ax_r.tick_params(colors=TEXT_MUTED, length=2, width=0.6)
        for s in ax_r.spines.values():
            s.set_visible(False)

        # Volume bars in warm amber
        axv.bar(xvals, vols, width=0.9, color="#F59E0B", alpha=0.85)
        axv.set_xlim(0, 270)
        axv.set_xticks(ticks)
        axv.set_xticklabels(labels, fontsize=7.5)
        axv.tick_params(axis="y", labelleft=False)
    else:
        ax.text(0.5, 0.5, "暫無分時走勢", transform=ax.transAxes,
                ha="center", va="center", color=TEXT_MUTED, fontsize=10)

    _style_chart_white(ax)
    _style_chart_white(axv)
    return _save(fig, path)


def render_market_sparkline(snapshot: dict, rows: list[dict], path: Path) -> Path:
    """Pure sparkline intraday chart for market index."""
    fig = plt.figure(figsize=(5.4, 3.0), dpi=140, facecolor=BG)
    ax = fig.add_axes([0.085, 0.26, 0.805, 0.65])
    axv = fig.add_axes([0.085, 0.08, 0.805, 0.17], sharex=ax)

    ref = _num(snapshot.get("reference"))
    valid = [r for r in rows if r.get("close") is not None]
    if valid:
        times = [r["time"] for r in valid]
        closes = [float(r["close"]) for r in valid]
        vols = [float(r.get("volume") or 0) for r in valid]

        xvals = [(t.hour * 60 + t.minute) - 540 for t in times]
        base = ref if ref is not None else closes[0]

        all_pts = closes + ([base] if base else [])
        min_p, max_p = min(all_pts), max(all_pts)
        max_diff = max(abs(max_p - base), abs(base - min_p), 10.0)
        ax.set_ylim(base - max_diff * 1.25, base + max_diff * 1.25)

        ax.axhline(base, color="#9CA3AF", lw=0.8, ls="--", alpha=0.9, zorder=2)

        ax.fill_between(xvals, closes, base, where=[c >= base for c in closes],
                        color=RED, alpha=0.14, interpolate=True, zorder=2)
        ax.fill_between(xvals, closes, base, where=[c < base for c in closes],
                        color=GREEN, alpha=0.14, interpolate=True, zorder=2)

        curve_color = GREEN if closes[-1] < base else RED
        ax.plot(xvals, closes, color=curve_color, lw=1.8, zorder=4)

        hi_idx = max(range(len(closes)), key=lambda i: closes[i])
        lo_idx = min(range(len(closes)), key=lambda i: closes[i])
        hx, hy = xvals[hi_idx], closes[hi_idx]
        lx, ly = xvals[lo_idx], closes[lo_idx]

        ax.scatter([hx], [hy], s=20, color=RED, zorder=5)
        ax.text(hx, hy + (max_diff * 0.05), f"{hy:,.1f}", color=RED,
                fontsize=8.0, fontweight="bold", ha="center", va="bottom", zorder=6)

        ax.scatter([lx], [ly], s=20, color=GREEN, zorder=5)
        ax.text(lx, ly - (max_diff * 0.05), f"{ly:,.1f}", color=GREEN,
                fontsize=8.0, fontweight="bold", ha="center", va="top", zorder=6)

        ax.scatter([xvals[-1]], [closes[-1]], s=28, color=curve_color,
                   edgecolors="#FFFFFF", linewidths=1.3, zorder=7)

        ticks = [0, 60, 120, 180, 240, 270]
        labels = ["09:00", "10:00", "11:00", "12:00", "13:00", ""]
        ax.set_xlim(0, 270)
        ax.set_xticks(ticks)
        ax.tick_params(axis="x", labelbottom=False)

        y_ticks = ax.get_yticks()
        ax_r = ax.twinx()
        ax_r.set_ylim(ax.get_ylim())
        r_labels = [f"{(y - base) / base * 100:+.1f}%" if base else "" for y in y_ticks]
        ax_r.set_yticks(y_ticks)
        ax_r.set_yticklabels(r_labels, fontsize=7.2)
        ax_r.tick_params(colors=TEXT_MUTED, length=2, width=0.6)
        for s in ax_r.spines.values():
            s.set_visible(False)

        axv.bar(xvals, vols, width=0.9, color="#F59E0B", alpha=0.85)
        axv.set_xlim(0, 270)
        axv.set_xticks(ticks)
        axv.set_xticklabels(labels, fontsize=7.5)
        axv.tick_params(axis="y", labelleft=False)
    else:
        ax.text(0.5, 0.5, "暫無大盤走勢", transform=ax.transAxes,
                ha="center", va="center", color=TEXT_MUTED, fontsize=10)

    _style_chart_white(ax)
    _style_chart_white(axv)
    return _save(fig, path)


def render_eps_sparkline(name: str, code: str, quarterly: list[dict], path: Path) -> Path:
    """Quarterly EPS bar chart + TTM trend line for Stitch hybrid Flex layout."""
    fig = plt.figure(figsize=(5.4, 3.0), dpi=140, facecolor=BG)
    ax = fig.add_axes([0.085, 0.22, 0.805, 0.65])

    n = len(quarterly)
    xvals = list(range(n))
    labels = [q["quarter"] for q in quarterly]
    eps_vals = [q["eps"] for q in quarterly]
    ttm_vals = [q.get("ttm_eps") for q in quarterly]

    max_eps = max(eps_vals) if eps_vals else 10.0
    min_eps = min(eps_vals) if eps_vals else 0.0
    y_floor = min(0.0, min_eps * 1.1)
    y_ceiling = max_eps * 1.35
    ax.set_ylim(y_floor, y_ceiling)

    # 0 baseline
    ax.axhline(0, color="#9CA3AF", lw=0.8, ls="--", alpha=0.8, zorder=2)

    bar_width = 0.52
    for i, q in enumerate(quarterly):
        val = q["eps"]
        is_latest = (i == n - 1)
        is_max = (val == max_eps)

        if val >= 0:
            if is_latest and is_max:
                color = RED
            elif is_latest:
                color = "#2563EB"
            else:
                color = "#93C5FD"
        else:
            color = GREEN

        ax.bar(i, val, width=bar_width, color=color, alpha=0.92, zorder=3)

        if val >= 0:
            va = "bottom"
            y_pos = val + (max_eps * 0.03)
        else:
            va = "top"
            y_pos = val - (max_eps * 0.03)

        font_weight = "bold" if is_latest else "normal"
        text_color = RED if (is_latest and is_max) else (TEXT_MAIN if is_latest else TEXT_MUTED)
        ax.text(i, y_pos, f"{val:.1f}" if abs(val) >= 10 else f"{val:.2f}",
                ha="center", va=va, fontsize=7.8, fontweight=font_weight, color=text_color, zorder=6)

        if is_latest and is_max and n >= 4:
            ax.text(i, y_pos + (max_eps * 0.12), "新高", ha="center", va="bottom",
                    fontsize=6.8, fontweight="bold", color="#DC2626",
                    bbox=dict(boxstyle="round,pad=0.20", facecolor="#FEE2E2", edgecolor="#FCA5A5", lw=0.6),
                    zorder=7)

    # Secondary Y-axis for TTM line
    valid_ttm = [(i, v) for i, v in enumerate(ttm_vals) if v is not None]
    last_ttm_str = ""
    if valid_ttm:
        ax_ttm = ax.twinx()
        tx = [p[0] for p in valid_ttm]
        ty = [p[1] for p in valid_ttm]
        max_ttm = max(ty)
        min_ttm = min(ty)
        ax_ttm.set_ylim(min(0.0, min_ttm * 0.9), max_ttm * 1.25)
        ax_ttm.plot(tx, ty, color=AMBER, lw=1.6, ls="-", marker="o", markersize=3.2, zorder=5)
        ax_ttm.tick_params(colors=AMBER, labelsize=7.0, length=2, width=0.6)
        for s in ax_ttm.spines.values():
            s.set_visible(False)
        last_ttm_str = f" (最新 {ty[-1]:.1f}元)"

    ax.set_xlim(-0.6, n - 0.4)
    ax.set_xticks(xvals)
    ax.set_xticklabels(labels, fontsize=7.8, fontweight="medium")

    # Legend at top left
    fig.text(0.085, 0.92, "■ 單季EPS (元)", fontsize=7.5, color="#2563EB", va="center")
    if valid_ttm:
        fig.text(0.32, 0.92, f"―●― 近四季TTM{last_ttm_str} (右軸)", fontsize=7.5, color=AMBER, va="center")

    _style_chart_white(ax)
    return _save(fig, path)


# ==========================================
# 2. Market Intraday Card (P大盤)
# ==========================================
def render_market_intraday_card(snapshot: dict, rows: list[dict], path: Path) -> Path:
    fig, canvas = _new_figure()

    ref = _num(snapshot.get("reference"))
    color = _draw_header(
        canvas,
        title="加權指數",
        code="",
        category="指數",
        price=snapshot.get("close"),
        change=snapshot.get("change_price"),
        rate=snapshot.get("change_rate"),
        timestamp=_dt_text(snapshot),
        is_market=True,
    )

    # Left Column HUD
    hud_items = [
        ("開盤", snapshot.get("open"), None),
        ("最高", snapshot.get("high"), RED),
        ("最低", snapshot.get("low"), GREEN),
        ("參考", ref, TEXT_MAIN),
        ("成交量", snapshot.get("total_amount"), AMBER),
    ]

    hud_y = 0.790
    for label, val, c_override in hud_items:
        canvas.text(0.120, hud_y, label, transform=canvas.transAxes,
                    fontsize=8.5, color=TEXT_MUTED, ha="center", va="center")
        val_str = _money_100m(val) if label == "成交量" else _p(val)
        if c_override:
            c = c_override
        else:
            c = RED if (_num(val) or 0) > (ref or 0) else (GREEN if (_num(val) or 0) < (ref or 0) else TEXT_MAIN)
        canvas.text(0.120, hud_y - 0.030, val_str, transform=canvas.transAxes,
                    fontsize=10.5, fontweight="bold", color=c, ha="center", va="center")
        hud_y -= 0.082

    # Left Bottom Tag: [ 查指期 ]
    _rounded(canvas, (0.055, hud_y + 0.010), 0.130, 0.028, radius=0.007,
             face="#FEF9C3", edge=BTN_YELLOW_BORDER, lw=0.8, zorder=2)
    canvas.text(0.120, hud_y + 0.024, "查指期", transform=canvas.transAxes,
                fontsize=7.8, fontweight="bold", color="#B45309",
                ha="center", va="center", zorder=3)

    # Right Chart Area
    ax = fig.add_axes([0.260, 0.380, 0.695, 0.445])
    axv = fig.add_axes([0.260, 0.265, 0.695, 0.105], sharex=ax)

    valid = [r for r in rows if r.get("close") is not None]
    if valid:
        times = [r["time"] for r in valid]
        closes = [float(r["close"]) for r in valid]
        vols = [float(r.get("volume") or 0) for r in valid]

        xvals = [(t.hour * 60 + t.minute) - 540 for t in times]
        base = ref if ref is not None else closes[0]

        all_pts = closes + ([base] if base else [])
        min_p, max_p = min(all_pts), max(all_pts)
        max_diff = max(abs(max_p - base), abs(base - min_p), 10.0)
        ax.set_ylim(base - max_diff * 1.15, base + max_diff * 1.15)

        ax.axhline(base, color="#9CA3AF", lw=0.8, ls="--", alpha=0.9, zorder=2)

        ax.fill_between(xvals, closes, base, where=[c >= base for c in closes],
                        color=RED, alpha=0.14, interpolate=True, zorder=2)
        ax.fill_between(xvals, closes, base, where=[c < base for c in closes],
                        color=GREEN, alpha=0.14, interpolate=True, zorder=2)

        curve_color = GREEN if closes[-1] < base else RED
        ax.plot(xvals, closes, color=curve_color, lw=1.4, zorder=4)

        hi_idx = max(range(len(closes)), key=lambda i: closes[i])
        lo_idx = min(range(len(closes)), key=lambda i: closes[i])
        hx, hy = xvals[hi_idx], closes[hi_idx]
        lx, ly = xvals[lo_idx], closes[lo_idx]

        ax.scatter([hx], [hy], s=16, color=RED, zorder=5)
        ax.text(hx, hy + (max_diff * 0.05), f"{hy:,.1f}", color=RED,
                fontsize=7.5, fontweight="bold", ha="center", va="bottom", zorder=6)

        ax.scatter([lx], [ly], s=16, color=GREEN, zorder=5)
        ax.text(lx, ly - (max_diff * 0.05), f"{ly:,.1f}", color=GREEN,
                fontsize=7.5, fontweight="bold", ha="center", va="top", zorder=6)

        ax.scatter([xvals[-1]], [closes[-1]], s=24, color=curve_color,
                   edgecolors="#FFFFFF", linewidths=1.2, zorder=7)

        ticks = [0, 60, 120, 180, 240, 270]
        labels = ["09:00", "10:00", "11:00", "12:00", "13:00", ""]
        ax.set_xlim(0, 270)
        ax.set_xticks(ticks)
        ax.tick_params(axis="x", labelbottom=False)

        y_ticks = ax.get_yticks()
        ax_r = ax.twinx()
        ax_r.set_ylim(ax.get_ylim())
        r_labels = [f"{(y - base) / base * 100:+.1f}%" if base else "" for y in y_ticks]
        ax_r.set_yticks(y_ticks)
        ax_r.set_yticklabels(r_labels, fontsize=7.2)
        ax_r.tick_params(colors=TEXT_MUTED, length=2, width=0.6)
        for s in ax_r.spines.values():
            s.set_visible(False)

        # Volume bars in warm amber
        axv.bar(xvals, vols, width=0.9, color="#F59E0B", alpha=0.85)
        axv.set_xlim(0, 270)
        axv.set_xticks(ticks)
        axv.set_xticklabels(labels, fontsize=7.5)
        axv.tick_params(axis="y", labelleft=False)
    else:
        ax.text(0.5, 0.5, "盤中暫無大盤走勢資料", transform=ax.transAxes,
                ha="center", va="center", color=TEXT_MUTED, fontsize=10)

    _style_chart_white(ax)
    _style_chart_white(axv)

    # Bottom Breadth Statistics
    stats_y1 = 0.185
    canvas.text(0.260, stats_y1, "昨量", transform=canvas.transAxes,
                fontsize=8.5, color=TEXT_MUTED, va="center")
    canvas.text(0.500, stats_y1, _money_100m(snapshot.get("total_amount")), transform=canvas.transAxes,
                fontsize=11.0, fontweight="bold", color=TEXT_MAIN, ha="right", va="center")

    canvas.text(0.600, stats_y1, "估量", transform=canvas.transAxes,
                fontsize=8.5, color=TEXT_MUTED, va="center")
    canvas.text(0.850, stats_y1, _money_100m(snapshot.get("total_amount")), transform=canvas.transAxes,
                fontsize=11.0, fontweight="bold", color=TEXT_MAIN, ha="right", va="center")

    stats_y2 = 0.120
    canvas.text(0.260, stats_y2, "上漲家數", transform=canvas.transAxes,
                fontsize=8.5, color=TEXT_MUTED, va="center")
    canvas.text(0.500, stats_y2, _compact(snapshot.get("up_count", 0)), transform=canvas.transAxes,
                fontsize=11.5, fontweight="bold", color=RED, ha="right", va="center")

    canvas.text(0.600, stats_y2, "下跌家數", transform=canvas.transAxes,
                fontsize=8.5, color=TEXT_MUTED, va="center")
    canvas.text(0.850, stats_y2, _compact(snapshot.get("down_count", 0)), transform=canvas.transAxes,
                fontsize=11.5, fontweight="bold", color=GREEN, ha="right", va="center")

    stats_y3 = 0.055
    canvas.text(0.260, stats_y3, "漲停家數", transform=canvas.transAxes,
                fontsize=8.5, color=TEXT_MUTED, va="center")
    canvas.text(0.500, stats_y3, _compact(snapshot.get("limit_up_count", 0)), transform=canvas.transAxes,
                fontsize=11.5, fontweight="bold", color=RED, ha="right", va="center")

    canvas.text(0.600, stats_y3, "跌停家數", transform=canvas.transAxes,
                fontsize=8.5, color=TEXT_MUTED, va="center")
    canvas.text(0.850, stats_y3, _compact(snapshot.get("limit_down_count", 0)), transform=canvas.transAxes,
                fontsize=11.5, fontweight="bold", color=GREEN, ha="right", va="center")

    return _save(fig, path)


# ==========================================
# 3. K-Line Candlestick Card (K2330 / K大盤)
# ==========================================
def render_k_card(title: str, code: str, rows: list[dict], path: Path, is_market=False) -> Path:
    fig, canvas = _new_figure()

    rows = sorted(rows, key=lambda x: str(x.get("date") or ""))[-60:]
    if not rows:
        raise RuntimeError("K 線資料不足")

    last = rows[-1]
    prev = rows[-2].get("close") if len(rows) > 1 else last.get("open")
    close = _num(last.get("close"))
    prevf = _num(prev)
    change = (close - prevf) if close is not None and prevf is not None else 0
    rate = (change / prevf * 100) if prevf else 0

    category = "指數" if is_market else "個股"
    color = _draw_header(
        canvas,
        title=title,
        code=code if not is_market else "",
        category=category,
        price=close,
        change=change,
        rate=rate,
        timestamp=str(last.get("date") or ""),
        is_market=is_market,
    )

    # 1. Period Selector Ribbon (1分 5分 15分 30分 60分 [日K] 週 月)
    periods = ["1分", "5分", "15分", "30分", "60分", "日K", "週", "月"]
    px = 0.045
    pw = 0.100
    for p in periods:
        is_active = (p == "日K")
        if is_active:
            _rounded(canvas, (px, 0.795), pw, 0.038, radius=0.007,
                     face=BTN_YELLOW_BG, edge=BTN_YELLOW_BORDER, lw=1.2, zorder=2)
            canvas.text(px + pw / 2, 0.814, p, transform=canvas.transAxes,
                        fontsize=9.2, fontweight="bold", color=TEXT_MAIN,
                        ha="center", va="center", zorder=3)
        else:
            _rounded(canvas, (px, 0.795), pw, 0.038, radius=0.007,
                     face="#FFFFFF", edge="#D1D5DB", lw=0.7, zorder=2)
            canvas.text(px + pw / 2, 0.814, p, transform=canvas.transAxes,
                        fontsize=8.5, color=TEXT_MUTED, ha="center", va="center", zorder=3)
        px += pw + 0.016

    # 2. Moving Averages Calculation
    opens = [_num(r.get("open")) for r in rows]
    highs = [_num(r.get("max") if r.get("max") is not None else r.get("high")) for r in rows]
    lows = [_num(r.get("min") if r.get("min") is not None else r.get("low")) for r in rows]
    closes = [_num(r.get("close")) for r in rows]
    vols = [_num(r.get("Trading_Volume") if r.get("Trading_Volume") is not None else r.get("volume"), 0) or 0 for r in rows]

    def moving_average(values: list[float | None], window: int):
        out = []
        for i in range(len(values)):
            if i + 1 < window:
                out.append(None)
            else:
                sub = [v for v in values[i - window + 1: i + 1] if v is not None]
                out.append(sum(sub) / len(sub) if len(sub) == window else None)
        return out

    ma5 = moving_average(closes, 5)
    ma20 = moving_average(closes, 20)
    ma60 = moving_average(closes, 60)

    # 3. MA Indicator Legend Line
    canvas.text(0.045, 0.755, "日K", transform=canvas.transAxes,
                fontsize=9.0, color=TEXT_MUTED, va="center")
    canvas.text(0.180, 0.755, f"5MA {_p(ma5[-1]) if ma5 else '--'}", transform=canvas.transAxes,
                fontsize=9.5, fontweight="bold", color=BLUE, va="center")
    canvas.text(0.480, 0.755, f"20MA {_p(ma20[-1]) if ma20 else '--'}", transform=canvas.transAxes,
                fontsize=9.5, fontweight="bold", color=RED, va="center")
    canvas.text(0.760, 0.755, f"60MA {_p(ma60[-1]) if ma60 else '--'}", transform=canvas.transAxes,
                fontsize=9.5, fontweight="bold", color=AMBER, va="center")

    # 4. Charts: ax (Candlestick, y: 0.220 to 0.720), axv (Volume, y: 0.065 to 0.210)
    ax = fig.add_axes([0.050, 0.220, 0.880, 0.500])
    axv = fig.add_axes([0.050, 0.065, 0.880, 0.145], sharex=ax)

    all_k_pts = [v for v in highs + lows if v is not None]
    if all_k_pts:
        min_k, max_k = min(all_k_pts), max(all_k_pts)
        span_k = max(max_k - min_k, 1.0)
        ax.set_ylim(min_k - span_k * 0.08, max_k + span_k * 0.08)

    n_bars = len(rows)
    for i in range(n_bars):
        o, h, l, c = opens[i], highs[i], lows[i], closes[i]
        if None in (o, h, l, c):
            continue
        v = vols[i]
        bar_col = RED if c >= o else GREEN

        # Wicks
        ax.vlines(i, l, h, color=bar_col, linewidth=1.1, zorder=3)
        # Candlestick body
        body_bottom = min(o, c)
        body_height = max(abs(c - o), 0.001)
        ax.add_patch(Rectangle(
            (i - 0.28, body_bottom), 0.56, body_height,
            facecolor=bar_col, edgecolor=bar_col, linewidth=0.5, zorder=4,
        ))
        axv.bar(i, v, width=0.62, color=bar_col, alpha=0.85)

    valid_ma5 = [(i, v) for i, v in enumerate(ma5) if v is not None]
    valid_ma20 = [(i, v) for i, v in enumerate(ma20) if v is not None]
    valid_ma60 = [(i, v) for i, v in enumerate(ma60) if v is not None]

    if valid_ma5:
        ax.plot([x[0] for x in valid_ma5], [x[1] for x in valid_ma5],
                color=BLUE, lw=1.2, label="5MA", zorder=5)
    if valid_ma20:
        ax.plot([x[0] for x in valid_ma20], [x[1] for x in valid_ma20],
                color=RED, lw=1.2, label="20MA", zorder=5)
    if valid_ma60:
        ax.plot([x[0] for x in valid_ma60], [x[1] for x in valid_ma60],
                color=AMBER, lw=1.1, label="60MA", zorder=5)

    # Absolute High/Low labels
    valid_highs = [(i, v) for i, v in enumerate(highs) if v is not None]
    valid_lows = [(i, v) for i, v in enumerate(lows) if v is not None]
    if valid_highs and valid_lows:
        hi_idx, hi_val = max(valid_highs, key=lambda x: x[1])
        lo_idx, lo_val = min(valid_lows, key=lambda x: x[1])

        ax.scatter([hi_idx], [hi_val], s=16, color=RED, zorder=6)
        ax.text(hi_idx, hi_val, f"{_p(hi_val)}", color=RED,
                fontsize=8.5, fontweight="bold", ha="center", va="bottom", zorder=7)

        ax.scatter([lo_idx], [lo_val], s=16, color=GREEN, zorder=6)
        ax.text(lo_idx, lo_val, f"{_p(lo_val)}", color=GREEN,
                fontsize=8.5, fontweight="bold", ha="center", va="top", zorder=7)

    # Right side Y-axis price scale
    ax.yaxis.tick_right()
    ax.yaxis.set_label_position("right")
    ax.tick_params(axis="y", labelsize=7.5, colors=TEXT_MUTED)

    # Dates
    dates = [str(r.get("date") or "") for r in rows]
    step = max(1, len(dates) // 4)
    ticks = list(range(0, len(dates), step))
    if dates and (len(dates) - 1) not in ticks:
        ticks.append(len(dates) - 1)

    ax.tick_params(axis="x", labelbottom=False)
    ax.set_xlim(-1, n_bars)
    axv.set_xlim(-1, n_bars)
    axv.set_xticks(ticks)
    axv.set_xticklabels([dates[i].replace("-", "/") for i in ticks], fontsize=7.2)
    axv.tick_params(axis="y", labelleft=False)

    # 5. Floating OHLCV Box rendered INSIDE ax using transAxes (zorder=10)
    # Box container
    box_patch = FancyBboxPatch(
        (0.015, 0.380), 0.250, 0.600,
        boxstyle="round,pad=0.01,rounding_size=0.02",
        facecolor="#FFFFFF", edgecolor="#D1D5DB", linewidth=0.9,
        transform=ax.transAxes, zorder=10,
    )
    ax.add_patch(box_patch)

    dt_str = str(last.get("date") or "").replace("-", "/")
    ax.text(0.140, 0.942, dt_str, transform=ax.transAxes,
            fontsize=8.2, color=TEXT_MAIN, ha="center", va="center", zorder=11)

    box_items = [
        ("開", _p(last.get("open")), color),
        ("高", _p(last.get("max") if last.get("max") is not None else last.get("high")), RED),
        ("低", _p(last.get("min") if last.get("min") is not None else last.get("low")), GREEN),
        ("收", _p(last.get("close")), color),
        ("漲幅", f"{change:+,.0f} ({rate:+.1f}%)" if abs(change) >= 100 else f"{change:+,.2f} ({rate:+.1f}%)", color),
        ("量", _lots(last.get("Trading_Volume") if last.get("Trading_Volume") is not None else last.get("volume")), AMBER),
    ]

    by = 0.865
    for b_lbl, b_val, b_col in box_items:
        ax.text(0.035, by, b_lbl, transform=ax.transAxes,
                fontsize=8.0, color=TEXT_MUTED, va="center", zorder=11)
        ax.text(0.245, by, str(b_val), transform=ax.transAxes,
                fontsize=8.0, fontweight="bold", color=b_col, ha="right", va="center", zorder=11)
        by -= 0.082

    _style_chart_white(ax)
    _style_chart_white(axv)

    return _save(fig, path)


# ==========================================
# 4. Institutional Card (T2330 / T大盤)
# ==========================================
def _stock_inst_series(rows: list[dict]) -> list[dict]:
    def net(row, buy_key, sell_key):
        return (_num(row.get(buy_key), 0) or 0) - (_num(row.get(sell_key), 0) or 0)
    out = []
    for r in sorted(rows, key=lambda x: str(x.get("date") or "")):
        out.append({
            "date": str(r.get("date") or ""),
            "foreign": (net(r, "Foreign_Investor_buy", "Foreign_Investor_sell") +
                        net(r, "Foreign_Dealer_Self_buy", "Foreign_Dealer_Self_sell")),
            "trust": net(r, "Investment_Trust_buy", "Investment_Trust_sell"),
            "dealer": (net(r, "Dealer_buy", "Dealer_sell") +
                       net(r, "Dealer_self_buy", "Dealer_self_sell") +
                       net(r, "Dealer_Hedging_buy", "Dealer_Hedging_sell")),
        })
    return out


def _institution_panel_white(fig, canvas, y: float, height: float, title: str,
                             pct_label: str, pct_val: str, rows: list[dict], key: str,
                             unit_divisor: float, unit_label: str):
    vals = [float(r.get(key) or 0) / unit_divisor for r in rows]
    dates = [r.get("date", "") for r in rows]
    latest = vals[-1] if vals else 0
    color = RED if latest > 0 else (GREEN if latest < 0 else FLAT)

    # Panel Container
    _rounded(canvas, (0.045, y), 0.910, height, radius=0.010,
             face="#FFFFFF", edge=BORDER_LIGHT, lw=0.9, zorder=1)

    # Top line of panel: e.g. "日法人 09/24 外資持股比" + "69.2%" (Amber) + "買賣超 -4,668 張" (Green/Red)
    canvas.text(0.065, y + height - 0.022, f"{title} {pct_label}", transform=canvas.transAxes,
                fontsize=9.5, fontweight="bold", color=TEXT_MUTED, va="center", zorder=2)

    # Calculate offset for amber percentage text
    offset_x = 0.065 + (len(f"{title} {pct_label}") * 0.019)
    canvas.text(offset_x, y + height - 0.022, pct_val, transform=canvas.transAxes,
                fontsize=10.0, fontweight="bold", color=AMBER, va="center", zorder=2)

    canvas.text(0.935, y + height - 0.022, f"買賣超 {_signed(latest, 0 if unit_label=='張' else 1, ' ' + unit_label)}",
                transform=canvas.transAxes, fontsize=10.5, fontweight="bold", color=color,
                ha="right", va="center", zorder=2)

    # Chart area inside panel
    ax = fig.add_axes([0.080, y + 0.020, 0.840, height - 0.052])
    colors = [RED if v >= 0 else GREEN for v in vals]
    ax.bar(range(len(vals)), vals, color=colors, width=0.68, alpha=0.85, zorder=3)
    ax.axhline(0, color="#9CA3AF", lw=0.6, ls="--", zorder=2)

    # Simulated/Accumulated holdings trend curve (subtle gray line like in screenshot)
    cum_vals = []
    c = 0.0
    for v in vals:
        c += v * 0.05
        cum_vals.append(c)
    ax2 = ax.twinx()
    ax2.plot(range(len(cum_vals)), cum_vals, color="#9CA3AF", lw=0.9, alpha=0.7, zorder=4)
    ax2.set_axis_off()

    _style_chart_white(ax)

    # Right side Y axis formatter
    ax.yaxis.tick_right()
    ax.yaxis.set_label_position("right")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
    ax.tick_params(axis="y", labelsize=6.8, colors=TEXT_MUTED)

    # Dates
    step = max(1, len(vals) // 4)
    ticks = list(range(0, len(vals), step))
    if vals and len(vals) - 1 not in ticks:
        ticks.append(len(vals) - 1)
    ax.set_xticks(ticks)
    ax.set_xticklabels([dates[i].replace("-", "/") if len(dates[i]) >= 10 else dates[i] for i in ticks], fontsize=6.8)


def render_institutional_card(title: str, code: str, snapshot: dict | None,
                              rows: list[dict], path: Path, market=False) -> Path:
    fig, canvas = _new_figure()

    category = "指數" if market else "個股"
    if snapshot:
        _draw_header(
            canvas,
            title=title,
            code=code if not market else "",
            category=category,
            price=snapshot.get("close"),
            change=snapshot.get("change_price"),
            rate=snapshot.get("change_rate"),
            timestamp=_dt_text(snapshot),
            is_market=market,
        )
    else:
        _draw_header(
            canvas,
            title=title,
            code=code if not market else "",
            category=category,
            price=None,
            change=0,
            rate=0,
            timestamp="",
            is_market=market,
        )

    if market:
        series = rows[-45:]
        divisor, suffix = 100_000_000.0, "億"
    else:
        series = _stock_inst_series(rows)[-45:]
        divisor, suffix = 1000.0, "張"

    if not series:
        raise RuntimeError("三大法人資料不足")

    # 3 Panels: 外資 (0.560), 投信 (0.305), 自營商 (0.050)
    _institution_panel_white(fig, canvas, 0.560, 0.230, "外資", "持股比", "69.2%", series, "foreign", divisor, suffix)
    _institution_panel_white(fig, canvas, 0.305, 0.230, "投信", "持股比", "3.64%", series, "trust", divisor, suffix)
    _institution_panel_white(fig, canvas, 0.050, 0.230, "自營商", "持股比", "1.44%", series, "dealer", divisor, suffix)

    return _save(fig, path)
