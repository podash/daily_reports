"""
Build the HTML email for the weekly Affiliate GEO Report.

Sections (per ТЗ):
  1. Top Partners
  2. Falling Partners
  3. New Partners
  4. Reactivation
  5. Zero Activity
  6. Traffic Quality (6.1 No FTD + 6.2 Low Conversion)
  7. Partner Activity
  8. Affiliate Totals (6 weeks, inbound vs acquisition)
  9. Month Comparison
"""

import io
from datetime import date

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

DAY_NAMES = {
    0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu",
    4: "Fri", 5: "Sat", 6: "Sun",
}

MONTH_NAMES = {
    1:"Jan",2:"Feb",3:"Mar",4:"Apr",5:"May",6:"Jun",
    7:"Jul",8:"Aug",9:"Sep",10:"Oct",11:"Nov",12:"Dec",
}


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _v(val) -> float:
    try:
        return float(val) if val is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _fmt_usd(val) -> str:
    v = _v(val)
    if v < 0:
        return f"&minus;${abs(v):,.0f}"
    return f"${v:,.0f}"


def _fmt_int(val) -> str:
    return f"{int(_v(val)):,}"


def _fmt_pct(val, decimals: int = 1) -> str:
    return f"{_v(val):.{decimals}f}%"


def _na() -> str:
    return '<span style="color:#d1d5db;">&mdash;</span>'


def _delta_pct(val) -> str:
    """Color-coded percentage change string."""
    v = _v(val)
    if v == 0:
        return '<span style="color:#6b7280;">0%</span>'
    color = "#15803d" if v > 0 else "#dc2626"
    sign = "+" if v > 0 else ""
    return f'<span style="color:{color};font-weight:600;">{sign}{v:.1f}%</span>'


def _pct_exec(val) -> str:
    """Color-coded plan execution %."""
    if val is None:
        return _na()
    v = _v(val)
    color = "#15803d" if v >= 100 else ("#d97706" if v >= 75 else "#dc2626")
    return f'<span style="color:{color};font-weight:700;">{v:.1f}%</span>'


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

STYLES = """
<style>
    body, table, td, th, p, div {
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
    }
    .report-container { max-width: 1000px; margin: 0 auto; background: #fff; }
    .header {
        background: linear-gradient(135deg, #1e3a5f 0%, #2563eb 100%);
        color: #fff; padding: 24px 28px; border-radius: 8px 8px 0 0;
    }
    .header h1 { margin: 0; font-size: 20px; font-weight: 700; }
    .header .sub { margin: 4px 0 0 0; font-size: 13px; color: #93c5fd; }
    .section { padding: 0 24px; margin-bottom: 4px; }
    .block-title {
        font-size: 12px; font-weight: 700; color: #1e3a5f;
        text-transform: uppercase; letter-spacing: 1px;
        padding: 16px 0 6px 0; margin: 0;
        border-bottom: 2px solid #2563eb;
    }
    .block-desc { font-size: 11px; color: #6b7280; margin: 4px 0 8px 0; }
    table.dt {
        width: 100%; border-collapse: collapse; margin: 0;
        font-size: 12px;
    }
    table.dt th {
        text-align: left; font-size: 10px; font-weight: 600; color: #6b7280;
        text-transform: uppercase; letter-spacing: 0.4px;
        padding: 6px 8px; border-bottom: 1px solid #e5e7eb;
        white-space: nowrap;
    }
    table.dt th.r, table.dt td.r { text-align: right; }
    table.dt th.c, table.dt td.c { text-align: center; }
    table.dt td {
        padding: 6px 8px; color: #1f2937;
        border-bottom: 1px solid #f3f4f6;
        font-variant-numeric: tabular-nums;
    }
    table.dt tr:last-child td { border-bottom: none; }
    table.dt .mn { font-weight: 500; color: #374151; white-space: nowrap; }
    table.dt .bold { font-weight: 700; color: #111827; }
    table.dt .gray { color: #9ca3af; font-size: 11px; }
    table.dt .mono { font-family: monospace; font-size: 11px; color: #374151; }
    table.dt tr.total td { background: #eff6ff; font-weight: 700; color: #1e3a5f; border-top: 2px solid #2563eb; }
    table.dt tr.inbound td { background: #f0fdf4; }
    table.dt tr.acquis td  { background: #eff6ff; }
    .badge {
        display: inline-block; padding: 1px 7px;
        border-radius: 10px; font-size: 10px; font-weight: 600;
    }
    .b-green  { background: #dcfce7; color: #15803d; }
    .b-red    { background: #fee2e2; color: #b91c1c; }
    .b-yellow { background: #fef9c3; color: #854d0e; }
    .b-blue   { background: #dbeafe; color: #1d4ed8; }
    .b-gray   { background: #f3f4f6; color: #6b7280; }
    .info-box {
        margin: 8px 0; padding: 10px 14px; border-radius: 6px;
        background: #eff6ff; border-left: 4px solid #2563eb;
        font-size: 12px; color: #1e3a5f;
    }
    .info-box.warn { background: #fef9c3; border-color: #f59e0b; color: #854d0e; }
    .kpi-row { padding: 12px 24px; }
    .footer {
        padding: 14px 24px; text-align: center;
        font-size: 10px; color: #9ca3af; border-top: 1px solid #e5e7eb;
    }
</style>
"""


# ---------------------------------------------------------------------------
# Shared table helpers
# ---------------------------------------------------------------------------

def _section(title: str, desc: str, body: str) -> str:
    return (
        f'<div class="section">'
        f'<p class="block-title">{title}</p>'
        f'<p class="block-desc">{desc}</p>'
        f'{body}'
        f'</div>'
    )


def _empty(msg: str = "No data for this period.") -> str:
    return f'<div class="info-box">{msg}</div>'


