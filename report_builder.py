"""
Build a plain-text daily report from collected metrics.
"""

from datetime import date

DAY_NAMES = {
    0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu",
    4: "Fri", 5: "Sat", 6: "Sun",
}


def _fmt_money(val: float) -> str:
    """Format as $X,XXX with no decimals."""
    if val < 0:
        return f"-${abs(val):,.0f}"
    return f"${val:,.0f}"


def _fmt_int(val: int) -> str:
    return f"{val:,}"


def _fmt_pct(val: float) -> str:
    return f"{val:.1f}%"


def _fmt_delta(val: float | None, suffix: str = "%") -> str:
    """Format a DoD/WoW delta. Returns 'n/a' when None."""
    if val is None:
        return "n/a"
    sign = "+" if val >= 0 else ""
    if suffix == "pp":
        return f"{sign}{val:.1f}pp"
    return f"{sign}{val:.1f}%"


def _line(label: str, value: str, dod: str, wow: str, width: int = 16) -> str:
    return f"  {label:<{width}}{value:<14}| {dod} DoD | {wow} WoW"


def build_report(data: dict) -> str:
    """Return the full report as a plain-text string."""
    target: date = data["target_date"]
    r = data["revenue"]
    g = data["gaming"]
    p = data["players"]
    top = data["top_countries"]
    alerts = data["alerts"]

    day_name = DAY_NAMES[target.weekday()]
    header = f"DAILY REPORT | {target.strftime('%d %b %Y')} ({day_name})"

    lines = [header, ""]

    # --- REVENUE ---
    lines.append("REVENUE")
    lines.append(_line(
        "Deposits:", _fmt_money(r["deposits"]),
        _fmt_delta(r.get("deposits_dod")), _fmt_delta(r.get("deposits_wow")),
    ))
    lines.append(_line(
        "Withdrawals:", _fmt_money(r["withdrawals"]),
        _fmt_delta(r.get("withdrawals_dod")), _fmt_delta(r.get("withdrawals_wow")),
    ))
    lines.append(_line(
        "Net Revenue:", _fmt_money(r["net_revenue"]),
        _fmt_delta(r.get("net_revenue_dod")), _fmt_delta(r.get("net_revenue_wow")),
    ))
    lines.append(_line(
        "GGR Total:", _fmt_money(g["total_ggr"]),
        _fmt_delta(g.get("total_ggr_dod")), _fmt_delta(g.get("total_ggr_wow")),
    ))
    lines.append("")

    # --- TRAFFIC ---
    lines.append("TRAFFIC")
    lines.append(_line(
        "Registrations:", _fmt_int(r["registrations"]),
        _fmt_delta(r.get("registrations_dod")), _fmt_delta(r.get("registrations_wow")),
    ))
    lines.append(_line(
        "FTD:", _fmt_int(r["ftd"]),
        _fmt_delta(r.get("ftd_dod")), _fmt_delta(r.get("ftd_wow")),
    ))
    lines.append(_line(
        "Conversion:", _fmt_pct(r["conversion"]),
        _fmt_delta(r.get("conversion_dod"), suffix="pp"),
        _fmt_delta(r.get("conversion_wow"), suffix="pp"),
    ))
    lines.append("")

    # --- GAMING ---
    lines.append("GAMING")
    lines.append(_line(
        "Sport GGR:", _fmt_money(g["sport_ggr"]),
        _fmt_delta(g.get("sport_ggr_dod")), _fmt_delta(g.get("sport_ggr_wow")),
    ))
    lines.append(_line(
        "Casino GGR:", _fmt_money(g["casino_ggr"]),
        _fmt_delta(g.get("casino_ggr_dod")), _fmt_delta(g.get("casino_ggr_wow")),
    ))
    sport_share = g.get("sport_share", 0)
    casino_share = 100 - sport_share
    lines.append(f"  Sport/Casino:   {sport_share:.0f}%/{casino_share:.0f}%")
    lines.append("")

    # --- PLAYERS ---
    lines.append("PLAYERS")
    lines.append(_line(
        "DAU Total:", _fmt_int(p["active_players"]),
        _fmt_delta(p.get("active_players_dod")), _fmt_delta(p.get("active_players_wow")),
    ))
    lines.append(_line(
        "Sport Active:", _fmt_int(p["sport_active"]),
        _fmt_delta(p.get("sport_active_dod")), _fmt_delta(p.get("sport_active_wow")),
    ))
    lines.append(_line(
        "Casino Active:", _fmt_int(p["casino_active"]),
        _fmt_delta(p.get("casino_active_dod")), _fmt_delta(p.get("casino_active_wow")),
    ))
    lines.append(_line(
        "Depositors:", _fmt_int(p["depositors"]),
        _fmt_delta(p.get("depositors_dod")), _fmt_delta(p.get("depositors_wow")),
    ))
    lines.append("")

    # --- TOP COUNTRIES ---
    if top:
        lines.append("TOP COUNTRIES (Deposits)")
        for i, row in enumerate(top, 1):
            lines.append(f"  {i}. {row['country']:<16}{_fmt_money(row['deposits'])}")
        lines.append("")

    # --- ALERTS ---
    if alerts:
        lines.append("ALERTS")
        for a in alerts:
            lines.append(f"  {a}")
    else:
        lines.append("ALERTS")
        lines.append("  No anomalies detected.")

    return "\n".join(lines)
