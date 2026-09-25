#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""EasyStock LINE compact card renderer (V5.0.0 - Stitch Obsidian Dark).

Google Stitch Dark Obsidian Redesign:
- Obsidian dark glassmorphism palette (#0B101B / #121A29).
- Taiwan market convention strictly enforced: UP is Red (#EF4444), DOWN is Green (#10B981).
- P-card: Intraday smooth glowing curve, VWAP (均價線), high/low pins, time marker, volume bars.
- K-card: Standard Japanese candlesticks (紅陽線、綠陰線), MA5/MA20/MA60, Volume MA20, KD/RSI indicators.
- Market-card: TAIEX intraday with Advance/Decline breadth (上漲/下跌/漲停/跌停).
- T-card: Institutional net buys/sells across Foreign, Investment Trust, and Dealer.
- 5:4 aspect ratio (900x720 px @ 125 dpi), optimized for mobile LINE chat preview.
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

# Register Noto Sans CJK on Ubuntu / Linux
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
# Stitch Obsidian Dark Color Palette
# ==========================================
BRAND = "當沖吧！牛馬仔 ｜ EasyStock · 智慧量化看板"
BG = "#0b101b"              # Outer background
CARD = "#121a29"            # Main container card
CARD_BORDER = "#1e2a3e"     # Container border
CARD_INNER = "#172235"      # Metrics row / panels
CARD_INNER_BORDER = "#223147"
TEXT = "#f8fafc"            # Bright white text (primary)
MUTED = "#94a3b8"           # Slate-400 text (secondary)
DIM = "#64748b"             # Slate-500 text (timestamps, grids)
GRID = "#182335"            # Subtle grid line color
CHART_BG = "#0d1422"        # Chart plot background
CHART_BORDER = "#1e293b"    # Plot border

# Taiwan Stock Market Conventions: 漲紅跌綠
RED = "#ef4444"             # Taiwan Up / Bullish
RED_SOFT = "#f87171"
RED_PILL_BG = "#2b1218"
RED_PILL_BORDER = "#7f1d1d"

GREEN = "#10b981"           # Taiwan Down / Bearish
GREEN_SOFT = "#34d399"
GREEN_PILL_BG = "#0a261d"
GREEN_PILL_BORDER = "#064e3b"

FLAT = "#94a3b8"            # Neutral / Flat
FLAT_PILL_BG = "#192231"
FLAT_PILL_BORDER = "#334155"

GOLD = "#f59e0b"            # VWAP / MA5 / Amber highlight
CYAN = "#06b6d4"            # MA20 / Volume highlight
PURPLE = "#a855f7"          # MA60


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
    return f"{x:,.0f}張"


def _money_100m(v: Any) -> str:
    x = _num(v)
    if x is None:
        return "--"
    return f"{x / 100_000_000:,.1f}億"


def _signed(v: Any, decimals: int = 2, suffix: str = "") -> str:
    x = _num(v)
    if x is None:
        return "--"
    sign = "+" if x > 0 else ""
    return f"{sign}{x:,.{decimals}f}{suffix}"


def _direction(change: Any) -> tuple[str, str, str, str]:
    x = _num(change, 0.0) or 0.0
    if x > 0:
        return "▲", RED, RED_PILL_BG, RED_PILL_BORDER
    if x < 0:
        return "▼", GREEN, GREEN_PILL_BG, GREEN_PILL_BORDER
    return "－", FLAT, FLAT_PILL_BG, FLAT_PILL_BORDER


def _dt_text(snapshot: dict) -> str:
    text = str(snapshot.get("timestamp_text") or "").strip()
    if text:
        return text
    return datetime.now().strftime("%m/%d %H:%M:%S")


def _new_figure():
    # 7.2 x 5.76 @ 125 dpi = 900 x 720 px (5:4 aspect ratio)
    fig = plt.figure(figsize=(7.2, 5.76), dpi=125, facecolor=BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    return fig, ax


def _rounded(ax, xy, width, height, radius=0.025, face=CARD, edge=CARD_BORDER, lw=1.0):
    p = FancyBboxPatch(
        xy, width, height,
        boxstyle=f"round,pad=0.005,rounding_size={radius}",
        facecolor=face, edgecolor=edge, linewidth=lw,
        transform=ax.transAxes, zorder=1,
    )
    ax.add_patch(p)
    return p


def _header(
    canvas,
    *,
    title: str,
    code: str,
    badge: str,
    price: Any,
    change: Any,
    rate: Any,
    timestamp: str,
) -> str:
    """Obsidian header matching Google Stitch visual hierarchy."""
    arrow, color, pill_bg, pill_border = _direction(change)

    # 1. Top left active indicator dot + brand text
    canvas.add_patch(Circle((0.057, 0.932), 0.0055, transform=canvas.transAxes,
                            facecolor=GREEN, edgecolor="none", zorder=2))
    canvas.text(0.068, 0.932, "EasyStock 官方機器人", transform=canvas.transAxes,
                fontsize=8.5, fontweight="bold", color=MUTED, va="center")

    # 2. Main title & code
    canvas.text(0.052, 0.888, title, transform=canvas.transAxes,
                fontsize=19.5, fontweight="bold", color=TEXT, va="center")
    if code:
        canvas.text(0.052, 0.852, code, transform=canvas.transAxes,
                    fontsize=10.0, fontweight="bold", color=MUTED, va="center")

    # 3. Price (prominent center-right)
    canvas.text(0.390, 0.892, _p(price), transform=canvas.transAxes,
                fontsize=22.5, fontweight="bold", color=color, va="center")

    # 4. Change Pill Badge
    ch = abs(_num(change, 0.0) or 0.0)
    rt = abs(_num(rate, 0.0) or 0.0)
    pill_text = f"{arrow} {ch:,.2f}  ({rt:.2f}%)"
    _rounded(canvas, (0.595, 0.865), 0.200, 0.055, radius=0.015,
             face=pill_bg, edge=pill_border, lw=0.9)
    canvas.text(0.695, 0.892, pill_text, transform=canvas.transAxes,
                fontsize=10.5, fontweight="bold", color=color,
                ha="center", va="center")

    # 5. Right Mode Badge & Timestamp
    _rounded(canvas, (0.825, 0.875), 0.125, 0.048, radius=0.013,
             face=CARD_INNER, edge=CARD_INNER_BORDER, lw=0.8)
    canvas.text(0.8875, 0.899, badge, transform=canvas.transAxes,
                fontsize=9.2, fontweight="bold", color=TEXT,
                ha="center", va="center")

    canvas.text(0.8875, 0.848, timestamp, transform=canvas.transAxes,
                fontsize=7.8, color=DIM, ha="center", va="center")

    return color


def _hud_metrics(canvas, y: float, height: float, items: list[tuple[str, str, str]]):
    """Sleek dark HUD metrics bar."""
    _rounded(canvas, (0.048, y), 0.904, height, radius=0.015,
             face=CARD_INNER, edge=CARD_INNER_BORDER, lw=0.8)
    n = max(1, len(items))
    step = 0.904 / n
    for i, (label, val, col) in enumerate(items):
        cx = 0.048 + (i + 0.5) * step
        canvas.text(cx, y + height * 0.68, label, transform=canvas.transAxes,
                    fontsize=8.0, fontweight="bold", color=MUTED, ha="center", va="center")
        canvas.text(cx, y + height * 0.28, str(val), transform=canvas.transAxes,
                    fontsize=9.8, fontweight="bold", color=col, ha="center", va="center")


def _summary_row(canvas, y: float, height: float, items: list[tuple[str, str, str]]):
    """Bottom summary bar."""
    _rounded(canvas, (0.048, y), 0.904, height, radius=0.015,
             face=CARD_INNER, edge=CARD_INNER_BORDER, lw=0.8)
    n = max(1, len(items))
    step = 0.904 / n
    for i, (label, val, col) in enumerate(items):
        cx = 0.048 + (i + 0.5) * step
        canvas.text(cx, y + height * 0.5, f"{label} {val}", transform=canvas.transAxes,
                    fontsize=9.0, fontweight="bold", color=col, ha="center", va="center")


def _footer(canvas):
    canvas.text(0.5, 0.035, BRAND, transform=canvas.transAxes,
                fontsize=7.6, color=DIM, ha="center", va="center")


def _style_chart(ax):
    ax.set_facecolor(CHART_BG)
    ax.grid(True, color=GRID, alpha=0.75, linestyle="-", linewidth=0.55)
    ax.tick_params(colors=MUTED, labelsize=7.3, length=2, width=0.7)
    for s in ax.spines.values():
        s.set_color(CHART_BORDER)
        s.set_linewidth(0.8)


def _save(fig, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=fig.get_facecolor(), bbox_inches=None, pad_inches=0)
    plt.close(fig)
    return path


def _annotate_intraday_extremes(ax, xvals, closes):
    """Annotate single highest and single lowest points with proper alignment."""
    if not xvals or not closes:
        return

    hi_idx = max(range(len(closes)), key=lambda i: closes[i])
    lo_idx = min(range(len(closes)), key=lambda i: closes[i])
    total = len(xvals)

    # High annotation
    hx, hy = xvals[hi_idx], closes[hi_idx]
    ax.scatter([hx], [hy], s=22, color=RED, zorder=7)
    ha_high = "right" if hi_idx > total * 0.8 else ("left" if hi_idx < total * 0.2 else "center")
    dx_high = -10 if ha_high == "right" else (10 if ha_high == "left" else 0)
    ax.annotate(
        f"高 {_p(hy)}",
        xy=(hx, hy),
        xytext=(dx_high, 8),
        textcoords="offset points",
        ha=ha_high, va="bottom",
        fontsize=7.6, fontweight="bold", color=RED,
        bbox=dict(boxstyle="round,pad=0.22", fc=RED_PILL_BG, ec=RED_PILL_BORDER, lw=0.8, alpha=0.95),
        zorder=8,
    )

    # Low annotation
    lx, ly = xvals[lo_idx], closes[lo_idx]
    ax.scatter([lx], [ly], s=22, color=GREEN, zorder=7)
    ha_low = "right" if lo_idx > total * 0.8 else ("left" if lo_idx < total * 0.2 else "center")
    dx_low = -10 if ha_low == "right" else (10 if ha_low == "left" else 0)
    ax.annotate(
        f"低 {_p(ly)}",
        xy=(lx, ly),
        xytext=(dx_low, -12),
        textcoords="offset points",
        ha=ha_low, va="top",
        fontsize=7.6, fontweight="bold", color=GREEN,
        bbox=dict(boxstyle="round,pad=0.22", fc=GREEN_PILL_BG, ec=GREEN_PILL_BORDER, lw=0.8, alpha=0.95),
        zorder=8,
    )


def _annotate_k_extremes(ax, highs, lows):
    """Annotate single absolute high and single absolute low on K-line chart."""
    valid_highs = [(i, v) for i, v in enumerate(highs) if v is not None]
    valid_lows = [(i, v) for i, v in enumerate(lows) if v is not None]
    if not valid_highs or not valid_lows:
        return

    hi_idx, hi_val = max(valid_highs, key=lambda x: x[1])
    lo_idx, lo_val = min(valid_lows, key=lambda x: x[1])
    total = max(len(highs), len(lows), 1)

    # High annotation
    ha_hi = "right" if hi_idx > total * 0.8 else ("left" if hi_idx < total * 0.2 else "center")
    dx_hi = -10 if ha_hi == "right" else (10 if ha_hi == "left" else 0)
    ax.scatter([hi_idx], [hi_val], s=20, color=RED, zorder=7)
    ax.annotate(
        f"高 {_p(hi_val)}",
        xy=(hi_idx, hi_val),
        xytext=(dx_hi, 8),
        textcoords="offset points",
        ha=ha_hi, va="bottom",
        fontsize=7.6, fontweight="bold", color=RED,
        bbox=dict(boxstyle="round,pad=0.22", fc=RED_PILL_BG, ec=RED_PILL_BORDER, lw=0.8, alpha=0.95),
        zorder=8,
    )

    # Low annotation
    ha_lo = "right" if lo_idx > total * 0.8 else ("left" if lo_idx < total * 0.2 else "center")
    dx_lo = -10 if ha_lo == "right" else (10 if ha_lo == "left" else 0)
    ax.scatter([lo_idx], [lo_val], s=20, color=GREEN, zorder=7)
    ax.annotate(
        f"低 {_p(lo_val)}",
        xy=(lo_idx, lo_val),
        xytext=(dx_lo, -12),
        textcoords="offset points",
        ha=ha_lo, va="top",
        fontsize=7.6, fontweight="bold", color=GREEN,
        bbox=dict(boxstyle="round,pad=0.22", fc=GREEN_PILL_BG, ec=GREEN_PILL_BORDER, lw=0.8, alpha=0.95),
        zorder=8,
    )


def _calc_kd(closes: list[float], highs: list[float], lows: list[float], n=9, m1=3, m2=3):
    if len(closes) < n:
        return None, None
    rsv_list = []
    for i in range(n - 1, len(closes)):
        sub_h = max(highs[i - n + 1: i + 1])
        sub_l = min(lows[i - n + 1: i + 1])
        c = closes[i]
        rsv = 50.0 if sub_h == sub_l else (c - sub_l) / (sub_h - sub_l) * 100.0
        rsv_list.append(rsv)
    k, d = 50.0, 50.0
    for rsv in rsv_list:
        k = (1.0 / m1) * rsv + (1.0 - 1.0 / m1) * k
        d = (1.0 / m2) * k + (1.0 - 1.0 / m2) * d
    return k, d


def _calc_rsi(closes: list[float], period=14):
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        if diff >= 0:
            gains.append(diff)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(diff))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


# ==========================================
# 1. Stock Intraday Card (P2330)
# ==========================================
def render_stock_intraday_card(snapshot: dict, rows: list[dict], path: Path) -> Path:
    fig, canvas = _new_figure()
    _rounded(canvas, (0.018, 0.018), 0.964, 0.964, radius=0.026, face=CARD, edge=CARD_BORDER, lw=1.2)

    name, code = snapshot.get("name", "股票"), snapshot.get("code", "")
    color = _header(
        canvas,
        title=str(name),
        code=f"TWSE · P{code}" if code else "TWSE",
        badge="即時走勢",
        price=snapshot.get("close"),
        change=snapshot.get("change_price"),
        rate=snapshot.get("change_rate"),
        timestamp=_dt_text(snapshot),
    )

    ref = _num(snapshot.get("reference"))
    avg = _num(snapshot.get("average_price"))

    _hud_metrics(canvas, 0.760, 0.066, [
        ("開盤", _p(snapshot.get("open")), TEXT),
        ("最高", _p(snapshot.get("high")), RED),
        ("最低", _p(snapshot.get("low")), GREEN),
        ("均價", _p(avg), GOLD),
        ("總量", _lots(snapshot.get("total_volume")), CYAN),
    ])

    ax = fig.add_axes([0.058, 0.270, 0.884, 0.440])
    axv = fig.add_axes([0.058, 0.180, 0.884, 0.075], sharex=ax)

    valid = [r for r in rows if r.get("close") is not None]
    if valid:
        times = [r["time"] for r in valid]
        closes = [float(r["close"]) for r in valid]
        vols = [float(r.get("volume") or 0) for r in valid]

        xvals = [(t.hour * 60 + t.minute) - 540 for t in times]
        base = ref if ref is not None else closes[0]

        # Dynamic Y limits with 8% padding for headroom
        all_pts = closes + ([base] if base else []) + ([avg] if avg else [])
        min_p, max_p = min(all_pts), max(all_pts)
        span = max(max_p - min_p, 1.0)
        ax.set_ylim(min_p - span * 0.09, max_p + span * 0.09)

        # Reference price horizontal dashed line
        ax.axhline(base, color=DIM, lw=0.75, ls="--", alpha=0.8, zorder=2)

        # Subtle glow + sharp price line
        ax.plot(xvals, closes, color=color, lw=3.0, alpha=0.18, zorder=3)
        ax.plot(xvals, closes, color=color, lw=1.5, zorder=4)

        # Soft shaded area under price
        ax.fill_between(xvals, closes, base, where=[c >= base for c in closes],
                        color=RED, alpha=0.12, interpolate=True, zorder=2)
        ax.fill_between(xvals, closes, base, where=[c < base for c in closes],
                        color=GREEN, alpha=0.12, interpolate=True, zorder=2)

        # VWAP Golden Line if available
        if avg:
            ax.axhline(avg, color=GOLD, lw=0.9, ls=":", alpha=0.85, zorder=3)

        # High/Low Pin Annotations
        _annotate_intraday_extremes(ax, xvals, closes)

        # Latest price right edge marker
        last_x, last_c = xvals[-1], closes[-1]
        ax.scatter([last_x], [last_c], s=26, color=color, edgecolors=TEXT, linewidths=1.0, zorder=7)

        ticks = list(range(0, 271, 30))
        labels = [
            "09:00", "09:30", "10:00", "10:30", "11:00",
            "11:30", "12:00", "12:30", "13:00", "13:30",
        ]
        ax.set_xlim(0, 270)
        ax.set_xticks(ticks)
        ax.tick_params(axis="x", labelbottom=False)

        # Volume bars
        bar_colors = [RED if c >= base else GREEN for c in closes]
        axv.bar(xvals, vols, width=0.85, color=bar_colors, alpha=0.85)
        axv.set_xlim(0, 270)
        axv.set_xticks(ticks)
        axv.set_xticklabels(labels)
        axv.tick_params(axis="y", labelleft=False)
    else:
        ax.text(0.5, 0.5, "盤中走勢暫無資料", transform=ax.transAxes,
                ha="center", va="center", color=MUTED, fontsize=11)

    _style_chart(ax)
    _style_chart(axv)

    _summary_row(canvas, 0.088, 0.065, [
        ("昨量", _lots(snapshot.get("yesterday_volume")), TEXT),
        ("估量", _lots(snapshot.get("estimated_volume")), TEXT),
        ("參考", _p(ref), MUTED),
        ("漲跌", _signed(snapshot.get("change_rate"), 2, "%"), color),
    ])

    _footer(canvas)
    return _save(fig, path)


# ==========================================
# 2. Market Intraday Card (P大盤)
# ==========================================
def render_market_intraday_card(snapshot: dict, rows: list[dict], path: Path) -> Path:
    fig, canvas = _new_figure()
    _rounded(canvas, (0.018, 0.018), 0.964, 0.964, radius=0.026, face=CARD, edge=CARD_BORDER, lw=1.2)

    color = _header(
        canvas,
        title="加權指數",
        code="TAIEX · P大盤",
        badge="大盤走勢",
        price=snapshot.get("close"),
        change=snapshot.get("change_price"),
        rate=snapshot.get("change_rate"),
        timestamp=_dt_text(snapshot),
    )

    ref = _num(snapshot.get("reference"))

    _hud_metrics(canvas, 0.760, 0.066, [
        ("開盤", _p(snapshot.get("open")), TEXT),
        ("最高", _p(snapshot.get("high")), RED),
        ("最低", _p(snapshot.get("low")), GREEN),
        ("昨收", _p(ref), MUTED),
        ("成交金額", _money_100m(snapshot.get("total_amount")), CYAN),
    ])

    ax = fig.add_axes([0.058, 0.270, 0.884, 0.440])
    axv = fig.add_axes([0.058, 0.180, 0.884, 0.075], sharex=ax)

    valid = [r for r in rows if r.get("close") is not None]
    if valid:
        times = [r["time"] for r in valid]
        closes = [float(r["close"]) for r in valid]
        vols = [float(r.get("volume") or 0) for r in valid]

        xvals = [(t.hour * 60 + t.minute) - 540 for t in times]
        base = ref if ref is not None else closes[0]

        all_pts = closes + ([base] if base else [])
        min_p, max_p = min(all_pts), max(all_pts)
        span = max(max_p - min_p, 1.0)
        ax.set_ylim(min_p - span * 0.09, max_p + span * 0.09)

        ax.axhline(base, color=DIM, lw=0.75, ls="--", alpha=0.8, zorder=2)
        ax.plot(xvals, closes, color=color, lw=3.0, alpha=0.18, zorder=3)
        ax.plot(xvals, closes, color=color, lw=1.5, zorder=4)

        ax.fill_between(xvals, closes, base, where=[c >= base for c in closes],
                        color=RED, alpha=0.12, interpolate=True, zorder=2)
        ax.fill_between(xvals, closes, base, where=[c < base for c in closes],
                        color=GREEN, alpha=0.12, interpolate=True, zorder=2)

        _annotate_intraday_extremes(ax, xvals, closes)

        last_x, last_c = xvals[-1], closes[-1]
        ax.scatter([last_x], [last_c], s=26, color=color, edgecolors=TEXT, linewidths=1.0, zorder=7)

        ticks = list(range(0, 271, 30))
        labels = [
            "09:00", "09:30", "10:00", "10:30", "11:00",
            "11:30", "12:00", "12:30", "13:00", "13:30",
        ]
        ax.set_xlim(0, 270)
        ax.set_xticks(ticks)
        ax.tick_params(axis="x", labelbottom=False)

        bar_colors = [RED if c >= base else GREEN for c in closes]
        axv.bar(xvals, vols, width=0.85, color=bar_colors, alpha=0.85)
        axv.set_xlim(0, 270)
        axv.set_xticks(ticks)
        axv.set_xticklabels(labels)
        axv.tick_params(axis="y", labelleft=False)
    else:
        ax.text(0.5, 0.5, "盤中指數走勢暫無資料", transform=ax.transAxes,
                ha="center", va="center", color=MUTED, fontsize=11)

    _style_chart(ax)
    _style_chart(axv)

    _summary_row(canvas, 0.088, 0.065, [
        ("上漲", _compact(snapshot.get("up_count")), RED),
        ("下跌", _compact(snapshot.get("down_count")), GREEN),
        ("漲停", _compact(snapshot.get("limit_up_count")), RED),
        ("跌停", _compact(snapshot.get("limit_down_count")), GREEN),
    ])

    _footer(canvas)
    return _save(fig, path)


# ==========================================
# 3. K-Line Candlestick Card (K2330 / K大盤)
# ==========================================
def render_k_card(title: str, code: str, rows: list[dict], path: Path, is_market=False) -> Path:
    fig, canvas = _new_figure()
    _rounded(canvas, (0.018, 0.018), 0.964, 0.964, radius=0.026, face=CARD, edge=CARD_BORDER, lw=1.2)

    rows = sorted(rows, key=lambda x: str(x.get("date") or ""))[-60:]
    if not rows:
        raise RuntimeError("K 線資料不足")

    last = rows[-1]
    prev = rows[-2].get("close") if len(rows) > 1 else last.get("open")
    close = _num(last.get("close"))
    prevf = _num(prev)
    change = (close - prevf) if close is not None and prevf is not None else 0
    rate = (change / prevf * 100) if prevf else 0

    badge_text = "大盤K線" if is_market else "日K線圖"
    code_text = "TAIEX · K大盤" if is_market else (f"TWSE · K{code}" if code else "TWSE")

    color = _header(
        canvas,
        title=title,
        code=code_text,
        badge=badge_text,
        price=close,
        change=change,
        rate=rate,
        timestamp=str(last.get("date") or ""),
    )

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
    vol_ma20 = moving_average(vols, 20)

    clean_closes = [c for c in closes if c is not None]
    clean_highs = [h for h in highs if h is not None]
    clean_lows = [l for l in lows if l is not None]
    kd_k, kd_d = _calc_kd(clean_closes, clean_highs, clean_lows)
    rsi = _calc_rsi(clean_closes)

    _hud_metrics(canvas, 0.760, 0.066, [
        ("■ MA5", _p(ma5[-1]) if ma5 else "--", GOLD),
        ("■ MA20", _p(ma20[-1]) if ma20 else "--", CYAN),
        ("■ MA60", _p(ma60[-1]) if ma60 else "--", PURPLE),
        ("開盤", _p(last.get("open")), TEXT),
        ("成交量", _lots(last.get("Trading_Volume") if last.get("Trading_Volume") is not None else last.get("volume")), CYAN),
    ])

    ax = fig.add_axes([0.058, 0.280, 0.884, 0.435])
    axv = fig.add_axes([0.058, 0.170, 0.884, 0.095], sharex=ax)

    # Dynamic Y limits with 8% padding
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

        ax.vlines(i, l, h, color=bar_col, linewidth=1.1, zorder=3)
        body_bottom = min(o, c)
        body_height = max(abs(c - o), 0.001)
        ax.add_patch(Rectangle(
            (i - 0.28, body_bottom), 0.56, body_height,
            facecolor=bar_col, edgecolor=bar_col, linewidth=0.5, zorder=4,
        ))
        axv.bar(i, v, width=0.62, color=bar_col, alpha=0.80)

    valid_ma5 = [(i, v) for i, v in enumerate(ma5) if v is not None]
    valid_ma20 = [(i, v) for i, v in enumerate(ma20) if v is not None]
    valid_ma60 = [(i, v) for i, v in enumerate(ma60) if v is not None]
    valid_vol_ma20 = [(i, v) for i, v in enumerate(vol_ma20) if v is not None]

    if valid_ma5:
        ax.plot([x[0] for x in valid_ma5], [x[1] for x in valid_ma5],
                color=GOLD, lw=1.25, label="MA5", zorder=5)
    if valid_ma20:
        ax.plot([x[0] for x in valid_ma20], [x[1] for x in valid_ma20],
                color=CYAN, lw=1.25, label="MA20", zorder=5)
    if valid_ma60:
        ax.plot([x[0] for x in valid_ma60], [x[1] for x in valid_ma60],
                color=PURPLE, lw=1.1, label="MA60", zorder=5)
    if valid_vol_ma20:
        axv.plot([x[0] for x in valid_vol_ma20], [x[1] for x in valid_vol_ma20],
                 color=GOLD, lw=0.9, zorder=5)

    _annotate_k_extremes(ax, highs, lows)

    if close is not None:
        ax.axhline(close, color=color, lw=0.8, ls="--", alpha=0.7, zorder=2)

    dates = [str(r.get("date") or "") for r in rows]
    step = max(1, len(dates) // 5)
    ticks = list(range(0, len(dates), step))
    if dates and (len(dates) - 1) not in ticks:
        ticks.append(len(dates) - 1)

    ax.tick_params(axis="x", labelbottom=False)
    ax.set_xlim(-1, n_bars)
    axv.set_xlim(-1, n_bars)
    axv.set_xticks(ticks)
    axv.set_xticklabels([dates[i][5:] if len(dates[i]) >= 10 else dates[i] for i in ticks])
    axv.tick_params(axis="y", labelleft=False)

    _style_chart(ax)
    _style_chart(axv)

    kd_text = f"K {kd_k:.1f} / D {kd_d:.1f}" if kd_k is not None else "--"
    kd_status = "金叉" if (kd_k is not None and kd_k >= kd_d) else "死叉"
    kd_color = RED if kd_status == "金叉" else GREEN
    rsi_text = f"{rsi:.1f}" if rsi is not None else "--"

    _summary_row(canvas, 0.088, 0.065, [
        ("最高", _p(last.get("max") if last.get("max") is not None else last.get("high")), RED),
        ("最低", _p(last.get("min") if last.get("min") is not None else last.get("low")), GREEN),
        ("KD(9,3)", f"{kd_text} ({kd_status})", kd_color),
        ("RSI(14)", rsi_text, GOLD if (rsi and rsi > 60) else TEXT),
    ])

    _footer(canvas)
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


def _institution_panel(fig, canvas, y: float, height: float, title: str, rows: list[dict],
                       key: str, unit_divisor: float, unit_label: str):
    vals = [float(r.get(key) or 0) / unit_divisor for r in rows]
    dates = [r.get("date", "") for r in rows]
    latest = vals[-1] if vals else 0
    color = RED if latest > 0 else (GREEN if latest < 0 else FLAT)

    _rounded(canvas, (0.048, y), 0.904, height, radius=0.015,
             face=CARD_INNER, edge=CARD_INNER_BORDER, lw=0.8)

    canvas.text(0.068, y + height - 0.026, title, transform=canvas.transAxes,
                fontsize=11.5, fontweight="bold", color=TEXT, va="center")
    canvas.text(0.932, y + height - 0.026, _signed(latest, 1, unit_label), transform=canvas.transAxes,
                fontsize=11.0, fontweight="bold", color=color, ha="right", va="center")

    ax = fig.add_axes([0.088, y + 0.018, 0.840, max(0.055, height - 0.058)])
    colors = [RED if v >= 0 else GREEN for v in vals]
    ax.bar(range(len(vals)), vals, color=colors, width=0.72, alpha=0.82)
    ax.axhline(0, color=DIM, lw=0.6, ls="--")
    _style_chart(ax)

    step = max(1, len(vals) // 4)
    ticks = list(range(0, len(vals), step))
    if vals and len(vals) - 1 not in ticks:
        ticks.append(len(vals) - 1)
    ax.set_xticks(ticks)
    ax.set_xticklabels([dates[i][5:] if len(dates[i]) >= 10 else dates[i] for i in ticks], fontsize=6.5)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
    ax.tick_params(axis="y", labelsize=6.8, colors=DIM)


def render_institutional_card(title: str, code: str, snapshot: dict | None,
                              rows: list[dict], path: Path, market=False) -> Path:
    fig, canvas = _new_figure()
    _rounded(canvas, (0.018, 0.018), 0.964, 0.964, radius=0.026, face=CARD, edge=CARD_BORDER, lw=1.2)

    code_text = "TAIEX · T大盤" if market else (f"TWSE · T{code}" if code else "TWSE")

    if snapshot:
        _header(
            canvas,
            title=title,
            code=code_text,
            badge="三大法人",
            price=snapshot.get("close"),
            change=snapshot.get("change_price"),
            rate=snapshot.get("change_rate"),
            timestamp=_dt_text(snapshot),
        )
    else:
        _header(
            canvas,
            title=title,
            code=code_text,
            badge="三大法人",
            price=None,
            change=0,
            rate=0,
            timestamp="",
        )

    if market:
        series = rows[-60:]
        divisor, suffix = 100_000_000.0, "億"
    else:
        series = _stock_inst_series(rows)[-60:]
        divisor, suffix = 1000.0, "張"

    if not series:
        raise RuntimeError("三大法人資料不足")

    _institution_panel(fig, canvas, 0.610, 0.175, "外資 (Foreign)", series, "foreign", divisor, suffix)
    _institution_panel(fig, canvas, 0.370, 0.175, "投信 (Investment Trust)", series, "trust", divisor, suffix)
    _institution_panel(fig, canvas, 0.130, 0.175, "自營商 (Dealer)", series, "dealer", divisor, suffix)

    _footer(canvas)
    return _save(fig, path)