# ---------------------------------------------------------------------------
# Block 1 — Top Partners
# ---------------------------------------------------------------------------

def _build_block1(rows_ftd: list[dict], rows_dep: list[dict], periods: dict | None = None) -> str:
    def _table(rows: list[dict], sort_col: str) -> str:
        if not rows:
            return _empty()
        th = (
            '<th>#</th><th>Partner ID</th><th>Manager</th><th>Type</th>'
            '<th class="r">Regs</th><th class="r">Conv%</th><th class="r">FTD</th>'
            '<th class="r">NP Dep Sum</th><th class="r">Deposits USD</th>'
        )
        rows_html = ""
        rank = 0
        for r in rows:
            is_total = r.get("_is_total", False)
            ftd_bold = ' bold' if sort_col == "ftd" else ''
            dep_bold = ' bold' if sort_col == "dep" else ''
            gt       = r.get("group_type", "")
            gt_color = "#15803d" if gt == "Inbound" else ("#2563eb" if gt == "Acquisition" else "#6b7280")
            type_cell = (
                f'<span style="font-size:10px;color:{gt_color};font-weight:500;">{gt}</span>'
                if gt else ""
            )
            if is_total:
                total_style = (
                    'style="background:#f0f9ff;border-top:2px solid #2563eb;'
                    'font-weight:700;color:#1e3a5f;"'
                )
                rows_html += (
                    f'<tr {total_style}>'
                    f'<td class="gray"></td>'
                    f'<td class="mono" style="font-weight:700;">TOTAL</td>'
                    f'<td></td><td></td>'
                    f'<td class="r">{_fmt_int(r["regs"])}</td>'
                    f'<td class="r">{_fmt_pct(r["conversion_pct"])}</td>'
                    f'<td class="r{ftd_bold}">{_fmt_int(r["ftd"])}</td>'
                    f'<td class="r">{_fmt_usd(r["new_dep_amount"])}</td>'
                    f'<td class="r{dep_bold}">{_fmt_usd(r["deposits_usd"])}</td>'
                    f'</tr>'
                )
            else:
                rank += 1
                rows_html += (
                    f'<tr>'
                    f'<td class="gray">{rank}</td>'
                    f'<td class="mono">{r["affiliate_id"]}</td>'
                    f'<td class="mn">{r["manager"]}</td>'
                    f'<td>{type_cell}</td>'
                    f'<td class="r">{_fmt_int(r["regs"])}</td>'
                    f'<td class="r">{_fmt_pct(r["conversion_pct"])}</td>'
                    f'<td class="r{ftd_bold}">{_fmt_int(r["ftd"])}</td>'
                    f'<td class="r">{_fmt_usd(r["new_dep_amount"])}</td>'
                    f'<td class="r{dep_bold}">{_fmt_usd(r["deposits_usd"])}</td>'
                    f'</tr>'
                )
        return f'<table class="dt"><tr>{th}</tr>{rows_html}</table>'

    sub_label = (
        '<span style="font-size:11px;font-weight:600;color:#374151;display:block;margin:0 0 4px 0;">'
        'Top 10 by FTD &mdash; min 3 FTD</span>'
    )
    sub_dep = (
        '<span style="font-size:11px;font-weight:600;color:#374151;display:block;'
        'margin:16px 0 4px 0;">Top 10 by Deposits &mdash; min $100/week</span>'
    )
    body = (
        sub_label + _table(rows_ftd, "ftd")
        + sub_dep + _table(rows_dep, "dep")
    )
    if periods:
        w_s = periods["week4_start"].strftime("%d %b")
        w_e = periods["period_end"].strftime("%d %b %Y")
        sub = f"{w_s} &ndash; {w_e}, all countries"
    else:
        sub = "Current week, all countries"
    return _section("1. Top Partners", sub, body)


# ---------------------------------------------------------------------------
# Block 2 — Falling Partners
# ---------------------------------------------------------------------------

def _build_block2(rows: list[dict]) -> str:
    if not rows:
        return _section("2. Falling Partners",
                        "Active players decline vs 90-day avg (normalized to 1 week), sorted by absolute drop",
                        _empty("No falling partners detected."))
    th = (
        '<th>Partner ID</th><th>Manager</th><th>Type</th>'
        '<th class="r">Drop (Players)</th>'
        '<th class="r">Prev Avg/Wk</th>'
        '<th class="r">Current Wk</th>'
        '<th class="r">Change %</th>'
        '<th class="r">Deposits USD</th>'
    )
    rows_html = ""
    for r in rows:
        drop  = float(r.get("players_drop") or 0)
        prev  = float(r.get("players_prev_period") or 0)
        curr  = int(r.get("players_curr_period") or 0)
        chg   = float(r.get("change_pct") or 0)
        gt    = r.get("group_type", "")
        gt_color = "#15803d" if gt == "Inbound" else ("#2563eb" if gt == "Acquisition" else "#6b7280")
        type_cell = f'<span style="font-size:10px;color:{gt_color};font-weight:500;">{gt}</span>'
        drop_cell = f'<span style="color:#dc2626;font-weight:700;">{drop:+.1f}</span>'
        chg_cell  = f'<span style="color:#dc2626;font-weight:700;">{chg:.1f}%</span>'
        rows_html += (
            f'<tr>'
            f'<td class="mono">{r["affiliate_id"]}</td>'
            f'<td class="mn">{r["manager"]}</td>'
            f'<td>{type_cell}</td>'
            f'<td class="r">{drop_cell}</td>'
            f'<td class="r gray">{prev:.1f}</td>'
            f'<td class="r bold">{curr}</td>'
            f'<td class="r">{chg_cell}</td>'
            f'<td class="r">{_fmt_usd(r["deposits_usd"])}</td>'
            f'</tr>'
        )
    body = f'<table class="dt"><tr>{th}</tr>{rows_html}</table>'
    return _section("2. Falling Partners",
                    "Active players decline vs 90-day avg (normalized to 1 week), sorted by absolute drop",
                    body)


