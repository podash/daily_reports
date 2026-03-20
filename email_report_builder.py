"""
Build an HTML email report from Google Sheets data (EUR).

Produces a styled, responsive HTML document suitable for email clients.
Tables, color-coded deltas, progress bars for MTD vs Plan.
"""

from datetime import date
from config import TOP_COUNTRIES_LIMIT

DAY_NAMES = {
    0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu",
    4: "Fri", 5: "Sat", 6: "Sun",
}

# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt_eur(val: float) -> str:
    if val < 0:
        return f"&minus;&euro;{abs(val):,.0f}"
    return f"&euro;{val:,.0f}"


def _fmt_int(val: int) -> str:
    return f"{val:,}"


def _fmt_pct(val: float) -> str:
    return f"{val:.1f}%"


def _pct_change_safe(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return ((current - previous) / abs(previous)) * 100


def _delta_html(val: float | None, suffix: str = "%") -> str:
    """Return a colored delta string for HTML. Red for negative, black for positive."""
    if val is None:
        return '<span style="color:#888;">n/a</span>'
    sign = "+" if val >= 0 else ""
    color = "#1f2937" if val >= 0 else "#dc2626"
    if suffix == "pp":
        text = f"{sign}{val:.1f}pp"
    else:
        text = f"{sign}{val:.1f}%"
    return f'<span style="color:{color};font-weight:600;">{text}</span>'


def _delta_short_html(val: float | None) -> str:
    if val is None:
        return '<span style="color:#888;">n/a</span>'
    sign = "+" if val >= 0 else ""
    color = "#1f2937" if val >= 0 else "#dc2626"
    return f'<span style="color:{color};font-weight:600;">{sign}{val:.0f}%</span>'



# ---------------------------------------------------------------------------
# CSS (inline-friendly for email clients)
# ---------------------------------------------------------------------------

STYLES = """
<style>
    body, table, td, th, p, div {
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
    }
    .report-container {
        max-width: 960px;
        margin: 0 auto;
        background: #ffffff;
    }
    .header {
        background: linear-gradient(135deg, #1e3a5f 0%, #2563eb 100%);
        color: #ffffff;
        padding: 24px 28px;
        border-radius: 8px 8px 0 0;
    }
    .header h1 {
        margin: 0;
        font-size: 20px;
        font-weight: 700;
        letter-spacing: 0.5px;
    }
    .header .subtitle {
        margin: 4px 0 0 0;
        font-size: 13px;
        color: #93c5fd;
        font-weight: 400;
    }
    .section {
        padding: 0 28px;
    }
    .section-title {
        font-size: 13px;
        font-weight: 700;
        color: #1e3a5f;
        text-transform: uppercase;
        letter-spacing: 1px;
        padding: 18px 0 8px 0;
        margin: 0;
        border-bottom: 2px solid #2563eb;
    }
    .data-table {
        width: 100%;
        border-collapse: collapse;
        margin: 0;
    }
    .data-table th {
        text-align: left;
        font-size: 11px;
        font-weight: 600;
        color: #6b7280;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        padding: 8px 10px;
        border-bottom: 1px solid #e5e7eb;
    }
    .data-table td {
        padding: 7px 10px;
        font-size: 13px;
        color: #1f2937;
        border-bottom: 1px solid #f3f4f6;
    }
    .data-table tr:last-child td {
        border-bottom: none;
    }
    .data-table .metric-name {
        font-weight: 500;
        color: #374151;
    }
    .data-table .metric-value {
        font-weight: 700;
        color: #111827;
        font-variant-numeric: tabular-nums;
    }
    .country-table th {
        text-align: left;
        font-size: 11px;
        font-weight: 600;
        color: #6b7280;
        text-transform: uppercase;
        padding: 8px 10px;
        border-bottom: 1px solid #e5e7eb;
    }
    .country-table td {
        padding: 6px 10px;
        font-size: 13px;
        color: #1f2937;
        border-bottom: 1px solid #f3f4f6;
    }
    .alert-box {
        margin: 16px 28px;
        padding: 12px 16px;
        border-radius: 6px;
        font-size: 13px;
    }
    .alert-box.warning {
        background: #fef3c7;
        border-left: 4px solid #f59e0b;
        color: #92400e;
    }
    .alert-box.success {
        background: #d1fae5;
        border-left: 4px solid #10b981;
        color: #065f46;
    }
    .footer {
        padding: 16px 28px;
        text-align: center;
        font-size: 11px;
        color: #9ca3af;
        border-top: 1px solid #e5e7eb;
    }
    .kpi-row {
        display: flex;
        gap: 12px;
        padding: 12px 28px;
    }
    .kpi-card {
        flex: 1;
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 14px 16px;
        text-align: center;
    }
    .kpi-card .kpi-label {
        font-size: 11px;
        color: #64748b;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin: 0 0 4px 0;
    }
    .kpi-card .kpi-value {
        font-size: 20px;
        font-weight: 700;
        color: #0f172a;
        margin: 0;
    }
    .kpi-card .kpi-delta {
        font-size: 12px;
        margin: 2px 0 0 0;
    }
</style>
"""


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _build_kpi_cards(d: dict, plan: dict, prev_month: dict) -> str:
    """Top-level KPI summary cards: today row + plan row."""

    def _mom_html(plan_val, prev_val):
        if not plan_val or not prev_val or prev_val == 0:
            return ""
        pct = ((plan_val - prev_val) / abs(prev_val)) * 100
        color = "#1f2937" if pct >= 0 else "#dc2626"
        sign = "+" if pct >= 0 else ""
        return f'<span style="color:{color};font-weight:600;">{sign}{pct:.1f}%</span>'

    def _mom_pp_html(current, prev):
        if not current and not prev:
            return ""
        diff = current - prev
        color = "#1f2937" if diff >= 0 else "#dc2626"
        sign = "+" if diff >= 0 else ""
        return f'<span style="color:{color};font-weight:600;">{sign}{diff:.1f}pp</span>'

    today_cards = [
        ("Deposits", _fmt_eur(d.get("deposits", 0)),
         _delta_html(d.get("deposits_dod")), _delta_html(d.get("deposits_wow"))),
        ("GGR Total", _fmt_eur(d.get("total_ggr", 0)),
         _delta_html(d.get("total_ggr_dod")), _delta_html(d.get("total_ggr_wow"))),
        ("FTD", _fmt_int(d.get("ftd", 0)),
         _delta_html(d.get("ftd_dod")), _delta_html(d.get("ftd_wow"))),
        ("Conversion", _fmt_pct(d.get("conversion", 0)),
         _delta_html(d.get("conversion_dod"), suffix="pp"), _delta_html(d.get("conversion_wow"), suffix="pp")),
    ]

    plan_regs = plan.get("registrations_plan", 0)
    plan_ftd = plan.get("ftd_plan", 0)
    plan_conv = (plan_ftd / plan_regs * 100) if plan_regs else 0
    prev_regs = prev_month.get("registrations", 0)
    prev_ftd = prev_month.get("ftd", 0)
    prev_conv = (prev_ftd / prev_regs * 100) if prev_regs else 0

    plan_cards = [
        ("Deposits Plan", _fmt_eur(plan.get("deposits_plan", 0)),
         _mom_html(plan.get("deposits_plan"), prev_month.get("deposits"))),
        ("GGR Plan", _fmt_eur(plan.get("total_ggr_plan", 0)),
         _mom_html(plan.get("total_ggr_plan"), prev_month.get("total_ggr"))),
        ("FTD Plan", _fmt_int(plan_ftd),
         _mom_html(plan_ftd, prev_ftd)),
        ("Conversion", _fmt_pct(plan_conv),
         _mom_pp_html(plan_conv, prev_conv)),
    ]

    def _render_card(label, value, deltas_html):
        return (
            f'<td style="width:25%;padding:0 6px;">'
            f'<table cellpadding="0" cellspacing="0" border="0" width="100%" '
            f'style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;">'
            f'<tr><td style="padding:14px 16px;text-align:center;">'
            f'<p style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:0.5px;margin:0 0 4px 0;">{label}</p>'
            f'<p style="font-size:20px;font-weight:700;color:#0f172a;margin:0;">{value}</p>'
            f'{deltas_html}'
            f'</td></tr></table>'
            f'</td>'
        )

    html = '<table cellpadding="0" cellspacing="0" border="0" width="100%" style="padding:6px 28px;">'
    html += '<tr>'
    for label, value, dod, wow in today_cards:
        deltas = (
            f'<p style="font-size:12px;margin:2px 0 0 0;">DoD: {dod}</p>'
            f'<p style="font-size:12px;margin:1px 0 0 0;">WoW: {wow}</p>'
        )
        html += _render_card(label, value, deltas)
    html += '</tr></table>'

    html += '<table cellpadding="0" cellspacing="0" border="0" width="100%" style="padding:6px 28px;">'
    html += '<tr>'
    for label, value, mom in plan_cards:
        deltas = f'<p style="font-size:12px;margin:2px 0 0 0;">MoM: {mom}</p>' if mom else ''
        html += _render_card(label, value, deltas)
    html += '</tr></table>'

    return html


def _build_metrics_table(title: str, rows: list[tuple]) -> str:
    """
    Build a section with a data table.
    rows: list of (metric_name, value, mtd_html, plan_html, dod_html, wow_html, avg7d_html)
    """
    html = f'<div class="section"><p class="section-title">{title}</p>'
    html += '<table class="data-table" cellpadding="0" cellspacing="0" border="0" width="100%">'
    html += (
        '<tr>'
        '<th style="width:16%;">Metric</th>'
        '<th style="width:14%;">Today</th>'
        '<th style="width:14%;">MTD</th>'
        '<th style="width:14%;">Plan</th>'
        '<th style="width:14%;">DoD</th>'
        '<th style="width:14%;">WoW</th>'
        '<th style="width:14%;">vs 7d Avg</th>'
        '</tr>'
    )
    for name, value, mtd, plan, dod, wow, avg7d in rows:
        is_subheader = value == "" and mtd == "" and plan == "" and dod == "" and wow == "" and avg7d == ""
        if is_subheader:
            html += (
                f'<tr>'
                f'<td colspan="7" style="font-weight:700;font-size:12px;color:#374151;'
                f'padding:10px 12px 4px;border-bottom:1px solid #e5e7eb;'
                f'background:#f9fafb;">{name}</td>'
                f'</tr>'
            )
        else:
            is_total = name.startswith("Total ")
            bold = "font-weight:700;" if is_total else ""
            bg = "background:#f0f4ff;" if is_total else ""
            html += (
                f'<tr style="{bg}">'
                f'<td class="metric-name" style="{bold}">{name}</td>'
                f'<td class="metric-value" style="{bold}">{value}</td>'
                f'<td style="font-variant-numeric:tabular-nums;{bold}">{mtd}</td>'
                f'<td style="color:#6b7280;{bold}">{plan}</td>'
                f'<td style="{bold}">{dod}</td>'
                f'<td style="{bold}">{wow}</td>'
                f'<td style="{bold}">{avg7d}</td>'
                f'</tr>'
            )
    html += '</table></div>'
    return html


def _build_countries_section(data: dict) -> str:
    """Combined table: Top countries with today, DoD, MTD, Plan, vs prev 3 months."""
    country_data = data.get("country_deposits", {})
    if not country_data or not country_data.get("today"):
        return ""

    top_today = country_data["today"][:TOP_COUNTRIES_LIMIT]
    yesterday_map = {c["country"]: c["deposits"] for c in country_data.get("yesterday", [])}
    mtd_map = {c["country"]: c["deposits"] for c in country_data.get("mtd", [])}
    plan_map = {c["country"]: c["deposits_plan"] for c in country_data.get("plan", [])}
    prev_months = country_data.get("prev_months", {})
    labels = country_data.get("prev_month_labels", {"prev1": "Prev1", "prev2": "Prev2", "prev3": "Prev3"})

    p1_map = {c["country"]: c["deposits"] for c in prev_months.get("prev1", [])}
    p2_map = {c["country"]: c["deposits"] for c in prev_months.get("prev2", [])}
    p3_map = {c["country"]: c["deposits"] for c in prev_months.get("prev3", [])}

    na = '<span style="color:#9ca3af;">n/a</span>'

    html = '<div class="section">'
    html += f'<p class="section-title">Top {TOP_COUNTRIES_LIMIT} Countries (Deposits EUR)</p>'
    html += '<table class="data-table country-table" cellpadding="0" cellspacing="0" border="0" width="100%">'
    html += (
        '<tr>'
        '<th style="width:4%;">#</th>'
        '<th style="width:14%;">Country</th>'
        '<th style="width:13%;">Today</th>'
        '<th style="width:9%;">DoD</th>'
        '<th style="width:13%;">MTD</th>'
        '<th style="width:13%;">Plan</th>'
        f'<th style="width:9%;">vs {labels["prev1"]}</th>'
        f'<th style="width:9%;">vs {labels["prev2"]}</th>'
        f'<th style="width:9%;">vs {labels["prev3"]}</th>'
        '</tr>'
    )

    for i, item in enumerate(top_today, 1):
        country = item["country"]
        today_val = item["deposits"]
        prev_val = yesterday_map.get(country, 0)
        dod = _pct_change_safe(today_val, prev_val)
        mtd_val = mtd_map.get(country, 0)
        plan_val = plan_map.get(country, 0)

        p1_val = p1_map.get(country, 0)
        p2_val = p2_map.get(country, 0)
        p3_val = p3_map.get(country, 0)

        vs_p1 = _delta_short_html(_pct_change_safe(plan_val, p1_val)) if p1_val > 0 and plan_val > 0 else na
        vs_p2 = _delta_short_html(_pct_change_safe(plan_val, p2_val)) if p2_val > 0 and plan_val > 0 else na
        vs_p3 = _delta_short_html(_pct_change_safe(plan_val, p3_val)) if p3_val > 0 and plan_val > 0 else na

        plan_cell = _fmt_eur(plan_val) if plan_val > 0 else na

        html += (
            f'<tr>'
            f'<td style="color:#9ca3af;font-weight:600;">{i}</td>'
            f'<td class="metric-name">{country}</td>'
            f'<td class="metric-value">{_fmt_eur(today_val)}</td>'
            f'<td>{_delta_short_html(dod)}</td>'
            f'<td style="font-variant-numeric:tabular-nums;">{_fmt_eur(mtd_val)}</td>'
            f'<td style="color:#6b7280;font-variant-numeric:tabular-nums;">{plan_cell}</td>'
            f'<td>{vs_p1}</td>'
            f'<td>{vs_p2}</td>'
            f'<td>{vs_p3}</td>'
            f'</tr>'
        )

    html += '</table></div>'
    return html


def _build_focus_markets_section(data: dict) -> str:
    """Focus markets: transposed table (countries as columns, metrics as rows)."""
    fm = data.get("focus_markets", {})
    if not fm:
        return ""

    region_order = ["Europe", "Asia", "LatAm", "Arab"]
    na = '<span style="color:#9ca3af;">&mdash;</span>'
    fm_labels = fm.get("_labels", {})
    label_turn_prev = fm_labels.get("turn_prev", "Turn Prev")
    label_vs_prev = fm_labels.get("vs_prev", "vs Prev")
    label_turn_ly = fm_labels.get("turn_ly", "Turn LY")
    label_vs_ly = fm_labels.get("vs_ly", "vs LY")

    html = '<div class="section">'
    html += '<p class="section-title">Focus Markets</p>'

    for region in region_order:
        rd = fm.get(region)
        if not rd:
            continue
        countries = rd["countries"]
        cd_map = rd["country_data"]

        totals = {"regs_mtd": 0, "ftd_mtd": 0, "deposits_mtd": 0,
                  "turnover_mtd": 0, "turnover_plan": 0, "deps_plan": 0,
                  "fact_prev": 0, "fact_ly": 0}
        for c in countries:
            cd = cd_map.get(c, {})
            for k in totals:
                totals[k] += cd.get(k, 0)

        col_w = max(8, int(70 / (len(countries) + 1)))
        th_style = f'style="width:{col_w}%;"'

        html += (
            f'<p style="font-size:13px;font-weight:700;color:#334155;margin:16px 0 6px 0;'
            f'border-left:3px solid #3b82f6;padding:2px 8px;">{region}</p>'
        )
        html += '<table class="data-table" cellpadding="0" cellspacing="0" border="0" width="100%">'

        html += '<tr><th style="width:18%;"></th>'
        for c in countries:
            html += f'<th {th_style}>{c}</th>'
        html += f'<th {th_style} style="font-weight:700;">Total</th></tr>'

        metrics = [
            ("Regs MTD", "regs_mtd", "int", "data"),
            ("FTD MTD", "ftd_mtd", "int", "data"),
            ("Deps MTD", "deposits_mtd", "eur", "data"),
            ("Deps Plan", "deps_plan", "eur", "plan"),
            ("Turn MTD", "turnover_mtd", "eur", "data"),
            ("Turn Plan", "turnover_plan", "eur", "plan"),
            (label_turn_prev, "fact_prev", "eur", "hist"),
            (label_vs_prev, "vs_prev_pct", "pct", "hist"),
            (label_turn_ly, "fact_ly", "eur", "hist"),
            (label_vs_ly, "vs_ly_pct", "pct", "hist"),
        ]

        row_styles = {
            "data": "",
            "plan": "background:#f3f4f6;color:#6b7280;",
            "hist": "background:#f9fafb;color:#6b7280;",
        }

        for label, key, fmt, row_type in metrics:
            rs = row_styles.get(row_type, "")
            html += f'<tr style="{rs}"><td class="metric-name" style="font-weight:600;">{label}</td>'
            for c in countries:
                cd = cd_map.get(c, {})
                val = cd.get(key, 0)
                if fmt == "eur":
                    cell = _fmt_eur(val) if val else na
                elif fmt == "int":
                    cell = f'{val:,}' if val else '0'
                elif fmt == "pct":
                    if val is not None:
                        color = "#1f2937" if val >= 0 else "#dc2626"
                        sign = "+" if val >= 0 else ""
                        cell = f'<span style="color:{color};">{sign}{val:.1f}%</span>'
                    else:
                        cell = na
                else:
                    cell = str(val)
                html += f'<td style="text-align:center;font-weight:400;font-size:12px;padding:6px 4px;">{cell}</td>'

            total_val = totals.get(key, 0)
            if fmt == "eur":
                total_cell = _fmt_eur(total_val) if total_val else na
            elif fmt == "int":
                total_cell = f'{total_val:,}'
            elif fmt == "pct":
                total_cell = na
            else:
                total_cell = str(total_val)
            html += f'<td style="text-align:center;font-weight:700;font-size:12px;padding:6px 4px;">{total_cell}</td>'
            html += '</tr>'

        html += '</table>'

    html += '</div>'
    return html


def _build_country_traffic_alerts(data: dict) -> str:
    """Country-level alerts: sharp changes in regs/FTD/conversion vs prev month avg."""
    ct_alerts = data.get("country_traffic_alerts", [])
    if not ct_alerts:
        return ""

    html = '<div class="section">'
    html += '<p class="section-title">Country Traffic Alerts (vs Prev Month Avg)</p>'
    html += '<table class="data-table" cellpadding="0" cellspacing="0" border="0" width="100%">'
    html += (
        '<tr>'
        '<th style="width:18%;">Country</th>'
        '<th style="width:12%;">Regs</th>'
        '<th style="width:14%;">vs Avg</th>'
        '<th style="width:10%;">FTD</th>'
        '<th style="width:14%;">vs Avg</th>'
        '<th style="width:12%;">Conv%</th>'
        '<th style="width:20%;">vs Avg</th>'
        '</tr>'
    )

    for item in ct_alerts:
        regs_today = item["regs_today"]
        ftd_today = item["ftd_today"]
        conv_today = item["conv_today"]
        regs_avg = item["regs_avg"]
        ftd_avg = item["ftd_avg"]
        conv_avg = item["conv_avg"]

        regs_pct = _pct_change_safe(regs_today, regs_avg)
        ftd_pct = _pct_change_safe(ftd_today, ftd_avg)
        conv_diff = conv_today - conv_avg

        html += (
            f'<tr>'
            f'<td class="metric-name">{item["country"]}</td>'
            f'<td class="metric-value">{regs_today:,}</td>'
            f'<td>{_delta_short_html(regs_pct)} <span style="font-size:10px;color:#9ca3af;">(avg {regs_avg:.0f})</span></td>'
            f'<td class="metric-value">{ftd_today:,}</td>'
            f'<td>{_delta_short_html(ftd_pct)} <span style="font-size:10px;color:#9ca3af;">(avg {ftd_avg:.0f})</span></td>'
            f'<td class="metric-value">{conv_today:.1f}%</td>'
            f'<td>{_delta_pp_html(conv_diff)} <span style="font-size:10px;color:#9ca3af;">(avg {conv_avg:.1f}%)</span></td>'
            f'</tr>'
        )

    html += '</table></div>'
    return html


def _delta_pp_html(val: float) -> str:
    """Format percentage point change with color. Red for negative, black for positive."""
    if abs(val) < 0.1:
        return '<span style="color:#6b7280;">0.0pp</span>'
    color = "#1f2937" if val > 0 else "#dc2626"
    sign = "+" if val > 0 else ""
    return f'<span style="color:{color};font-weight:600;">{sign}{val:.1f}pp</span>'


def _build_alerts_section(alerts: list[str]) -> str:
    if not alerts:
        return (
            '<div class="alert-box success">'
            'No anomalies detected.'
            '</div>'
        )

    html = ""
    for a in alerts:
        html += f'<div class="alert-box warning">{a}</div>'
    return html


# ---------------------------------------------------------------------------
# Top 5 Players section
# ---------------------------------------------------------------------------

def _build_top_players(top: dict) -> str:
    if not top:
        return ""

    casino = top.get("casino", [])
    sport  = top.get("sport", [])
    deps   = top.get("deposits", [])
    wds    = top.get("withdrawals", [])

    def _fmt_usd(v: float) -> str:
        return f"${v:,.0f}"

    th = (
        'style="font-size:11px;font-weight:700;color:#374151;text-transform:uppercase;'
        'padding:4px 8px;border-bottom:2px solid #e5e7eb;text-align:left;white-space:nowrap;'
        'background:#f9fafb;"'
    )
    th_r = (
        'style="font-size:11px;font-weight:700;color:#374151;text-transform:uppercase;'
        'padding:4px 8px;border-bottom:2px solid #e5e7eb;text-align:right;white-space:nowrap;'
        'background:#f9fafb;"'
    )

    def _col_html(title: str, rows: list[dict]) -> str:
        # Title spanning header
        out = (
            f'<tr><th colspan="3" {th} style="font-size:11px;font-weight:700;color:#374151;'
            f'text-transform:uppercase;padding:4px 8px;border-bottom:2px solid #e5e7eb;'
            f'white-space:nowrap;background:#f9fafb;">{title}</th></tr>'
            f'<tr>'
            f'<th {th}>#</th>'
            f'<th {th}>Player ID</th>'
            f'<th {th_r}>Amt, USD</th>'
            f'</tr>'
        )
        if not rows:
            out += (
                '<tr><td colspan="3" style="padding:8px;font-size:12px;color:#9ca3af;'
                'font-style:italic;">No data</td></tr>'
            )
        else:
            for i, r in enumerate(rows):
                bg = "background:#f9fafb;" if i % 2 == 0 else ""
                out += (
                    f'<tr style="{bg}">'
                    f'<td style="padding:5px 8px;font-size:12px;color:#6b7280;">{i+1}</td>'
                    f'<td style="padding:5px 8px;font-size:12px;color:#374151;">{r["player_id"]}</td>'
                    f'<td style="padding:5px 8px;font-size:12px;font-weight:600;color:#111827;text-align:right;">'
                    f'{_fmt_usd(r["amount_usd"])}</td>'
                    f'</tr>'
                )
        return out

    # Build one outer table with 4 sub-table columns separated by spacer cells
    sep = '<td style="width:16px;"></td>'

    def _wrap(title: str, rows: list[dict]) -> str:
        inner = (
            f'<table cellpadding="0" cellspacing="0" border="0" '
            f'style="border-collapse:collapse;min-width:200px;width:100%;">'
            f'<tbody>'
            f'{_col_html(title, rows)}'
            f'</tbody></table>'
        )
        return f'<td style="vertical-align:top;padding:0;">{inner}</td>'

    row_html = (
        _wrap("Top 5 Casino Winnings", casino)
        + sep
        + _wrap("Top 5 Sport Winnings", sport)
        + sep
        + _wrap("Top 5 Deposits", deps)
        + sep
        + _wrap("Top 5 Withdrawals", wds)
    )

    return (
        '<div style="padding:16px 28px;">'
        '<p style="font-size:12px;font-weight:700;color:#374151;text-transform:uppercase;'
        'letter-spacing:.05em;margin:0 0 12px 0;">Top 5 Players</p>'
        '<div style="overflow-x:auto;">'
        '<table cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;">'
        f'<tr>{row_html}</tr>'
        '</table>'
        '</div>'
        '</div>'
    )


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_email_report(data: dict) -> str:
    """
    Build a complete HTML email report from Sheets data.
    Returns a full HTML document string.
    """
    target: date = data["target_date"]
    d = data["data"]
    alerts = data["alerts"]
    plan = data.get("plan", {})
    sport_share = data.get("sport_share", 0)
    casino_share = 100 - sport_share

    day_name = DAY_NAMES[target.weekday()]

    # Plan & MTD helpers
    _no = '<span style="color:#d1d5db;">&mdash;</span>'
    def _plan(val):
        return _fmt_eur(val) if val else _no
    mtd = data.get("mtd", {})
    def _mtd_eur(key):
        v = mtd.get(key)
        return _fmt_eur(v) if v else _no
    def _mtd_int(key):
        v = mtd.get(key)
        return _fmt_int(v) if v else _no

    # Revenue rows: (name, value, mtd, plan, dod, wow, 7d)
    revenue_rows = [
        ("Deposits", _fmt_eur(d.get("deposits", 0)), _mtd_eur("deposits"), _plan(plan.get("deposits_plan")),
         _delta_html(d.get("deposits_dod")), _delta_html(d.get("deposits_wow")), _delta_html(d.get("deposits_7d"))),
        ("Withdrawals", _fmt_eur(d.get("withdrawals", 0)), _mtd_eur("withdrawals"), _plan(plan.get("withdrawals_plan")),
         _delta_html(d.get("withdrawals_dod")), _delta_html(d.get("withdrawals_wow")), _delta_html(d.get("withdrawals_7d"))),
        ("Cash Flow", _fmt_eur(d.get("cash_flow", 0)), _mtd_eur("cash_flow"), _plan(plan.get("cash_flow_plan")),
         _delta_html(d.get("cash_flow_dod")), _delta_html(d.get("cash_flow_wow")), _delta_html(d.get("cash_flow_7d"))),
        ("GGR Total", _fmt_eur(d.get("total_ggr", 0)), _mtd_eur("total_ggr"), _plan(plan.get("total_ggr_plan")),
         _delta_html(d.get("total_ggr_dod")), _delta_html(d.get("total_ggr_wow")), _delta_html(d.get("total_ggr_7d"))),
        ("Promo", _fmt_eur(d.get("promo", 0)), _mtd_eur("promo"), _plan(plan.get("promo_plan")),
         _delta_html(d.get("promo_dod")), _delta_html(d.get("promo_wow")), _delta_html(d.get("promo_7d"))),
        ("GGR-Promo", _fmt_eur(d.get("ggr_net_promo", 0)), _mtd_eur("ggr_net_promo"), _plan(plan.get("ggr_net_promo_plan")),
         _delta_html(d.get("ggr_net_promo_dod")), _delta_html(d.get("ggr_net_promo_wow")), _delta_html(d.get("ggr_net_promo_7d"))),
    ]

    # Traffic rows
    regs_plan = plan.get("registrations_plan")
    ftd_plan = plan.get("ftd_plan")
    mtd_regs = mtd.get("registrations", 0)
    mtd_ftd = mtd.get("ftd", 0)
    mtd_conv = (mtd_ftd / mtd_regs * 100) if mtd_regs > 0 else 0

    ss = data.get("somalia_split", {})

    traffic_rows = [
        ("Registrations", _fmt_int(d.get("registrations", 0)), _mtd_int("registrations"),
         _fmt_int(regs_plan) if regs_plan else _no,
         _delta_html(d.get("registrations_dod")), _delta_html(d.get("registrations_wow")), _delta_html(d.get("registrations_7d"))),
        ("FTD", _fmt_int(d.get("ftd", 0)), _mtd_int("ftd"),
         _fmt_int(ftd_plan) if ftd_plan else _no,
         _delta_html(d.get("ftd_dod")), _delta_html(d.get("ftd_wow")), _delta_html(d.get("ftd_7d"))),
        ("Conversion", _fmt_pct(d.get("conversion", 0)), _fmt_pct(mtd_conv), _no,
         _delta_html(d.get("conversion_dod"), suffix="pp"),
         _delta_html(d.get("conversion_wow"), suffix="pp"),
         _delta_html(d.get("conversion_7d"), suffix="pp")),
    ]

    if ss:
        excl_mtd_regs = ss.get("excl_somalia_regs_mtd", 0)
        excl_mtd_ftd = ss.get("excl_somalia_ftd_mtd", 0)
        excl_mtd_conv = ss.get("excl_somalia_conv_mtd", 0)
        excl_fc_regs = ss.get("excl_somalia_regs_forecast", 0)
        excl_fc_ftd = ss.get("excl_somalia_ftd_forecast", 0)
        excl_fc_conv = ss.get("excl_somalia_conv_forecast", 0)
        som_mtd_regs = ss.get("somalia_regs_mtd", 0)
        som_mtd_ftd = ss.get("somalia_ftd_mtd", 0)
        som_mtd_conv = ss.get("somalia_conv_mtd", 0)
        som_fc_regs = ss.get("somalia_regs_forecast", 0)
        som_fc_ftd = ss.get("somalia_ftd_forecast", 0)
        som_fc_conv = ss.get("somalia_conv_forecast", 0)

        traffic_rows.extend([
            ("Excl. Somalia", "", "", "", "", "", ""),
            ("  Regs", _fmt_int(ss.get("excl_somalia_regs", 0)), _fmt_int(excl_mtd_regs),
             _fmt_int(excl_fc_regs),
             _delta_html(ss.get("excl_somalia_regs_dod")), _delta_html(ss.get("excl_somalia_regs_wow")), _delta_html(ss.get("excl_somalia_regs_7d"))),
            ("  FTD", _fmt_int(ss.get("excl_somalia_ftd", 0)), _fmt_int(excl_mtd_ftd),
             _fmt_int(excl_fc_ftd),
             _delta_html(ss.get("excl_somalia_ftd_dod")), _delta_html(ss.get("excl_somalia_ftd_wow")), _delta_html(ss.get("excl_somalia_ftd_7d"))),
            ("  Conv", _fmt_pct(ss.get("excl_somalia_conv", 0)), _fmt_pct(excl_mtd_conv),
             _fmt_pct(excl_fc_conv),
             _delta_html(ss.get("excl_somalia_conv_dod"), suffix="pp"),
             _delta_html(ss.get("excl_somalia_conv_wow"), suffix="pp"),
             _delta_html(ss.get("excl_somalia_conv_7d"), suffix="pp")),
            ("Somalia only", "", "", "", "", "", ""),
            ("  Regs", _fmt_int(ss.get("somalia_regs", 0)), _fmt_int(som_mtd_regs),
             _fmt_int(som_fc_regs),
             _delta_html(ss.get("somalia_regs_dod")), _delta_html(ss.get("somalia_regs_wow")), _delta_html(ss.get("somalia_regs_7d"))),
            ("  FTD", _fmt_int(ss.get("somalia_ftd", 0)), _fmt_int(som_mtd_ftd),
             _fmt_int(som_fc_ftd),
             _delta_html(ss.get("somalia_ftd_dod")), _delta_html(ss.get("somalia_ftd_wow")), _delta_html(ss.get("somalia_ftd_7d"))),
            ("  Conv", _fmt_pct(ss.get("somalia_conv", 0)), _fmt_pct(som_mtd_conv),
             _fmt_pct(som_fc_conv),
             _delta_html(ss.get("somalia_conv_dod"), suffix="pp"),
             _delta_html(ss.get("somalia_conv_wow"), suffix="pp"),
             _delta_html(ss.get("somalia_conv_7d"), suffix="pp")),
        ])

    # Gaming rows
    gaming_rows = [
        ("Sport GGR", _fmt_eur(d.get("sport_ggr", 0)), _mtd_eur("sport_ggr"), _plan(plan.get("sport_ggr_plan")),
         _delta_html(d.get("sport_ggr_dod")), _delta_html(d.get("sport_ggr_wow")), _delta_html(d.get("sport_ggr_7d"))),
        ("Casino GGR", _fmt_eur(d.get("casino_ggr", 0)), _mtd_eur("casino_ggr"), _plan(plan.get("casino_ggr_plan")),
         _delta_html(d.get("casino_ggr_dod")), _delta_html(d.get("casino_ggr_wow")), _delta_html(d.get("casino_ggr_7d"))),
        ("Total GGR", _fmt_eur(d.get("total_ggr", 0)), _mtd_eur("total_ggr"), _plan(plan.get("total_ggr_plan")),
         _delta_html(d.get("total_ggr_dod")), _delta_html(d.get("total_ggr_wow")), _delta_html(d.get("total_ggr_7d"))),
        ("Sport/Casino Share", f"{sport_share:.0f}% / {casino_share:.0f}%", "", "", "", "", ""),
    ]

    # Turnover rows
    turnover_rows = [
        ("Sport Turnover", _fmt_eur(d.get("sport_turnover", 0)), _mtd_eur("sport_turnover"),
         _plan(plan.get("sport_turnover_plan")),
         _delta_html(d.get("sport_turnover_dod")), _delta_html(d.get("sport_turnover_wow")), _delta_html(d.get("sport_turnover_7d"))),
        ("Casino Turnover", _fmt_eur(d.get("casino_turnover", 0)), _mtd_eur("casino_turnover"),
         _plan(plan.get("casino_turnover_plan")),
         _delta_html(d.get("casino_turnover_dod")), _delta_html(d.get("casino_turnover_wow")), _delta_html(d.get("casino_turnover_7d"))),
        ("Total Turnover", _fmt_eur(d.get("total_turnover", 0)), _mtd_eur("total_turnover"),
         _plan(plan.get("turnover_plan")),
         _delta_html(d.get("total_turnover_dod")), _delta_html(d.get("total_turnover_wow")), _delta_html(d.get("total_turnover_7d"))),
    ]

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Daily Report {target.strftime('%d %b %Y')}</title>
    {STYLES}
</head>
<body style="margin:0;padding:20px 0;background:#f1f5f9;">
    <div class="report-container" style="max-width:960px;margin:0 auto;background:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.1);">

        <!-- Header -->
        <div class="header">
            <h1>Daily Report</h1>
            <p class="subtitle">{target.strftime('%d %B %Y')} ({day_name}) &bull; Sheets / EUR</p>
        </div>

        <!-- KPI Cards -->
        {_build_kpi_cards(d, plan, data.get("prev_month_totals", {}))}

        <!-- Revenue -->
        {_build_metrics_table("Revenue (EUR)", revenue_rows)}

        <!-- Traffic -->
        {_build_metrics_table("Traffic", traffic_rows)}

        <!-- Gaming -->
        {_build_metrics_table("Gaming (EUR)", gaming_rows)}

        <!-- Turnover -->
        {_build_metrics_table("Turnover (EUR)", turnover_rows)}

        <!-- Top 5 Players -->
        {_build_top_players(data.get("top_players", {}))}

        <!-- Top Countries -->
        {_build_countries_section(data)}

        <!-- Country Traffic Alerts -->
        {_build_country_traffic_alerts(data)}

        <!-- Alerts -->
        {_build_alerts_section(alerts)}

        <!-- Focus Markets -->
        {_build_focus_markets_section(data)}

        <!-- Glossary -->
        <div style="padding:16px 28px 8px;border-top:1px solid #e5e7eb;">
            <p style="font-size:11px;font-weight:600;color:#6b7280;text-transform:uppercase;margin:0 0 6px 0;">Glossary</p>
            <table cellpadding="0" cellspacing="0" border="0" style="font-size:11px;color:#6b7280;line-height:1.6;">
                <tr><td style="padding-right:12px;white-space:nowrap;">DoD</td><td>Day over Day, change vs previous day</td></tr>
                <tr><td style="padding-right:12px;white-space:nowrap;">WoW</td><td>Week over Week, change vs same day last week</td></tr>
                <tr><td style="padding-right:12px;white-space:nowrap;">vs 7d Avg</td><td>Change vs average of previous 7 days</td></tr>
                <tr><td style="padding-right:12px;white-space:nowrap;">MoM</td><td>Month over Month, plan vs previous month actual</td></tr>
                <tr><td style="padding-right:12px;white-space:nowrap;">MTD</td><td>Month to Date, cumulative total from 1st of the month</td></tr>
                <tr><td style="padding-right:12px;white-space:nowrap;">Plan</td><td>Monthly forecast from Google Sheets</td></tr>
                <tr><td style="padding-right:12px;white-space:nowrap;">GGR</td><td>Gross Gaming Revenue (Turnover - Winnings)</td></tr>
                <tr><td style="padding-right:12px;white-space:nowrap;">FTD</td><td>First Time Depositors</td></tr>
                <tr><td style="padding-right:12px;white-space:nowrap;">pp</td><td>Percentage points (absolute difference)</td></tr>
                <tr><td style="padding-right:12px;white-space:nowrap;">Forecast</td><td>Projected month total: MTD / days elapsed x days in month</td></tr>
            </table>
        </div>

        <!-- Footer -->
        <div class="footer">
            BetAndYou Analytics &bull; Generated automatically &bull; {target.strftime('%d.%m.%Y')}
        </div>

    </div>
</body>
</html>"""

    return html


def build_email_subject(data: dict) -> str:
    """Build the email subject line."""
    target: date = data["target_date"]
    return f"Daily Report {target.strftime('%d %b %Y')} B&U"
