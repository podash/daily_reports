"""
Fetch daily metrics from aggregates and compute DoD / WoW / 7d-avg deltas.
"""

import logging
from datetime import date, timedelta
from decimal import Decimal

from db_client import execute_query, execute_scalar
from config import TOP_COUNTRIES_LIMIT, ALERT_THRESHOLD_PCT

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Freshness
# ------------------------------------------------------------------

def check_freshness(target_date: date) -> dict:
    """Return freshness status for each aggregate view."""
    views = [
        "aggregates.daily_traffic_core",
        "aggregates.daily_traffic_gaming",
        "aggregates.daily_traffic_players",
    ]
    result = {}
    for view in views:
        max_date = execute_scalar(f"SELECT MAX(stat_date) FROM {view}")
        is_fresh = max_date is not None and max_date >= target_date
        result[view] = {"max_date": max_date, "fresh": is_fresh}
        if not is_fresh:
            logger.warning("%s stale: max_date=%s, expected>=%s", view, max_date, target_date)
    return result


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _to_float(val) -> float:
    if val is None:
        return 0.0
    if isinstance(val, Decimal):
        return float(val)
    return float(val)


def _pct_change(current: float, previous: float) -> float | None:
    """Percentage change. Returns None when previous is zero."""
    if previous == 0:
        return None
    return ((current - previous) / abs(previous)) * 100


def _pp_change(current_pct: float, previous_pct: float) -> float | None:
    """Percentage-point change for ratio metrics."""
    if previous_pct is None or current_pct is None:
        return None
    return current_pct - previous_pct


# ------------------------------------------------------------------
# Revenue & Traffic (daily_traffic_core)
# ------------------------------------------------------------------

_CORE_SQL = """
SELECT
    stat_date,
    SUM(registrations_count::bigint)       AS registrations,
    SUM(ftd_count::bigint)                 AS ftd,
    SUM(ftd_amount_usd::numeric)           AS ftd_amount,
    SUM(deposits_count::bigint)            AS deposits_count,
    SUM(deposits_amount_usd::numeric)      AS deposits,
    SUM(withdrawals_count::bigint)         AS withdrawals_count,
    SUM(withdrawals_amount_usd::numeric)   AS withdrawals
FROM aggregates.daily_traffic_core
WHERE stat_date = ANY(%(dates)s)
GROUP BY stat_date
ORDER BY stat_date;
"""


def _fetch_core(dates: list[date]) -> dict[date, dict]:
    rows = execute_query(_CORE_SQL, {"dates": dates})
    out = {}
    for r in rows:
        d = r["stat_date"]
        regs = int(r["registrations"] or 0)
        ftd = int(r["ftd"] or 0)
        out[d] = {
            "registrations": regs,
            "ftd": ftd,
            "ftd_amount": _to_float(r["ftd_amount"]),
            "deposits_count": int(r["deposits_count"] or 0),
            "deposits": _to_float(r["deposits"]),
            "withdrawals_count": int(r["withdrawals_count"] or 0),
            "withdrawals": _to_float(r["withdrawals"]),
            "conversion": (ftd / regs * 100) if regs > 0 else 0.0,
        }
    return out


# ------------------------------------------------------------------
# Gaming (daily_traffic_gaming)
# ------------------------------------------------------------------

_GAMING_SQL = """
SELECT
    stat_date,
    SUM(sport_bets_count::bigint)      AS sport_bets,
    SUM(sport_turnover_usd::numeric)   AS sport_turnover,
    SUM(sport_winnings_usd::numeric)   AS sport_winnings,
    SUM(sport_ggr_usd::numeric)        AS sport_ggr,
    SUM(casino_bets_count::bigint)     AS casino_bets,
    SUM(casino_turnover_usd::numeric)  AS casino_turnover,
    SUM(casino_winnings_usd::numeric)  AS casino_winnings,
    SUM(casino_ggr_usd::numeric)       AS casino_ggr,
    SUM(total_ggr_usd::numeric)        AS total_ggr
FROM aggregates.daily_traffic_gaming
WHERE stat_date = ANY(%(dates)s)
GROUP BY stat_date
ORDER BY stat_date;
"""


def _fetch_gaming(dates: list[date]) -> dict[date, dict]:
    rows = execute_query(_GAMING_SQL, {"dates": dates})
    out = {}
    for r in rows:
        sport_ggr = _to_float(r["sport_ggr"])
        casino_ggr = _to_float(r["casino_ggr"])
        total_ggr = _to_float(r["total_ggr"])
        out[r["stat_date"]] = {
            "sport_bets": int(r["sport_bets"] or 0),
            "sport_turnover": _to_float(r["sport_turnover"]),
            "sport_ggr": sport_ggr,
            "casino_bets": int(r["casino_bets"] or 0),
            "casino_turnover": _to_float(r["casino_turnover"]),
            "casino_ggr": casino_ggr,
            "total_ggr": total_ggr,
            "sport_share": (sport_ggr / total_ggr * 100) if total_ggr != 0 else 0.0,
        }
    return out