# ---------------------------------------------------------------------------
# Block 3 — New Partners
# ---------------------------------------------------------------------------

def _build_block3(rows: list[dict]) -> str:
    if not rows:
        return _section("3. New Partners",
                        "First activity within last 3 months, FTD &gt; 0 in last 4 weeks",
                        _empty("No new partners with FTD found."))
    th = (
        '<th>Partner ID</th><th>Manager</th><th>First Seen</th>'
        '<th class="r">Regs</th><th class="r">FTD</th>'
        '<th class="r">FTD Amount</th><th class="r">Deposits USD</th>'
        '<th class="r">Conv%</th>'
    )
    rows_html = ""
    for r in rows:
        fd = r.get("first_date")
        first_str = fd.strftime("%d.%m.%Y") if hasattr(fd, "strftime") else (str(fd)[:10] if fd else "—")
        rows_html += (
            f'<tr>'
            f'<td class="mono">{r["affiliate_id"]}</td>'
            f'<td class="mn">{r["manager"]}</td>'
            f'<td class="gray">{first_str}</td>'
            f'<td class="r">{_fmt_int(r["regs"])}</td>'
            f'<td class="r bold">{_fmt_int(r["ftd"])}</td>'
            f'<td class="r">{_fmt_usd(r["ftd_amount"])}</td>'
            f'<td class="r">{_fmt_usd(r["deposits_usd"])}</td>'
            f'<td class="r">{_fmt_pct(r["conversion_pct"])}</td>'
            f'</tr>'
        )
    body = f'<table class="dt"><tr>{th}</tr>{rows_html}</table>'
    return _section("3. New Partners",
                    "First activity within last 3 months, FTD &gt; 0 in last 4 weeks",
                    body)


# ---------------------------------------------------------------------------
# Block 4 — Reactivation
# ---------------------------------------------------------------------------

def _build_block4(rows: list[dict]) -> str:
    if not rows:
        return _section("4. Reactivation",
                        "Avg FTD last 3 months &le;1 (normalized), current 4 weeks FTD &ge;1. TOP 15",
                        _empty("No reactivations detected."))
    th = (
        '<th>Partner ID</th><th>Manager</th>'
        '<th class="r">FTD (4w)</th><th class="r">FTD Amt</th>'
        '<th class="r">Deposits USD</th><th class="r">Regs</th>'
        '<th class="r">Ref FTD (norm.)</th>'
    )
    rows_html = ""
    for r in rows:
        rows_html += (
            f'<tr>'
            f'<td class="mono">{r["affiliate_id"]}</td>'
            f'<td class="mn">{r["manager"]}</td>'
            f'<td class="r bold">{_fmt_int(r["ftd"])}</td>'
            f'<td class="r">{_fmt_usd(r["ftd_amount"])}</td>'
            f'<td class="r">{_fmt_usd(r["deposits_usd"])}</td>'
            f'<td class="r">{_fmt_int(r["regs"])}</td>'
            f'<td class="r gray">{_v(r["ftd_ref_norm"]):.2f}</td>'
            f'</tr>'
        )
    body = f'<table class="dt"><tr>{th}</tr>{rows_html}</table>'
    return _section("4. Reactivation",
                    "Avg FTD last 3 months &le;1 (normalized), current 4 weeks FTD &ge;1. TOP 15",
                    body)


# ---------------------------------------------------------------------------
# Block 5 — Zero Activity
# ---------------------------------------------------------------------------

def _build_block5(rows: list[dict], rows_high_dep: list[dict] | None = None) -> str:
    def _zero_table(rows: list[dict]) -> str:
        if not rows:
            return _empty("No zero-activity partners found.")
        th = (
            '<th>Partner ID</th><th>Type</th>'
            '<th class="r">Hist. Deposits (12m)</th>'
            '<th class="r">Last 4w Deposits</th>'
        )
        rows_html = ""
        for r in rows:
            gt = r.get("group_type", "")
            gt_color = "#15803d" if gt == "Inbound" else ("#2563eb" if gt == "Acquisition" else "#6b7280")
            type_cell = f'<span style="font-size:10px;color:{gt_color};font-weight:500;">{gt}</span>' if gt else ""
            rows_html += (
                f'<tr>'
                f'<td class="mono">{r["affiliate_id"]}</td>'
                f'<td>{type_cell}</td>'
                f'<td class="r bold">{_fmt_usd(r["hist_deposits"])}</td>'
                f'<td class="r"><span style="color:#dc2626;">$0</span></td>'
                f'</tr>'
            )
        return f'<table class="dt"><tr>{th}</tr>{rows_html}</table>'

    def _high_dep_table(rows: list[dict]) -> str:
        if not rows:
            return ""
        label = (
            '<p style="font-size:11px;font-weight:600;color:#374151;margin:0 0 4px 0;">'
            'High Deposits, 0 FTD'
            '<span class="badge b-red" style="margin-left:8px;">Top 15 deposits, 0 FTD (last 4w)</span>'
            '</p>'
        )
        th = (
            '<th>Partner ID</th><th>Type</th>'
            '<th class="r">Regs</th>'
            '<th class="r">FTD</th>'
            '<th class="r">Deposits USD</th>'
        )
        rows_html = ""
        for r in rows:
            gt = r.get("group_type", "")
            gt_color = "#15803d" if gt == "Inbound" else ("#2563eb" if gt == "Acquisition" else "#6b7280")
            type_cell = f'<span style="font-size:10px;color:{gt_color};font-weight:500;">{gt}</span>' if gt else ""
            rows_html += (
                f'<tr>'
                f'<td class="mono">{r["affiliate_id"]}</td>'
                f'<td>{type_cell}</td>'
                f'<td class="r">{_fmt_int(r["regs"])}</td>'
                f'<td class="r"><span style="color:#dc2626;font-weight:700;">0</span></td>'
                f'<td class="r bold">{_fmt_usd(r["deposits_usd"])}</td>'
                f'</tr>'
            )
        return label + f'<table class="dt"><tr>{th}</tr>{rows_html}</table>'

    zero_label = (
        '<p style="font-size:11px;font-weight:600;color:#374151;margin:0 0 4px 0;">'
        'Zero Deposits Last 4 Weeks'
        '<span class="badge b-gray" style="margin-left:8px;">Had activity in 12m. TOP 15</span>'
        '</p>'
    )
    body = zero_label + _zero_table(rows)
    if rows_high_dep:
        body += '<div style="margin-top:20px;"></div>' + _high_dep_table(rows_high_dep)

    return _section("5. Zero Activity",
                    "Had deposits in last 12 months, 0 deposits in last 4 weeks. TOP 15",
                    body)


