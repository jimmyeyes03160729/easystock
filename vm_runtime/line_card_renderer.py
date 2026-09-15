#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""EasyStock LINE compact card renderer (V4.3.2).

Changes from V4.3.1:
- Keep V4.3.1 compact 900x720 layout and button-friendly design.
- K-line chart uses more of the canvas (less blank space above the plot).
- K-line highest high and lowest low are annotated directly on the chart.
- K-line summary bar remains compact.
- Taiwan market convention: up=red, down=green.
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

# Try to register Noto CJK on Ubuntu. Noto CJK JP also contains Traditional
# Chinese glyphs, so it is a safe fallback if TC face discovery is weak.
for _font_path in (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
):
    try:
        if Path(_font_path).exists():
            fm.fontManager.addfont(_font_path)
    except Exception:
        pass

BRAND = "當沖吧！牛馬仔 ｜ EasyStock   By JimmyWei"
BG = "#f4f7fb"
CARD = "#ffffff"
TEXT = "#111827"
MUTED = "#718096"
GRID = "#dbe3ee"
RED = "#e53935"      # 台股上漲
GREEN = "#0f9d58"    # 台股下跌
YELLOW = "#f2b705"


def _font_family() -> str:
    candidates = [
        "Noto Sans CJK TC",
        "Noto Sans CJK JP",
        "Noto Sans TC",
        "Microsoft JhengHei",
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


def _direction(change: Any) -> tuple[str, str]:
    x = _num(change, 0.0) or 0.0
    if x > 0:
        return "▲", RED
    if x < 0:
        return "▼", GREEN
    return "－", MUTED


def _dt_text(snapshot: dict) -> str:
    text = str(snapshot.get("timestamp_text") or "").strip()
    if text:
        return text
    return datetime.now().strftime("%m/%d %H:%M:%S")


def _new_figure():
    # 7.2 x 5.76 @ 125 dpi = 900 x 720 px (5:4)
    fig = plt.figure(figsize=(7.2, 5.76), dpi=125, facecolor=BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    return fig, ax


def _rounded(ax, xy, width, height, radius=0.025, face=CARD, edge="none", lw=1):
    p = FancyBboxPatch(
        xy, width, height,
        boxstyle=f"round,pad=0.006,rounding_size={radius}",
        facecolor=face, edgecolor=edge, linewidth=lw,
        transform=ax.transAxes,
    )
    ax.add_patch(p)
    return p


def _candlestick_icon(ax, x, y, size=0.030):
    """Small icon only; keep title/status text visually dominant."""
    ax.add_patch(Circle((x, y), size, transform=ax.transAxes,
                        facecolor="#f0f4fa", edgecolor="none"))
    xs = [x - size * .33, x, x + size * .33]
    vals = [(.35, .10, .22), (.55, .14, .32), (.74, .18, .40)]
    for xx, (hi, lo, body) in zip(xs, vals):
        ax.plot([xx, xx], [y-size*lo, y+size*hi], transform=ax.transAxes,
                color=TEXT, lw=.85)
        ax.add_patch(Rectangle((xx-size*.10, y-size*.02), size*.20, size*body,
                               transform=ax.transAxes, facecolor=RED,
                               edgecolor=TEXT, linewidth=.55))


def _header_price(
    ax,
    *,
    title: str,
    code: str,
    badge: str,
    price: Any,
    change: Any,
    rate: Any,
    timestamp: str,
):
    """One compact title row: name/code + price/change + status badge."""
    arrow, color = _direction(change)
    _candlestick_icon(ax, 0.066, 0.906, size=.029)

    ax.text(0.108, 0.919, title, transform=ax.transAxes,
            fontsize=18.5, fontweight="bold", color=TEXT, va="center")
    if code:
        ax.text(0.108, 0.878, code, transform=ax.transAxes,
                fontsize=10.5, fontweight="bold", color=MUTED, va="center")

    # Price immediately beside stock/index name instead of a separate large row.
    ax.text(0.385, 0.911, _p(price), transform=ax.transAxes,
            fontsize=21.5, fontweight="bold", color=color, va="center")
    ch = abs(_num(change, 0.0) or 0.0)
    rt = _num(rate, 0.0) or 0.0
    ax.text(0.610, 0.911, f"{arrow}{ch:,.2f}  {rt:+.2f}%",
            transform=ax.transAxes, fontsize=11.5, fontweight="bold",
            color=color, va="center")

    # Smaller pill, larger label.
    _rounded(ax, (0.820, 0.870), 0.135, 0.065, radius=.015, face="#f5f7fb")
    ax.text(0.8875, 0.903, badge, transform=ax.transAxes,
            fontsize=11.8, fontweight="bold", color=TEXT,
            ha="center", va="center")

    ax.text(0.610, 0.874, timestamp, transform=ax.transAxes,
            fontsize=8.2, color=MUTED, va="center")
    return color


def _metric_inline(ax, x, y, label, value, color=TEXT, size=10.3):
    ax.text(x, y, f"{label} {value}", transform=ax.transAxes,
            fontsize=size, fontweight="bold", color=color, va="center", ha="left")


def _footer(ax):
    ax.text(0.5, 0.036, BRAND, transform=ax.transAxes,
            fontsize=7.7, color="#98a2b3", ha="center", va="center")


def _save(fig, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=fig.get_facecolor(), bbox_inches=None, pad_inches=0)
    plt.close(fig)
    return path


def _style_chart(ax):
    ax.set_facecolor(CARD)
    ax.grid(True, color=GRID, alpha=.7, linewidth=.5)
    ax.tick_params(colors=MUTED, labelsize=7.1, length=2)
    for s in ax.spines.values():
        s.set_color(GRID)


def _intraday_axes(fig):
    # 固定交易分鐘軸，不使用 datetime sharex，避免 matplotlib 自動縮放。
    ax = fig.add_axes([.075, .270, .85, .405])
    axv = fig.add_axes([.075, .195, .85, .055])
    return ax, axv


def _compact_summary_row(canvas, items: list[tuple[str, str, str]]):
    _rounded(canvas, (.045, .090), .91, .070, radius=.015, face="#f7f9fc")
    n = max(1, len(items))
    for i, (label, value, color) in enumerate(items):
        x = .065 + i * (.87 / n)
        canvas.text(x, .125, f"{label} {value}", transform=canvas.transAxes,
                    fontsize=8.9, fontweight="bold", color=color, va="center")


def render_stock_intraday_card(snapshot: dict, rows: list[dict], path: Path) -> Path:
    fig, canvas = _new_figure()
    _rounded(canvas, (.018, .018), .964, .964, radius=.026)
    name, code = snapshot.get("name", "股票"), snapshot.get("code", "")
    color = _header_price(
        canvas, title=str(name), code=str(code), badge="即時走勢",
        price=snapshot.get("close"), change=snapshot.get("change_price"),
        rate=snapshot.get("change_rate"), timestamp=_dt_text(snapshot),
    )

    ref = _num(snapshot.get("reference"))
    # One compact data row only.
    _metric_inline(canvas, .055, .758, "開", _p(snapshot.get("open")), TEXT)
    _metric_inline(canvas, .225, .758, "高", _p(snapshot.get("high")), RED)
    _metric_inline(canvas, .395, .758, "低", _p(snapshot.get("low")), GREEN)
    _metric_inline(canvas, .565, .758, "均", _p(snapshot.get("average_price")), TEXT)
    _metric_inline(canvas, .745, .758, "量", _lots(snapshot.get("total_volume")), TEXT, size=9.6)

    ax, axv = _intraday_axes(fig)
    valid = [r for r in rows if r.get("close") is not None]
    if valid:
        times = [r["time"] for r in valid]
        closes = [float(r["close"]) for r in valid]
        vols = [float(r.get("volume") or 0) for r in valid]

        # 固定台股盤中座標：09:00 = 0，13:30 = 270
        xvals = [
            (t.hour * 60 + t.minute) - 540
            for t in times
        ]

        base = ref or closes[0]

        ax.plot(xvals, closes, color=color, lw=1.35)
        ax.fill_between(xvals, closes, base, where=[c >= base for c in closes], color=RED, alpha=.08, interpolate=True)
        ax.fill_between(xvals, closes, base, where=[c < base for c in closes], color=GREEN, alpha=.08, interpolate=True)
        ax.axhline(base, color=MUTED, lw=.65, ls="--")
        ticks = list(range(0, 271, 30))

        labels = [
            "09:00",
            "09:30",
            "10:00",
            "10:30",
            "11:00",
            "11:30",
            "12:00",
            "12:30",
            "13:00",
            "13:30",
        ]

        ax.set_xlim(0, 270)
        ax.set_xticks(ticks)
        ax.set_xticklabels(labels)

        ax.tick_params(axis="x", labelbottom=False)

        axv.bar(xvals, vols, width=0.8, color=YELLOW, alpha=.82)
        axv.set_xlim(0, 270)
        axv.set_xticks(ticks)
        axv.set_xticklabels(labels)
    else:
        ax.text(.5, .5, "盤中走勢暫無資料", transform=ax.transAxes,
                ha="center", va="center", color=MUTED, fontsize=11)
    _style_chart(ax)
    _style_chart(axv)

    if valid:
        ax.set_xlim(0, 270)
        axv.set_xlim(0, 270)

    _compact_summary_row(canvas, [
        ("昨量", _lots(snapshot.get("yesterday_volume")), TEXT),
        ("估量", _lots(snapshot.get("estimated_volume")), TEXT),
        ("參考", _p(ref), TEXT),
        ("漲跌", _signed(snapshot.get("change_rate"), 2, "%"), color),
    ])
    _footer(canvas)
    return _save(fig, path)


def render_market_intraday_card(snapshot: dict, rows: list[dict], path: Path) -> Path:
    fig, canvas = _new_figure()
    _rounded(canvas, (.018, .018), .964, .964, radius=.026)
    color = _header_price(
        canvas, title="加權指數", code="TAIEX", badge="大盤走勢",
        price=snapshot.get("close"), change=snapshot.get("change_price"),
        rate=snapshot.get("change_rate"), timestamp=_dt_text(snapshot),
    )
    ref = _num(snapshot.get("reference"))
    _metric_inline(canvas, .055, .758, "開", _p(snapshot.get("open")), TEXT)
    _metric_inline(canvas, .225, .758, "高", _p(snapshot.get("high")), RED)
    _metric_inline(canvas, .395, .758, "低", _p(snapshot.get("low")), GREEN)
    _metric_inline(canvas, .565, .758, "參考", _p(ref), TEXT, size=9.8)
    _metric_inline(canvas, .755, .758, "成交", _money_100m(snapshot.get("total_amount")), TEXT, size=9.2)

    ax, axv = _intraday_axes(fig)
    valid = [r for r in rows if r.get("close") is not None]
    if valid:
        times = [r["time"] for r in valid]
        closes = [float(r["close"]) for r in valid]
        vols = [float(r.get("volume") or 0) for r in valid]

        # 固定台股盤中座標：09:00 = 0，13:30 = 270
        xvals = [
            (t.hour * 60 + t.minute) - 540
            for t in times
        ]

        base = ref or closes[0]

        ax.plot(xvals, closes, color=color, lw=1.35)
        ax.fill_between(xvals, closes, base, where=[c >= base for c in closes], color=RED, alpha=.08, interpolate=True)
        ax.fill_between(xvals, closes, base, where=[c < base for c in closes], color=GREEN, alpha=.08, interpolate=True)
        ax.axhline(base, color=MUTED, lw=.65, ls="--")
        ticks = list(range(0, 271, 30))

        labels = [
            "09:00",
            "09:30",
            "10:00",
            "10:30",
            "11:00",
            "11:30",
            "12:00",
            "12:30",
            "13:00",
            "13:30",
        ]

        ax.set_xlim(0, 270)
        ax.set_xticks(ticks)
        ax.set_xticklabels(labels)

        ax.tick_params(axis="x", labelbottom=False)

        axv.bar(xvals, vols, width=0.8, color=YELLOW, alpha=.82)
        axv.set_xlim(0, 270)
        axv.set_xticks(ticks)
        axv.set_xticklabels(labels)
    else:
        ax.text(.5, .5, "盤中指數走勢暫無資料", transform=ax.transAxes,
                ha="center", va="center", color=MUTED, fontsize=11)
    _style_chart(ax)
    _style_chart(axv)

    if valid:
        ax.set_xlim(0, 270)
        axv.set_xlim(0, 270)

    _compact_summary_row(canvas, [
        ("上漲", _compact(snapshot.get("up_count")), RED),
        ("下跌", _compact(snapshot.get("down_count")), GREEN),
        ("漲停", _compact(snapshot.get("limit_up_count")), RED),
        ("跌停", _compact(snapshot.get("limit_down_count")), GREEN),
    ])
    _footer(canvas)
    return _save(fig, path)


def _date_labels(rows: list[dict]) -> tuple[list[str], list[int]]:
    dates = [str(r.get("date") or "") for r in rows]
    step = max(1, len(dates) // 5)
    ticks = list(range(0, len(dates), step))
    if dates and (len(dates)-1) not in ticks:
        ticks.append(len(dates)-1)
    return dates, ticks




def _annotate_k_extremes(ax, highs, lows):
    valid_highs = [(i, v) for i, v in enumerate(highs) if v is not None]
    valid_lows = [(i, v) for i, v in enumerate(lows) if v is not None]
    if not valid_highs and not valid_lows:
        return

    total = max(len(highs), len(lows), 1)

    def _xalign(idx: int):
        if idx <= total * 0.15:
            return (18, 'left')
        if idx >= total * 0.85:
            return (-18, 'right')
        return (0, 'center')

    if valid_highs:
        hi_idx, hi_val = max(valid_highs, key=lambda x: x[1])
        dx, ha = _xalign(hi_idx)
        ax.scatter([hi_idx], [hi_val], s=14, color=RED, zorder=6)
        ax.annotate(
            f"高 {_p(hi_val)}",
            xy=(hi_idx, hi_val),
            xytext=(dx, 14),
            textcoords='offset points',
            ha=ha, va='bottom',
            fontsize=7.6, fontweight='bold', color=RED,
            arrowprops=dict(arrowstyle='-', color=RED, lw=0.8),
            bbox=dict(boxstyle='round,pad=0.18', fc='white', ec='none', alpha=0.88),
            zorder=7,
        )

    if valid_lows:
        lo_idx, lo_val = min(valid_lows, key=lambda x: x[1])
        dx, ha = _xalign(lo_idx)
        ax.scatter([lo_idx], [lo_val], s=14, color=GREEN, zorder=6)
        ax.annotate(
            f"低 {_p(lo_val)}",
            xy=(lo_idx, lo_val),
            xytext=(dx, 12),
            textcoords='offset points',
            ha=ha, va='bottom',
            fontsize=7.6, fontweight='bold', color=GREEN,
            arrowprops=dict(arrowstyle='-', color=GREEN, lw=0.8),
            bbox=dict(boxstyle='round,pad=0.18', fc='white', ec='none', alpha=0.88),
            zorder=7,
        )

def render_k_card(title: str, code: str, rows: list[dict], path: Path, is_market=False) -> Path:
    fig, canvas = _new_figure()
    _rounded(canvas, (.018, .018), .964, .964, radius=.026)
    rows = sorted(rows, key=lambda x: str(x.get("date") or ""))[-60:]
    if not rows:
        raise RuntimeError("K 線資料不足")
    last = rows[-1]
    prev = rows[-2].get("close") if len(rows) > 1 else last.get("open")
    close = _num(last.get("close")); prevf = _num(prev)
    change = (close - prevf) if close is not None and prevf is not None else 0
    rate = (change / prevf * 100) if prevf else 0
    color = _header_price(
        canvas, title=title, code=code, badge="K線",
        price=close, change=change, rate=rate,
        timestamp=str(last.get("date") or ""),
    )

    # Enlarge K-line plot area to reduce empty space between the header and chart.
    ax = fig.add_axes([.060, .232, .88, .500])
    axv = fig.add_axes([.060, .162, .88, .060], sharex=ax)
    opens = [_num(r.get("open")) for r in rows]
    highs = [_num(r.get("max") if r.get("max") is not None else r.get("high")) for r in rows]
    lows = [_num(r.get("min") if r.get("min") is not None else r.get("low")) for r in rows]
    closes = [_num(r.get("close")) for r in rows]
    vols = [_num(r.get("Trading_Volume") if r.get("Trading_Volume") is not None else r.get("volume"), 0) or 0 for r in rows]
    for i, (o, h, l, c) in enumerate(zip(opens, highs, lows, closes)):
        if None in (o, h, l, c):
            continue
        col = RED if c >= o else GREEN
        ax.vlines(i, l, h, color=col, linewidth=.72)
        ax.add_patch(Rectangle((i-.28, min(o,c)), .56, max(abs(c-o), .001), facecolor=col, edgecolor=col, linewidth=.45))
        axv.bar(i, vols[i], width=.58, color=col, alpha=.72)
    _style_chart(ax); _style_chart(axv)
    dates, ticks = _date_labels(rows)
    ax.tick_params(axis="x", labelbottom=False)
    axv.set_xticks(ticks)
    axv.set_xticklabels([dates[i][5:] if len(dates[i]) >= 10 else dates[i] for i in ticks])
    ax.set_xlim(-1, len(rows))
    _annotate_k_extremes(ax, highs, lows)

    _compact_summary_row(canvas, [
        ("開", _p(last.get("open")), TEXT),
        ("高", _p(last.get("max") if last.get("max") is not None else last.get("high")), RED),
        ("低", _p(last.get("min") if last.get("min") is not None else last.get("low")), GREEN),
        ("收", _p(last.get("close")), color),
    ])
    _footer(canvas)
    return _save(fig, path)


def _stock_inst_series(rows: list[dict]) -> list[dict]:
    def net(row, buy_key, sell_key):
        return (_num(row.get(buy_key), 0) or 0) - (_num(row.get(sell_key), 0) or 0)
    out = []
    for r in sorted(rows, key=lambda x: str(x.get("date") or "")):
        out.append({
            "date": str(r.get("date") or ""),
            "foreign": net(r, "Foreign_Investor_buy", "Foreign_Investor_sell") + net(r, "Foreign_Dealer_Self_buy", "Foreign_Dealer_Self_sell"),
            "trust": net(r, "Investment_Trust_buy", "Investment_Trust_sell"),
            "dealer": net(r, "Dealer_buy", "Dealer_sell") + net(r, "Dealer_self_buy", "Dealer_self_sell") + net(r, "Dealer_Hedging_buy", "Dealer_Hedging_sell"),
        })
    return out


def _institution_panel(fig, canvas, y, height, title, rows, key, unit_divisor, unit_label):
    vals = [float(r.get(key) or 0) / unit_divisor for r in rows]
    dates = [r.get("date", "") for r in rows]
    latest = vals[-1] if vals else 0
    color = RED if latest > 0 else GREEN if latest < 0 else MUTED
    _rounded(canvas, (.045, y), .91, height, radius=.014, face="#fbfcfe", edge="#edf1f7", lw=.7)
    canvas.text(.065, y+height-.028, title, transform=canvas.transAxes, fontsize=11.7,
                fontweight="bold", color=TEXT, va="center")
    canvas.text(.935, y+height-.028, f"{_signed(latest, 1, unit_label)}", transform=canvas.transAxes,
                fontsize=10.8, fontweight="bold", color=color, ha="right", va="center")
    ax = fig.add_axes([.09, y+.018, .84, max(.055, height-.060)])
    colors = [RED if v >= 0 else GREEN for v in vals]
    ax.bar(range(len(vals)), vals, color=colors, width=.72, alpha=.80)
    ax.axhline(0, color=MUTED, lw=.55)
    _style_chart(ax)
    step = max(1, len(vals)//4)
    ticks = list(range(0, len(vals), step))
    if vals and len(vals)-1 not in ticks:
        ticks.append(len(vals)-1)
    ax.set_xticks(ticks)
    ax.set_xticklabels([dates[i][5:] if len(dates[i]) >= 10 else dates[i] for i in ticks], fontsize=6.1)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))


def render_institutional_card(title: str, code: str, snapshot: dict | None,
                              rows: list[dict], path: Path, market=False) -> Path:
    fig, canvas = _new_figure()
    _rounded(canvas, (.018, .018), .964, .964, radius=.026)

    if snapshot:
        _header_price(
            canvas, title=title, code=code, badge="三大法人",
            price=snapshot.get("close"), change=snapshot.get("change_price"),
            rate=snapshot.get("change_rate"), timestamp=_dt_text(snapshot),
        )
    else:
        _header_price(canvas, title=title, code=code, badge="三大法人",
                      price=None, change=0, rate=0, timestamp="")

    if market:
        series = rows[-60:]
        divisor, suffix = 100_000_000.0, "億"
    else:
        series = _stock_inst_series(rows)[-60:]
        divisor, suffix = 1000.0, "張"
    if not series:
        raise RuntimeError("三大法人資料不足")

    # Three compact panels with minimal dead space.
    _institution_panel(fig, canvas, .610, .175, "外資", series, "foreign", divisor, suffix)
    _institution_panel(fig, canvas, .370, .175, "投信", series, "trust", divisor, suffix)
    _institution_panel(fig, canvas, .130, .175, "自營商", series, "dealer", divisor, suffix)
    _footer(canvas)
    return _save(fig, path)