# ------------------------------------------------------------------
# Players (daily_traffic_players)
# ------------------------------------------------------------------

_PLAYERS_SQL = """
SELECT
    stat_date,
    SUM(active_players::bigint)        AS active_players,
    SUM(sport_active_players::bigint)  AS sport_active,
    SUM(casino_active_players::bigint) AS casino_active,
    SUM(depositors_count::bigint)      AS depositors
FROM aggregates.daily_traffic_players
WHERE stat_date = ANY(%(dates)s)
GROUP BY stat_date
ORDER BY stat_date;
"""


def _fetch_players(dates: list[date]) -> dict[date, dict]:
    rows = execute_query(_PLAYERS_SQL, {"dates": dates})
    out = {}
    for r in rows:
        out[r["stat_date"]] = {
            "active_players": int(r["active_players"] or 0),
            "sport_active": int(r["sport_active"] or 0),
            "casino_active": int(r["casino_active"] or 0),
            "depositors": int(r["depositors"] or 0),
        }
    return out


# ------------------------------------------------------------------
# Top Countries (daily_traffic_core)
# ------------------------------------------------------------------

_TOP_COUNTRIES_SQL = """
SELECT
    country,
    SUM(deposits_amount_usd::numeric) AS deposits
FROM aggregates.daily_traffic_core
WHERE stat_date = %(target_date)s
GROUP BY country
ORDER BY deposits DESC
LIMIT %(limit)s;
"""


def fetch_top_countries(target_date: date) -> list[dict]:
    rows = execute_query(
        _TOP_COUNTRIES_SQL,
        {"target_date": target_date, "limit": TOP_COUNTRIES_LIMIT},
    )
    return [{"country": r["country"], "deposits": _to_float(r["deposits"])} for r in rows]


# ------------------------------------------------------------------
# 7-day average (for alerts)
# ------------------------------------------------------------------

_CORE_7D_AVG_SQL = """
SELECT
    ROUND(AVG(registrations)::numeric, 2) AS avg_registrations,
    ROUND(AVG(deposits)::numeric, 2)      AS avg_deposits,
    ROUND(AVG(withdrawals)::numeric, 2)   AS avg_withdrawals,
    ROUND(AVG(ftd)::numeric, 2)           AS avg_ftd
FROM (
    SELECT
        stat_date,
        SUM(registrations_count::bigint)     AS registrations,
        SUM(deposits_amount_usd::numeric)    AS deposits,
        SUM(withdrawals_amount_usd::numeric) AS withdrawals,
        SUM(ftd_count::bigint)               AS ftd
    FROM aggregates.daily_traffic_core
    WHERE stat_date >= %(start)s AND stat_date < %(end)s
    GROUP BY stat_date
) daily;
"""

_GAMING_7D_AVG_SQL = """
SELECT
    ROUND(AVG(sport_ggr)::numeric, 2)  AS avg_sport_ggr,
    ROUND(AVG(casino_ggr)::numeric, 2) AS avg_casino_ggr,
    ROUND(AVG(total_ggr)::numeric, 2)  AS avg_total_ggr
FROM (
    SELECT
        stat_date,
        SUM(sport_ggr_usd::numeric)  AS sport_ggr,
        SUM(casino_ggr_usd::numeric) AS casino_ggr,
        SUM(total_ggr_usd::numeric)  AS total_ggr
    FROM aggregates.daily_traffic_gaming
    WHERE stat_date >= %(start)s AND stat_date < %(end)s
    GROUP BY stat_date
) daily;
"""


def _fetch_7d_averages(target_date: date) -> dict:
    start = target_date - timedelta(days=7)
    params = {"start": start, "end": target_date}

    core_rows = execute_query(_CORE_7D_AVG_SQL, params)
    gaming_rows = execute_query(_GAMING_7D_AVG_SQL, params)

    core = core_rows[0] if core_rows else {}
    gaming = gaming_rows[0] if gaming_rows else {}

    return {
        "registrations": _to_float(core.get("avg_registrations")),
        "deposits": _to_float(core.get("avg_deposits")),
        "withdrawals": _to_float(core.get("avg_withdrawals")),
        "ftd": _to_float(core.get("avg_ftd")),
        "sport_ggr": _to_float(gaming.get("avg_sport_ggr")),
        "casino_ggr": _to_float(gaming.get("avg_casino_ggr")),
        "total_ggr": _to_float(gaming.get("avg_total_ggr")),
    }


# ------------------------------------------------------------------
# Alerts
# ------------------------------------------------------------------