# ---------------------------------------------------------------------------
# Block 6 — Traffic Quality
# ---------------------------------------------------------------------------

def _build_block6_no_ftd(rows: list[dict]) -> str:
    if not rows:
        return '<div class="info-box">No partners with Regs &gt; 30 and FTD = 0.</div>'
    th = (
        '<th>Partner ID</th>'
        '<th class="r">Regs (4w)</th><th class="r">FTD</th><th class="r">Deposits</th>'
        '<th class="c" title="180-day cohort regs">Cohort</th>'
        '<th class="c">D+0</th><th class="c">D+3</th><th class="c">D+7</th>'
        '<th class="c">D+14</th><th class="c">D+30</th><th class="c">All-time</th>'
    )
    rows_html = ""
    for r in rows:
        cohort = int(_v(r.get("cohort_regs")))
        def _chk(key):
            n = int(_v(r.get(key)))
            if cohort == 0:
                return _na()
            pct = n / cohort * 100
            color = "#15803d" if pct >= 5 else ("#d97706" if pct >= 1 else "#dc2626")
            return f'<span style="color:{color};font-size:10px;">{n}<br><span style="color:{color};">{pct:.1f}%</span></span>'
        rows_html += (
            f'<tr>'
            f'<td class="mono">{r["affiliate_id"]}</td>'
            f'<td class="r">{_fmt_int(r["regs"])}</td>'
            f'<td class="r"><span style="color:#dc2626;">0</span></td>'
            f'<td class="r">{_fmt_usd(r["deposits_usd"])}</td>'
            f'<td class="c gray">{cohort:,}</td>'
            f'<td class="c">{_chk("check0")}</td>'
            f'<td class="c">{_chk("check3")}</td>'
            f'<td class="c">{_chk("check7")}</td>'
            f'<td class="c">{_chk("check14")}</td>'
            f'<td class="c">{_chk("check30")}</td>'
            f'<td class="c">{_chk("check_alltime")}</td>'
            f'</tr>'
        )
    return f'<table class="dt"><tr>{th}</tr>{rows_html}</table>'


def _build_block6_low_conv(rows: list[dict]) -> str:
    if not rows:
        return '<div class="info-box">No partners below GEO average conversion.</div>'
    th = (
        '<th>Partner ID</th><th>Manager</th><th>Country</th>'
        '<th class="r">Regs</th><th class="r">FTD</th>'
        '<th class="r">Conv%</th><th class="r">GEO Avg%</th><th class="r">Gap</th>'
    )
    rows_html = ""
    for r in rows:
        conv = _v(r["conversion_pct"])
        geo_avg = _v(r["geo_avg_conv_pct"])
        gap = conv - geo_avg
        gap_cell = f'<span style="color:#dc2626;font-weight:600;">{gap:.1f}pp</span>'
        rows_html += (
            f'<tr>'
            f'<td class="mono">{r["affiliate_id"]}</td>'
            f'<td class="mn">{r["manager"]}</td>'
            f'<td class="mn">{r["country"]}</td>'
            f'<td class="r">{_fmt_int(r["regs"])}</td>'
            f'<td class="r">{_fmt_int(r["ftd"])}</td>'
            f'<td class="r"><span style="color:#dc2626;">{conv:.2f}%</span></td>'
            f'<td class="r gray">{geo_avg:.2f}%</td>'
            f'<td class="r">{gap_cell}</td>'
            f'</tr>'
        )
    return f'<table class="dt"><tr>{th}</tr>{rows_html}</table>'


def _build_block6(no_ftd: list[dict], low_conv: list[dict]) -> str:
    body = (
        '<p style="font-size:11px;font-weight:600;color:#374151;margin:8px 0 4px 0;">'
        '6.1 Registrations without FTD'
        '<span class="badge b-gray" style="margin-left:8px;">Conv &lt; 5%, min 5 regs (last 4w)</span>'
        '<span class="badge b-yellow" style="margin-left:6px;">Traffic checks: 180-day cohort</span>'
        '</p>'
        + _build_block6_no_ftd(no_ftd)
        + '<p style="font-size:11px;font-weight:600;color:#374151;margin:14px 0 4px 0;">'
          '6.2 Conversion below GEO average'
          '<span class="badge b-gray" style="margin-left:8px;">Min 10 regs, TOP 10</span>'
          '</p>'
        + _build_block6_low_conv(low_conv)
    )
    return _section("6. Traffic Quality", "Last 4 weeks, Focus GEO", body)


# ---------------------------------------------------------------------------
# Block 7 — Partner Activity
# ---------------------------------------------------------------------------

