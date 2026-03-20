"""
Build a plain-text daily report from Google Sheets data (EUR).
"""

from datetime import date
from config import TOP_COUNTRIES_LIMIT

DAY_NAMES = {
    0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu",
    4: "Fri", 5: "Sat", 6: "Sun",
}


def _fmt_eur(val: float) -> str:
    if val < 0:
        return f"-E{abs(val):,.0f}"
    return f"E{val:,.0f}"


def _fmt_int(val: int) -> str:
    return f"{val:,}"


def _fmt_pct(val: float) -> str:
    return f"{val:.1f}%"


def _fmt_delta(val: float | None, suffix: str = "%") -> str:
    if val is None:
        return "n/a"
    sign = "+" if val >= 0 else ""
    if suffix == "pp":
        return f"{sign}{val:.1f}pp"
    return f"{sign}{val:.1f}%"


def _line(label: str, value: str, dod: str, wow: str, width: int = 18) -> str:
    return f"  {label:<{width}}{value:<14}| {dod} DoD | {wow} WoW"


def _pct_change_safe(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return ((current - previous) / abs(previous)) * 100


def _fmt_delta_short(val: float | None) -> str:
    if val is None:
        return "n/a"
    sign = "+" if val >= 0 else ""
    return f"{sign}{val:.0f}%"


def build_sheets_report(data: dict) -> str:
    target: date = data["target_date"]
    d = data["data"]
    alerts = data["alerts"]
    sport_share = data.get("sport_share", 0)
    casino_share = 100 - sport_share

    day_name = DAY_NAMES[target.weekday()]
    header = f"DAILY REPORT (Sheets/EUR) | {target.strftime('%d %b %Y')} ({day_name})"

    lines = [header, ""]

    # --- REVENUE ---
    lines.append("REVENUE (EUR)")
    lines.append(_line(
        "Deposits:", _fmt_eur(d.get("deposits", 0)),
        _fmt_delta(d.get("deposits_dod")), _fmt_delta(d.get("deposits_wow")),
    ))
    lines.append(_line(
        "Withdrawals:", _fmt_eur(d.get("withdrawals", 0)),
        _fmt_delta(d.get("withdrawals_dod")), _fmt_delta(d.get("withdrawals_wow")),
    ))
    lines.append(_line(
        "Cash Flow:", _fmt_eur(d.get("cash_flow", 0)),
        _fmt_delta(d.get("cash_flow_dod")), _fmt_delta(d.get("cash_flow_wow")),
    ))
    lines.append(_line(
        "GGR Total:", _fmt_eur(d.get("total_ggr", 0)),
        _fmt_delta(d.get("total_ggr_dod")), _fmt_delta(d.get("total_ggr_wow")),
    ))
    lines.append(_line(
        "Promo:", _fmt_eur(d.get("promo", 0)),
        _fmt_delta(d.get("promo_dod")), _fmt_delta(d.get("promo_wow")),
    ))
    lines.append(_line(
        "GGR-Promo:", _fmt_eur(d.get("ggr_net_promo", 0)),
        _fmt_delta(d.get("ggr_net_promo_dod")), _fmt_delta(d.get("ggr_net_promo_wow")),
    ))
    lines.append("")

    # --- TRAFFIC ---
    lines.append("TRAFFIC")
    lines.append(_line(
        "Registrations:", _fmt_int(d.get("registrations", 0)),
        _fmt_delta(d.get("registrations_dod")), _fmt_delta(d.get("registrations_wow")),
    ))
    lines.append(_line(
        "FTD:", _fmt_int(d.get("ftd", 0)),
        _fmt_delta(d.get("ftd_dod")), _fmt_delta(d.get("ftd_wow")),
    ))
    lines.append(_line(
        "Conversion:", _fmt_pct(d.get("conversion", 0)),
        _fmt_delta(d.get("conversion_dod"), suffix="pp"),
        _fmt_delta(d.get("conversion_wow"), suffix="pp"),
    ))
    lines.append("")

    # --- GAMING ---
    lines.append("GAMING (EUR)")
    lines.append(_line(
        "Sport GGR:", _fmt_eur(d.get("sport_ggr", 0)),
        _fmt_delta(d.get("sport_ggr_dod")), _fmt_delta(d.get("sport_ggr_wow")),
    ))
    lines.append(_line(
        "Casino GGR:", _fmt_eur(d.get("casino_ggr", 0)),
        _fmt_delta(d.get("casino_ggr_dod")), _fmt_delta(d.get("casino_ggr_wow")),
    ))
    lines.append(f"  Sport/Casino:     {sport_share:.0f}%/{casino_share:.0f}%")
    lines.append("")

    # --- TURNOVER ---
    lines.append("TURNOVER (EUR)")
    lines.append(_line(
        "Sport Turnover:", _fmt_eur(d.get("sport_turnover", 0)),
        _fmt_delta(d.get("sport_turnover_dod")), _fmt_delta(d.get("sport_turnover_wow")),
    ))
    lines.append(_line(
        "Casino Turnover:", _fmt_eur(d.get("casino_turnover", 0)),
        _fmt_delta(d.get("casino_turnover_dod")), _fmt_delta(d.get("casino_turnover_wow")),
    ))
    lines.append(_line(
        "Total Turnover:", _fmt_eur(d.get("total_turnover", 0)),
        _fmt_delta(d.get("total_turnover_dod")), _fmt_delta(d.get("total_turnover_wow")),
    ))
    lines.append("")

    # --- MTD vs PLAN ---
    mtd = data.get("mtd", {})
    plan = data.get("plan", {})
    if mtd:
        days_elapsed = mtd.get("days_elapsed", 0)
        days_total = mtd.get("days_in_month", 28)
        pct_month = (days_elapsed / days_total * 100) if days_total > 0 else 0

        lines.append(f"MTD vs PLAN  ({days_elapsed}/{days_total} days, {pct_month:.0f}% of month)")

        mtd_items = [
            ("Deposits", "deposits", "deposits_plan"),
            ("Withdrawals", "withdrawals", "withdrawals_plan"),
            ("Cash Flow", "cash_flow", "cash_flow_plan"),
            ("Turnover", "total_turnover", "turnover_plan"),
            ("GGR Total", "total_ggr", None),
            ("GGR-Promo", "ggr_net_promo", None),
        ]

        for label, mtd_key, plan_key in mtd_items:
            mtd_val = mtd.get(mtd_key, 0)
            if plan_key and plan_key in plan and plan[plan_key] > 0:
                plan_val = plan[plan_key]
                pct_of_plan = mtd_val / plan_val * 100
                # Expected pace: if we are at X% of month, we expect X% of plan
                pace_delta = pct_of_plan - pct_month
                pace_sign = "+" if pace_delta >= 0 else ""
                lines.append(
                    f"  {label:<18}{_fmt_eur(mtd_val):<14}"
                    f"| {pct_of_plan:.1f}% of plan"
                    f" | pace {pace_sign}{pace_delta:.1f}pp"
                )
            else:
                lines.append(f"  {label:<18}{_fmt_eur(mtd_val)}")

        # Registrations & FTD (integers)
        lines.append(f"  {'Registrations':<18}{_fmt_int(mtd.get('registrations', 0))}")
        lines.append(f"  {'FTD':<18}{_fmt_int(mtd.get('ftd', 0))}")
        ftd_total = mtd.get("ftd", 0)
        regs_total = mtd.get("registrations", 0)
        conv_mtd = (ftd_total / regs_total * 100) if regs_total > 0 else 0
        lines.append(f"  {'Conversion':<18}{_fmt_pct(conv_mtd)}")

        lines.append("")

    # --- TOP COUNTRIES (Deposits) ---
    country_data = data.get("country_deposits", {})
    if country_data and country_data.get("today"):
        mtd_data = data.get("mtd", {})
        days_elapsed = mtd_data.get("days_elapsed", 0)
        days_total = mtd_data.get("days_in_month", 28)
        pct_month = (days_elapsed / days_total * 100) if days_total > 0 else 0

        # Build lookup maps
        top_today = country_data["today"][:TOP_COUNTRIES_LIMIT]
        yesterday_map = {c["country"]: c["deposits"] for c in country_data.get("yesterday", [])}
        mtd_map = {c["country"]: c["deposits"] for c in country_data.get("mtd", [])}
        plan_map = {c["country"]: c["deposits_plan"] for c in country_data.get("plan", [])}

        prev_months = country_data.get("prev_months", {})
        jan_map = {c["country"]: c["deposits"] for c in prev_months.get("jan", [])}
        dec_map = {c["country"]: c["deposits"] for c in prev_months.get("dec", [])}
        nov_map = {c["country"]: c["deposits"] for c in prev_months.get("nov", [])}

        # --- Line 1: daily values ---
        lines.append(f"TOP {TOP_COUNTRIES_LIMIT} COUNTRIES (Deposits EUR)")
        for item in top_today:
            country = item["country"]
            today_val = item["deposits"]
            prev_val = yesterday_map.get(country, 0)
            dod = _pct_change_safe(today_val, prev_val)

            mtd_val = mtd_map.get(country, 0)
            plan_val = plan_map.get(country, 0)

            pace_str = ""
            if plan_val > 0:
                pct_of_plan = mtd_val / plan_val * 100
                pace = pct_of_plan - pct_month
                pace_sign = "+" if pace >= 0 else ""
                pace_str = f"| {pct_of_plan:.1f}% plan ({pace_sign}{pace:.1f}pp)"

            lines.append(
                f"  {country:<14}{_fmt_eur(today_val):<12}{_fmt_delta_short(dod)} DoD {pace_str}"
            )

        lines.append("")

        # --- Line 2: Plan vs previous months ---
        lines.append("PLAN vs PREV MONTHS (Deposits EUR)")
        lines.append(f"  {'Country':<14}{'Plan':<12}{'vs Jan':<10}{'vs Dec':<10}{'vs Nov':<10}")

        # Sort by plan descending
        plan_sorted = sorted(
            [(c, plan_map.get(c, 0)) for _, c in [(0, item["country"]) for item in top_today]],
            key=lambda x: x[1],
            reverse=True,
        )

        for country, plan_val in plan_sorted:
            if plan_val <= 0:
                continue
            jan_val = jan_map.get(country, 0)
            dec_val = dec_map.get(country, 0)
            nov_val = nov_map.get(country, 0)

            vs_jan = _fmt_delta_short(_pct_change_safe(plan_val, jan_val)) if jan_val > 0 else "n/a"
            vs_dec = _fmt_delta_short(_pct_change_safe(plan_val, dec_val)) if dec_val > 0 else "n/a"
            vs_nov = _fmt_delta_short(_pct_change_safe(plan_val, nov_val)) if nov_val > 0 else "n/a"

            lines.append(
                f"  {country:<14}{_fmt_eur(plan_val):<12}{vs_jan:<10}{vs_dec:<10}{vs_nov:<10}"
            )

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