def _build_alerts(today_vals: dict, avg_7d: dict) -> list[str]:
    """Generate alert strings for metrics that deviate > threshold from 7d avg."""
    threshold = ALERT_THRESHOLD_PCT
    alerts = []

    checks = [
        ("Registrations", "registrations"),
        ("Deposits", "deposits"),
        ("Withdrawals", "withdrawals"),
        ("FTD", "ftd"),
        ("Sport GGR", "sport_ggr"),
        ("Casino GGR", "casino_ggr"),
        ("Total GGR", "total_ggr"),
    ]

    for label, key in checks:
        current = today_vals.get(key, 0)
        avg = avg_7d.get(key, 0)
        pct = _pct_change(current, avg)
        if pct is not None and abs(pct) > threshold:
            direction = "+" if pct > 0 else ""
            alerts.append(f"[!] {label} {direction}{pct:,.1f}% vs 7d avg (threshold {threshold:.0f}%)")

    return alerts


# ------------------------------------------------------------------
# Assemble delta row
# ------------------------------------------------------------------

def _with_deltas(today: dict, yesterday: dict, last_week: dict, ratio_keys=None) -> dict:
    """Add DoD and WoW deltas to today's metrics dict."""
    ratio_keys = ratio_keys or set()
    enriched = {}
    for key, val in today.items():
        enriched[key] = val
        prev = yesterday.get(key)
        week = last_week.get(key)

        if key in ratio_keys:
            enriched[f"{key}_dod"] = _pp_change(val, prev)
            enriched[f"{key}_wow"] = _pp_change(val, week)
        else:
            enriched[f"{key}_dod"] = _pct_change(val, prev) if prev is not None else None
            enriched[f"{key}_wow"] = _pct_change(val, week) if week is not None else None
    return enriched


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

_EMPTY_CORE = {
    "registrations": 0, "ftd": 0, "ftd_amount": 0.0,
    "deposits_count": 0, "deposits": 0.0,
    "withdrawals_count": 0, "withdrawals": 0.0,
    "conversion": 0.0,
}

_EMPTY_GAMING = {
    "sport_bets": 0, "sport_turnover": 0.0, "sport_ggr": 0.0,
    "casino_bets": 0, "casino_turnover": 0.0, "casino_ggr": 0.0,
    "total_ggr": 0.0, "sport_share": 0.0,
}

_EMPTY_PLAYERS = {
    "active_players": 0, "sport_active": 0, "casino_active": 0, "depositors": 0,
}


def collect_daily_metrics(target_date: date) -> dict:
    """
    Collect all metrics for the target_date and return a structured dict
    with values, DoD/WoW deltas, top countries, and alerts.
    """
    prev_day = target_date - timedelta(days=1)
    prev_week = target_date - timedelta(days=7)
    needed_dates = [target_date, prev_day, prev_week]

    # Fetch raw data
    core_data = _fetch_core(needed_dates)
    gaming_data = _fetch_gaming(needed_dates)
    players_data = _fetch_players(needed_dates)

    # Extract per-date with fallback
    core_today = core_data.get(target_date, _EMPTY_CORE)
    core_prev = core_data.get(prev_day, _EMPTY_CORE)
    core_week = core_data.get(prev_week, _EMPTY_CORE)

    gaming_today = gaming_data.get(target_date, _EMPTY_GAMING)
    gaming_prev = gaming_data.get(prev_day, _EMPTY_GAMING)
    gaming_week = gaming_data.get(prev_week, _EMPTY_GAMING)

    players_today = players_data.get(target_date, _EMPTY_PLAYERS)
    players_prev = players_data.get(prev_day, _EMPTY_PLAYERS)
    players_week = players_data.get(prev_week, _EMPTY_PLAYERS)

    # Compute net revenue
    core_today["net_revenue"] = core_today["deposits"] - core_today["withdrawals"]
    core_prev["net_revenue"] = core_prev["deposits"] - core_prev["withdrawals"]
    core_week["net_revenue"] = core_week["deposits"] - core_week["withdrawals"]

    # Enrich with deltas
    revenue = _with_deltas(core_today, core_prev, core_week, ratio_keys={"conversion"})
    gaming = _with_deltas(gaming_today, gaming_prev, gaming_week)
    players = _with_deltas(players_today, players_prev, players_week)

    # Top countries
    top_countries = fetch_top_countries(target_date)

    # 7d averages and alerts
    avg_7d = _fetch_7d_averages(target_date)
    alert_vals = {
        "registrations": core_today["registrations"],
        "deposits": core_today["deposits"],
        "withdrawals": core_today["withdrawals"],
        "ftd": core_today["ftd"],
        "sport_ggr": gaming_today["sport_ggr"],
        "casino_ggr": gaming_today["casino_ggr"],
        "total_ggr": gaming_today["total_ggr"],
    }
    alerts = _build_alerts(alert_vals, avg_7d)

    return {
        "target_date": target_date,
        "revenue": revenue,
        "gaming": gaming,
        "players": players,
        "top_countries": top_countries,
        "alerts": alerts,
    }