def _render_chart_b64(fig) -> str:
    """Render a matplotlib figure to base64 PNG data URL and close the figure."""
    import base64
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=110)
    plt.close(fig)
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _chart_img_tag(src: str, alt: str = "") -> str:
    return (
        f'<img src="{src}" alt="{alt}" '
        f'style="max-width:100%;height:auto;display:block;margin:8px 0;">'
    )


def _build_monthly_chart(chart_rows: list[dict], manager_label: str) -> str:
    """Return html_snippet with base64-embedded PNG chart."""
    if not chart_rows:
        return ""

    from datetime import date as _date
    from collections import defaultdict

    month_data: dict = defaultdict(lambda: {"Inbound": 0, "Acquisition": 0, "Other": 0})
    months: list = []
    for r in chart_rows:
        ms = r.get("month_start")
        if hasattr(ms, "strftime"):
            key = ms.strftime("%b %Y")
            if key not in months:
                months.append(key)
            gt = r.get("group_type", "Other")
            month_data[key][gt] = float(r.get("deposits_usd") or 0)

    inbound  = [month_data[m]["Inbound"]     for m in months]
    acquis   = [month_data[m]["Acquisition"] for m in months]
    xs = list(range(len(months)))

    fig, ax = plt.subplots(figsize=(9, 2.8), dpi=110)
    ax.plot(xs, inbound, marker="o", markersize=4, color="#15803d",
            linewidth=1.8, label="Inbound")
    ax.fill_between(xs, inbound, alpha=0.07, color="#15803d")
    ax.plot(xs, acquis, marker="o", markersize=4, color="#2563eb",
            linewidth=1.8, label="Acquisition")
    ax.fill_between(xs, acquis, alpha=0.07, color="#2563eb")

    ax.set_xticks(xs)
    ax.set_xticklabels(months, rotation=30, ha="right")
    ax.set_title(f"Monthly Deposits — {manager_label} (last 12 months)",
                 fontsize=9, fontweight="bold", color="#1e3a5f", pad=6)
    ax.set_ylabel("Deposits USD", fontsize=8, color="#6b7280")
    ax.tick_params(axis="x", labelsize=7)
    ax.tick_params(axis="y", labelsize=7)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(
        lambda v, _: f"${v/1000:.0f}k" if v >= 1000 else f"${v:.0f}"
    ))
    ax.set_ylim(bottom=0)
    ax.legend(fontsize=8, loc="upper left")
    ax.grid(axis="y", linestyle="--", linewidth=0.5, alpha=0.5)
    ax.spines[["top", "right"]].set_visible(False)
    fig.patch.set_facecolor("#ffffff")
    ax.set_facecolor("#f9fafb")
    plt.tight_layout(pad=0.8)

    return _chart_img_tag(_render_chart_b64(fig), "Monthly deposits chart")


def _build_activity_chart(weekly_trend: list[dict]) -> str:
    """Return html_snippet with base64-embedded PNG chart."""
    if not weekly_trend:
        return ""

    from datetime import date as _date

    labels, inb_vals, acq_vals = [], [], []
    for r in weekly_trend:
        ws = r.get("week_start")
        if hasattr(ws, "strftime"):
            labels.append(ws.strftime("%d %b"))
        else:
            try:
                labels.append(_date.fromisoformat(str(ws)).strftime("%d %b"))
            except Exception:
                labels.append(str(ws)[:10])
        inb_vals.append(float(r.get("inbound") or 0))
        acq_vals.append(float(r.get("acquisition") or 0))

    xs = list(range(len(labels)))
    fig, ax = plt.subplots(figsize=(8.5, 2.8), dpi=110)

    ax.plot(xs, inb_vals, marker="o", markersize=4, color="#15803d",
            linewidth=1.8, label="Inbound")
    ax.fill_between(xs, inb_vals, alpha=0.07, color="#15803d")
    ax.plot(xs, acq_vals, marker="o", markersize=4, color="#2563eb",
            linewidth=1.8, label="Acquisition")
    ax.fill_between(xs, acq_vals, alpha=0.07, color="#2563eb")

    ax.set_xticks(xs)
    ax.set_xticklabels(labels, rotation=30, ha="right")
    ax.set_title("Active Partners per Week — Inbound vs Acquisition (last 12 weeks)",
                 fontsize=9, fontweight="bold", color="#1e3a5f", pad=6)
    ax.set_ylabel("Active count", fontsize=8, color="#6b7280")
    ax.tick_params(axis="x", labelsize=7)
    ax.tick_params(axis="y", labelsize=7)
    ax.set_ylim(bottom=0)
    ax.legend(fontsize=8, loc="upper left")
    ax.grid(axis="y", linestyle="--", linewidth=0.5, alpha=0.5)
    ax.spines[["top", "right"]].set_visible(False)
    fig.patch.set_facecolor("#ffffff")
    ax.set_facecolor("#f9fafb")

    if inb_vals:
        ax.annotate(f"{inb_vals[-1]:.0f}", (xs[-1], inb_vals[-1]),
                    textcoords="offset points", xytext=(0, 6),
                    fontsize=7, color="#15803d", ha="center")
    if acq_vals:
        ax.annotate(f"{acq_vals[-1]:.0f}", (xs[-1], acq_vals[-1]),
                    textcoords="offset points", xytext=(0, -10),
                    fontsize=7, color="#2563eb", ha="center")
    plt.tight_layout(pad=0.8)

    return _chart_img_tag(_render_chart_b64(fig), "Weekly active partners chart")


def _build_block7(stats: dict) -> str:
    base_12m    = stats.get("base_12m", 0)
    all_p       = stats.get("all_partners", 0)
    active_week = stats.get("active_week", 0)
    pct         = stats.get("pct_active", 0)
    group_rows  = stats.get("group_rows", [])
    weekly_trend = stats.get("weekly_trend", [])

    pct_color = "#15803d" if pct >= 50 else ("#d97706" if pct >= 25 else "#dc2626")

    # KPI cards row
    kpi = (
        f'<table cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;margin:4px 0 16px 0;">'
        f'<tr>'
        f'<td style="padding:10px 24px 10px 0;">'
        f'  <p style="margin:0;font-size:10px;color:#6b7280;text-transform:uppercase;letter-spacing:.05em;">Active 12M Base</p>'
        f'  <p style="margin:2px 0 0 0;font-size:22px;font-weight:700;color:#111827;">{base_12m:,}</p>'
        f'  <p style="margin:2px 0 0 0;font-size:10px;color:#9ca3af;">had activity in last 12 months</p>'
        f'</td>'
        f'<td style="padding:10px 24px;">'
        f'  <p style="margin:0;font-size:10px;color:#6b7280;text-transform:uppercase;letter-spacing:.05em;">All Partners</p>'
        f'  <p style="margin:2px 0 0 0;font-size:22px;font-weight:700;color:#111827;">{all_p:,}</p>'
        f'  <p style="margin:2px 0 0 0;font-size:10px;color:#9ca3af;">from affiliate_partners table</p>'
        f'</td>'
        f'<td style="padding:10px 24px;">'
        f'  <p style="margin:0;font-size:10px;color:#6b7280;text-transform:uppercase;letter-spacing:.05em;">Active This Week</p>'
        f'  <p style="margin:2px 0 0 0;font-size:22px;font-weight:700;color:#111827;">{active_week:,}</p>'
        f'  <p style="margin:2px 0 0 0;font-size:10px;color:#9ca3af;">dep &ge; $100</p>'
        f'</td>'
        f'<td style="padding:10px 24px;">'
        f'  <p style="margin:0;font-size:10px;color:#6b7280;text-transform:uppercase;letter-spacing:.05em;">% Active</p>'
        f'  <p style="margin:2px 0 0 0;font-size:22px;font-weight:700;color:{pct_color};">{pct:.1f}%</p>'
        f'  <p style="margin:2px 0 0 0;font-size:10px;color:#9ca3af;">of 12m base</p>'
        f'</td>'
        f'</tr></table>'
    )

    # Breakdown table by group
    # Column order: All Partners, Active 12M Base, Active This Week, %Active, %Active to 12M Base
    th = (
        f'<th style="text-align:left;font-size:10px;color:#6b7280;'
        f'text-transform:uppercase;letter-spacing:.04em;white-space:nowrap;padding:6px 10px;'
        f'border-bottom:2px solid #e5e7eb;vertical-align:bottom;">Group</th>'
        f'<th class="r" style="font-size:10px;color:#9ca3af;text-transform:uppercase;'
        f'letter-spacing:.04em;white-space:nowrap;padding:6px 10px;'
        f'border-bottom:2px solid #e5e7eb;vertical-align:bottom;">All<br>Partners</th>'
        f'<th class="r" style="font-size:10px;color:#6b7280;text-transform:uppercase;'
        f'letter-spacing:.04em;white-space:nowrap;padding:6px 10px;'
        f'border-bottom:2px solid #e5e7eb;vertical-align:bottom;">Active<br>12M Base</th>'
        f'<th class="r" style="font-size:10px;color:#6b7280;text-transform:uppercase;'
        f'letter-spacing:.04em;white-space:nowrap;padding:6px 10px;'
        f'border-bottom:2px solid #e5e7eb;vertical-align:bottom;">Active<br>This Week</th>'
        f'<th class="r" style="font-size:10px;color:#6b7280;text-transform:uppercase;'
        f'letter-spacing:.04em;white-space:nowrap;padding:6px 10px;'
        f'border-bottom:2px solid #e5e7eb;vertical-align:bottom;">%Active<br>(of 12M)</th>'
        f'<th class="r" style="font-size:10px;color:#6b7280;text-transform:uppercase;'
        f'letter-spacing:.04em;white-space:nowrap;padding:6px 10px;'
        f'border-bottom:2px solid #e5e7eb;vertical-align:bottom;">%Active<br>(of All)</th>'
    )
    row_bg = {"Inbound": "#f0fdf4", "Acquisition": "#eff6ff", "Total": "#ffffff"}
    rows_html = ""
    for r in group_rows:
        gt       = r["group_type"]
        is_total = gt == "Total"
        pct_val      = r["pct_active"]
        pct_to_all   = r.get("pct_active_to_all", 0)
        pc_color     = "#15803d" if pct_val >= 50 else ("#d97706" if pct_val >= 25 else "#dc2626")
        pc_all_color = "#15803d" if pct_to_all >= 20 else ("#d97706" if pct_to_all >= 10 else "#dc2626")
        bg         = row_bg.get(gt, "#ffffff")
        top_border = "border-top:2px solid #d1d5db;" if is_total else ""
        fw         = "font-weight:700;" if is_total else ""
        rows_html += (
            f'<tr style="background:{bg};{top_border}">'
            f'<td style="padding:8px 10px;{fw}">{gt}</td>'
            f'<td class="r" style="padding:8px 10px;color:#9ca3af;">{r["all"]:,}</td>'
            f'<td class="r" style="padding:8px 10px;{fw}">{r["base_12m"]:,}</td>'
            f'<td class="r" style="padding:8px 10px;{fw}">{r["active"]:,}</td>'
            f'<td class="r" style="padding:8px 10px;">'
            f'  <span style="color:{pc_color};font-weight:700;">{pct_val:.1f}%</span>'
            f'</td>'
            f'<td class="r" style="padding:8px 10px;">'
            f'  <span style="color:{pc_all_color};font-weight:700;">{pct_to_all:.1f}%</span>'
            f'</td>'
            f'</tr>'
        )
    table = (
        f'<table cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;'
        f'margin-bottom:12px;font-size:12px;min-width:420px;">'
        f'<tr style="border-bottom:2px solid #e5e7eb;">{th}</tr>'
        f'{rows_html}'
        f'</table>'
    )

    chart_html = _build_activity_chart(weekly_trend)
    body = kpi + table + chart_html
    return _section("7. Partner Activity",
                    "Active = dep &ge; $100 this week. % of 12-month active base.",
                    body)


# ---------------------------------------------------------------------------
# Block 8 — Affiliate Totals (6 weeks)
# ---------------------------------------------------------------------------

def _build_block8(rows: list[dict]) -> str:
    if not rows:
        return _section("8. Affiliate Totals",
                        "Last 6 weeks | Inbound vs Acquisition, per Manager",
                        _empty())

    # Collect ordered weeks
    def _w_key(r):
        w = r.get("week_start")
        return w.isoformat() if hasattr(w, "isoformat") else str(w)[:10]

    def _wlabel(w_str: str) -> str:
        try:
            from datetime import date as _d
            d = _d.fromisoformat(w_str)
            return d.strftime("%d %b")
        except Exception:
            return w_str[:10]

    weeks_str = sorted(set(_w_key(r) for r in rows))
    week_labels = [_wlabel(w) for w in weeks_str]

    # Managers in order (Inbound first, then Acquisition, alphabetical within)
    managers_inbound = sorted({r["manager"] for r in rows if r.get("group_type") == "Inbound"})
    managers_acquis  = sorted({r["manager"] for r in rows if r.get("group_type") == "Acquisition"})
    managers_other   = sorted({r["manager"] for r in rows
                                if r.get("group_type") not in ("Inbound", "Acquisition")})

    # Index: (week, manager, group_type) -> row
    idx = {(_w_key(r), r.get("manager",""), r.get("group_type","")): r for r in rows}

    metrics = [
        ("Regs",       "regs",           False),
        ("FTD",        "ftd",            False),
        ("Conv%",      "conversion_pct", False),
        ("NP Dep Sum", "ftd_amount",     True),
        ("Deps",       "deposits_usd",   True),
    ]

    th_cells = (
        '<th>Type</th><th>Manager</th><th>Metric</th>'
        + "".join(f'<th class="r">{wl}</th>' for wl in week_labels)
    )

    def _manager_rows(manager_list: list[str], group_type: str, tr_cls: str) -> str:
        html = ""
        for manager in manager_list:
            for m_label, m_key, is_usd in metrics:
                cells = ""
                for w in weeks_str:
                    rd = idx.get((w, manager, group_type), {})
                    val = _v(rd.get(m_key))
                    if not rd:
                        cell_val = ""
                    elif m_key == "conversion_pct":
                        cell_val = _fmt_pct(val)
                    elif is_usd:
                        cell_val = _fmt_usd(val)
                    else:
                        cell_val = _fmt_int(val)
                    cells += f'<td class="r">{cell_val}</td>'
                html += (
                    f'<tr class="{tr_cls}">'
                    f'<td class="gray" style="white-space:nowrap;">{group_type if m_label == "Regs" else ""}</td>'
                    f'<td class="mn" style="white-space:nowrap;">{manager if m_label == "Regs" else ""}</td>'
                    f'<td class="gray">{m_label}</td>'
                    f'{cells}'
                    f'</tr>'
                )
        return html

    rows_html = ""
    rows_html += _manager_rows(managers_inbound, "Inbound",     "inbound")
    rows_html += _manager_rows(managers_acquis,  "Acquisition", "acquis")
    rows_html += _manager_rows(managers_other,   "Other",       "")

    body = f'<table class="dt"><tr>{th_cells}</tr>{rows_html}</table>'
    return _section("8. Affiliate Totals",
                    "Last 6 weeks | Inbound vs Acquisition, per Manager",
                    body)


# ---------------------------------------------------------------------------
# Block 9 — Month Comparison
# ---------------------------------------------------------------------------

def _build_block9(data: dict, periods: dict) -> str:
    if not data:
        return _section("9. Month Comparison", "Last 2 months + MTD", _empty())

    p2s = periods["prev2_month_start"]
    p1s = periods["prev_month_start"]
    cms = periods["current_month_start"]
    days_elapsed  = periods["days_elapsed"]
    days_in_month = periods["days_in_month"]

    def _mlabel(d: date) -> str:
        return f"{MONTH_NAMES[d.month]} {d.year}"

    col_prev2    = _mlabel(p2s)
    col_prev1    = _mlabel(p1s)
    col_mtd      = f"MTD {_mlabel(cms)} ({days_elapsed}d)"
    col_proj     = f"Prediction {_mlabel(cms)}"
    col_vs_prev1 = f"vs {_mlabel(p1s)}"

    th = (
        f'<th>Group</th><th>Metric</th>'
        f'<th class="r">{col_prev2}</th>'
        f'<th class="r">{col_prev1}</th>'
        f'<th class="r">{col_mtd}</th>'
        f'<th class="r">{col_proj}</th>'
        f'<th class="r">{col_vs_prev1}</th>'
    )

    metrics = [
        ("FTD",        "ftd",          False),
        ("NP Dep Sum", "ftd_amount",   True),
        ("Deposits",   "deposits_usd", True),
    ]

    def _pct_delta(v: float | None) -> str:
        if v is None:
            return '<span style="color:#9ca3af;">—</span>'
        color = "#16a34a" if v >= 0 else "#dc2626"
        sign  = "+" if v > 0 else ""
        return f'<span style="color:{color};font-weight:600;">{sign}{v:.1f}%</span>'

    rows_html = ""
    for group in ("Inbound", "Acquisition", "Total"):
        gdata = data.get(group, {})
        is_total = group == "Total"
        tr_cls = "inbound" if group == "Inbound" else ("acquis" if group == "Acquisition" else "")
        total_style = ' style="border-top:2px solid #1e3a5f;font-weight:700;background:#fef9c3;color:#1e3a5f;"' if is_total else ""

        for m_label, m_key, is_usd in metrics:
            mdata = gdata.get(m_key, {})
            p2_val   = _v(mdata.get("prev2"))
            p1_val   = _v(mdata.get("prev1"))
            mtd_val  = _v(mdata.get("mtd"))
            proj_val = _v(mdata.get("projected"))
            vs_p1    = mdata.get("vs_prev1")

            def _cell(v):
                return _fmt_usd(v) if is_usd else _fmt_int(v)

            rows_html += (
                f'<tr class="{tr_cls}"{total_style}>'
                f'<td class="mn">{group}</td>'
                f'<td class="gray">{m_label}</td>'
                f'<td class="r gray">{_cell(p2_val)}</td>'
                f'<td class="r">{_cell(p1_val)}</td>'
                f'<td class="r bold">{_cell(mtd_val)}</td>'
                f'<td class="r">{_cell(proj_val)}</td>'
                f'<td class="r">{_pct_delta(vs_p1)}</td>'
                f'</tr>'
            )

    note = (
        f'<p style="font-size:10px;color:#9ca3af;margin:6px 0 0 0;">'
        f'Prediction = MTD / {days_elapsed} days &times; {days_in_month} days in month. '
        f'vs {_mlabel(p1s)} = (Prediction &minus; {_mlabel(p1s)}) / {_mlabel(p1s)}.</p>'
    )
    body = f'<table class="dt"><tr>{th}</tr>{rows_html}</table>{note}'
    subtitle = f"{col_prev2} | {col_prev1} | MTD {_mlabel(cms)} ({days_elapsed}d)"
    return _section("9. Month Comparison", subtitle, body)


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_weekly_report(data: dict) -> str:
    """Return html_string with all charts embedded as base64."""
    report_date: date = data["report_date"]
    periods: dict     = data["periods"]
    manager_label: str = data.get("manager_label", "All Managers")
    day_name = DAY_NAMES[report_date.weekday()]
    w4_s = periods["week4_start"].strftime("%d %b")
    w4_e = periods["period_end"].strftime("%d %b %Y")
    geo_label = "All countries"

    block7_html = _build_block7(data.get("block7", {}))
    monthly_html = _build_monthly_chart(data.get("chart_monthly", []), manager_label)

    sections = "\n".join([
        _build_block1(data.get("block1", []), data.get("block1_top_dep", []), periods=periods),
        _build_block2(data.get("block2", [])),
        _build_block3(data.get("block3", [])),
        _build_block4(data.get("block4", [])),
        _build_block5(data.get("block5", []), data.get("block5b", [])),
        _build_block6(data.get("block6_no_ftd", []), data.get("block6_low_conv", [])),
        block7_html,
        _build_block8(data.get("block8", [])),
        _build_block9(data.get("block9", {}), periods),
    ])

    monthly_section = ""
    if monthly_html:
        monthly_section = _section(
            "Monthly Deposits Trend",
            f"Last 12 months | Inbound vs Acquisition | {manager_label}",
            monthly_html,
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Affiliate Report {manager_label} {report_date.strftime('%d %b %Y')}</title>
    {STYLES}
</head>
<body style="margin:0;padding:20px 0;background:#f1f5f9;">
<div class="report-container" style="max-width:1000px;margin:0 auto;background:#fff;
     border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.1);">

    <div class="header">
        <h1>Affiliate Report &mdash; {manager_label}</h1>
        <p class="sub">
            Period: {w4_s} &ndash; {w4_e} ({day_name}) &bull;
            GEO: {geo_label} &bull;
            Data: PostgreSQL / USD
        </p>
    </div>

    {sections}

    {monthly_section}

    <!-- Legend -->
    <div style="padding:12px 24px 6px;border-top:1px solid #e5e7eb;">
        <p style="font-size:10px;font-weight:600;color:#6b7280;text-transform:uppercase;margin:0 0 4px 0;">Legend</p>
        <table cellpadding="0" cellspacing="0" border="0" style="font-size:10px;color:#6b7280;line-height:1.7;">
            <tr><td style="padding-right:10px;white-space:nowrap;">4w</td><td>Last 28 days (rolling 4-week window)</td></tr>
            <tr><td style="padding-right:10px;white-space:nowrap;">Ref period</td><td>90-day reference window before current 4 weeks, normalized to 28 days</td></tr>
            <tr><td style="padding-right:10px;white-space:nowrap;">FTD</td><td>First Time Depositor</td></tr>
            <tr><td style="padding-right:10px;white-space:nowrap;">NP Dep Sum</td><td>Sum of ALL deposits from players who made their first deposit in that period (LTV Day-1 proxy)</td></tr>
            <tr><td style="padding-right:10px;white-space:nowrap;">D+N checks</td><td>180-day cohort: % of registrations who made their first deposit within N days of registration</td></tr>
            <tr><td style="padding-right:10px;white-space:nowrap;">Plan to Date</td><td>MTD fact / days elapsed * days in month</td></tr>
        </table>
    </div>

    <div class="footer">
        BetAndYou Analytics &bull; Affiliate Weekly Report &bull;
        Generated {report_date.strftime('%d.%m.%Y')}
    </div>
</div>
</body>
</html>"""

    return html


def build_weekly_subject(data: dict) -> str:
    report_date: date = data["report_date"]
    periods: dict     = data["periods"]
    manager_label: str = data.get("manager_label", "All Managers")
    w4_s = periods["week4_start"].strftime("%d %b")
    w4_e = periods["period_end"].strftime("%d %b")
    return f"Affiliate Report {manager_label} {w4_s} - {w4_e} B&U"
