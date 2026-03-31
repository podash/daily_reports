"""
Collect weekly affiliate GEO metrics from PostgreSQL.

Manager = affiliate_group from affiliate_partners (with type suffix stripped).
  e.g. "Affiliate 4 (inbound)" -> manager="Affiliate 4", group_type="Inbound"

Covers all 9 blocks of the Affiliate GEO Report (ТЗ):
  1. Top Partners
  2. Falling Partners
  3. New Partners
  4. Reactivation
  5. Zero Activity
  6. Traffic Quality (no-FTD + low conversion)
  7. Partner Activity
  8. Affiliate Totals (last 6 weeks, inbound vs acquisition)
  9. Month Comparison (last 2 months + MTD)
"""

import calendar
import json
import logging
from datetime import date, timedelta
from pathlib import Path

from db_client import execute_query

logger = logging.getLogger(__name__)


def _aff_clause(affiliate_ids: list[int] | None, alias: str = "ads") -> str:
    """Return SQL AND clause to filter by affiliate_ids, or empty string."""
    if not affiliate_ids:
        return ""
    col = f"{alias}.affiliate_id" if alias else "affiliate_id"
    return f"AND {col} = ANY(%s)"


def fetch_manager_affiliate_ids(manager_group: str) -> list[int]:
    """Return all affiliate_ids belonging to the given manager group key (e.g. 'affiliate 1').
    Strips everything from first '(' onwards, then trims and lowercases.
    Handles both 'Affiliate 4 (inbound) Lada' and 'Affiliate 4 (inbound)' formats.
    """
    rows = execute_query(
        r"""
        SELECT DISTINCT affiliate_id
        FROM public.affiliate_partners
        WHERE LOWER(TRIM(REGEXP_REPLACE(affiliate_group, '\s*\(.*$', '', 'i'))) = %s
          AND affiliate_id IS NOT NULL
        """,
        (manager_group.lower().strip(),),
    )
    ids = [int(r["affiliate_id"]) for r in rows if r.get("affiliate_id")]
    logger.info("Manager '%s': found %d affiliate_ids", manager_group, len(ids))
    return ids


# ---------------------------------------------------------------------------
# Manager name mapping (loaded from local JSON)
# ---------------------------------------------------------------------------

_NAMES_FILE = Path(__file__).parent / "manager_names.json"


def load_manager_names() -> dict[str, str]:
    """Load affiliate group -> real name mapping. Keys are lowercase."""
    if not _NAMES_FILE.exists():
        logger.warning("manager_names.json not found at %s", _NAMES_FILE)
        return {}
    try:
        raw = json.loads(_NAMES_FILE.read_text(encoding="utf-8"))
        return {k.lower().strip(): v for k, v in raw.items() if k}
    except Exception as e:
        logger.warning("Failed to load manager_names.json: %s", e)
        return {}


def enrich_manager_name(manager: str, names: dict[str, str]) -> str:
    """
    Return "Group (RealName)" if mapping found, else original.
    Lookup is case-insensitive on the group prefix.
    """
    if not names or not manager or manager == "—":
        return manager
    real_name = names.get(manager.lower().strip())
    if real_name:
        return f"{manager} ({real_name})"
    return manager


def enrich_rows(rows: list[dict], names: dict[str, str]) -> list[dict]:
    """Apply manager name enrichment to a list of row dicts (in-place)."""
    for row in rows:
        if "manager" in row:
            row["manager"] = enrich_manager_name(row["manager"], names)
    return rows

TOP_PARTNERS_LIMIT    = 10
FALLING_PARTNERS_LIMIT = 15
NEW_PARTNERS_LIMIT    = 15
REACTIVATION_LIMIT    = 15
ZERO_ACTIVITY_LIMIT   = 15
NO_FTD_LIMIT          = 15
LOW_CONV_LIMIT        = 10


# ---------------------------------------------------------------------------
# Period calculations
# ---------------------------------------------------------------------------

def get_report_periods(report_date: date) -> dict:
    """Return all date boundary variables needed for the weekly report.

    Primary period = last completed Mon-Sun calendar week.
    weekday(): Mon=0, Sun=6  -> days_back to last Sunday = weekday() + 1
    """
    days_back   = report_date.weekday() + 1   # how many days back to reach last Sunday
    period_end  = report_date - timedelta(days=days_back)
    week4_start = period_end - timedelta(days=6)  # Monday of that week

    ref_end   = week4_start - timedelta(days=1)
    ref_start = ref_end - timedelta(days=89)

    week6_start  = period_end - timedelta(days=41)
    month12_start = period_end - timedelta(days=364)

    current_month_start = report_date.replace(day=1)
    current_month_end   = period_end

    prev_month_end   = current_month_start - timedelta(days=1)
    prev_month_start = prev_month_end.replace(day=1)

    prev2_month_end   = prev_month_start - timedelta(days=1)
    prev2_month_start = prev2_month_end.replace(day=1)

    days_elapsed  = (current_month_end - current_month_start).days + 1
    days_in_month = calendar.monthrange(report_date.year, report_date.month)[1]
    new_partner_cutoff = period_end - timedelta(days=90)

    # YoY: full same month in previous year
    yoy_year = current_month_start.year - 1
    yoy_month_start = current_month_start.replace(year=yoy_year)
    yoy_month_end   = date(yoy_year, current_month_start.month,
                           calendar.monthrange(yoy_year, current_month_start.month)[1])

    return {
        "period_end":          period_end,
        "week4_start":         week4_start,
        "ref_start":           ref_start,
        "ref_end":             ref_end,
        "week6_start":         week6_start,
        "month12_start":       month12_start,
        "current_month_start": current_month_start,
        "current_month_end":   current_month_end,
        "prev_month_start":    prev_month_start,
        "prev_month_end":      prev_month_end,
        "prev2_month_start":   prev2_month_start,
        "prev2_month_end":     prev2_month_end,
        "days_elapsed":        days_elapsed,
        "days_in_month":       days_in_month,
        "new_partner_cutoff":  new_partner_cutoff,
        "yoy_month_start":     yoy_month_start,
        "yoy_month_end":       yoy_month_end,
    }


# ---------------------------------------------------------------------------
# Common CTE: affiliate_partners -> manager name + group type
#
# Manager = affiliate_group with " (inbound)" / " (acquisition)" stripped.
# e.g. "Affiliate 4 (inbound)"  -> manager="Affiliate 4", group_type="Inbound"
#      "Affiliate 4 (acquisition)" -> manager="Affiliate 4", group_type="Acquisition"
#
# NOTE: %% in ILIKE patterns because psycopg2 treats % as a placeholder escape.
# ---------------------------------------------------------------------------

_AFF_INFO_CTE = r"""
    aff_info AS (
        SELECT
            affiliate_id::bigint                                                       AS affiliate_id,
            TRIM(REGEXP_REPLACE(affiliate_group, '\s*\(.*$', '', 'i'))                AS manager,
            CASE
                WHEN affiliate_group ILIKE '%%inbound%%'     THEN 'Inbound'
                WHEN affiliate_group ILIKE '%%acquisition%%' THEN 'Acquisition'
                ELSE 'Other'
            END                                                                        AS group_type
        FROM public.affiliate_partners
        WHERE affiliate_group IS NOT NULL
    )
"""


# ---------------------------------------------------------------------------
# Block 1 — Top Partners
# ---------------------------------------------------------------------------

def _fetch_block1_base(
    periods: dict,
    affiliate_ids: list[int] | None,
    order_by: str = "ftd",
) -> list[dict]:
    """All countries, no GEO filter. Filters by affiliate_ids in SQL so LIMIT is correct."""
    clause = _aff_clause(affiliate_ids, alias="ads")
    extra  = [affiliate_ids] if affiliate_ids else []

    if order_by == "ftd":
        having = "HAVING SUM(ads.ftd_count) >= 3"
    else:
        having = "HAVING SUM(ads.deposits_amount_usd) >= 100"

    rows = execute_query(
        f"""
        WITH {_AFF_INFO_CTE}
        SELECT
            ads.affiliate_id,
            COALESCE(ai.manager, '—')                           AS manager,
            COALESCE(ai.group_type, '—')                        AS group_type,
            SUM(ads.registrations_count)                        AS regs,
            SUM(ads.ftd_count)                                  AS ftd,
            ROUND(SUM(ads.new_players_deposit_sum)::numeric, 0) AS new_dep_amount,
            ROUND(SUM(ads.deposits_amount_usd)::numeric, 0)     AS deposits_usd,
            CASE WHEN SUM(ads.registrations_count) > 0
                 THEN ROUND((SUM(ads.ftd_count)::numeric
                      / SUM(ads.registrations_count) * 100), 1)
                 ELSE 0 END                                     AS conversion_pct
        FROM aggregates.affiliate_daily_stats ads
        LEFT JOIN aff_info ai ON ai.affiliate_id = ads.affiliate_id
        WHERE ads.stat_date BETWEEN %s AND %s
          {clause}
        GROUP BY ads.affiliate_id, ai.manager, ai.group_type
        {having}
        ORDER BY {order_by} DESC
        LIMIT %s
        """,
        tuple([periods["week4_start"], periods["period_end"]] + extra + [TOP_PARTNERS_LIMIT]),
    )

    # total row
    if rows:
        total = {
            "affiliate_id":   "TOTAL",
            "manager":        "",
            "group_type":     "",
            "regs":           sum(int(r.get("regs") or 0) for r in rows),
            "ftd":            sum(int(r.get("ftd") or 0) for r in rows),
            "new_dep_amount": sum(float(r.get("new_dep_amount") or 0) for r in rows),
            "deposits_usd":   sum(float(r.get("deposits_usd") or 0) for r in rows),
            "conversion_pct": (
                round(sum(int(r.get("ftd") or 0) for r in rows) /
                      sum(int(r.get("regs") or 0) for r in rows) * 100, 1)
                if sum(int(r.get("regs") or 0) for r in rows) > 0 else 0
            ),
            "_is_total": True,
        }
        rows = list(rows) + [total]

    return rows


def fetch_block1_top_partners(periods: dict, focus_geo: list[str], affiliate_ids: list[int] | None = None) -> list[dict]:
    return _fetch_block1_base(periods, affiliate_ids, order_by="ftd")


def fetch_block1_top_by_deposits(periods: dict, focus_geo: list[str], affiliate_ids: list[int] | None = None) -> list[dict]:
    return _fetch_block1_base(periods, affiliate_ids, order_by="deposits_usd")


# ---------------------------------------------------------------------------
# Block 2 — Falling Partners
# ---------------------------------------------------------------------------

def fetch_block2_falling_partners(periods: dict, focus_geo: list[str], affiliate_ids: list[int] | None = None) -> list[dict]:
    """
    Partners where unique active depositors dropped vs 90-day ref (normalized to 1 week).
    Uses affiliate_daily_stats.active_players aggregate instead of raw bet_deposits
    for a major performance improvement.
    Drop = curr_week_active - ref_avg_per_week. Sorted by absolute drop.
    """
    clause = _aff_clause(affiliate_ids, alias="ads")
    extra  = [affiliate_ids] if affiliate_ids else []
    return execute_query(
        f"""
        WITH {_AFF_INFO_CTE},
        current_p AS (
            SELECT
                affiliate_id,
                SUM(active_players)                             AS players_curr,
                ROUND(SUM(deposits_amount_usd)::numeric, 0)    AS deposits_curr
            FROM aggregates.affiliate_daily_stats ads
            WHERE stat_date BETWEEN %s AND %s
              {clause}
            GROUP BY affiliate_id
        ),
        reference_p AS (
            SELECT
                affiliate_id,
                ROUND(SUM(active_players)::numeric / 90 * 7, 1) AS players_ref
            FROM aggregates.affiliate_daily_stats ads
            WHERE stat_date BETWEEN %s AND %s
              {clause}
            GROUP BY affiliate_id
        )
        SELECT
            c.affiliate_id,
            COALESCE(ai.manager, '—')                                   AS manager,
            COALESCE(ai.group_type, '—')                                AS group_type,
            r.players_ref                                               AS players_prev_period,
            c.players_curr                                              AS players_curr_period,
            ROUND((c.players_curr - r.players_ref)::numeric, 1)        AS players_drop,
            ROUND(((c.players_curr - r.players_ref)
                   / NULLIF(r.players_ref, 0) * 100)::numeric, 1)      AS change_pct,
            c.deposits_curr                                             AS deposits_usd
        FROM current_p c
        JOIN reference_p r ON r.affiliate_id = c.affiliate_id
        LEFT JOIN aff_info ai ON ai.affiliate_id = c.affiliate_id
        WHERE r.players_ref >= 1
          AND c.players_curr < r.players_ref
        ORDER BY players_drop ASC
        LIMIT %s
        """,
        tuple(
            [periods["week4_start"], periods["period_end"]] + extra +  # current_p
            [periods["ref_start"],   periods["ref_end"]]   + extra +   # reference_p
            [FALLING_PARTNERS_LIMIT]
        ),
    )


# ---------------------------------------------------------------------------
# Block 3 — New Partners
# ---------------------------------------------------------------------------

def fetch_block3_new_partners(periods: dict, focus_geo: list[str], affiliate_ids: list[int] | None = None) -> list[dict]:
    clause = _aff_clause(affiliate_ids, alias="ads")
    extra  = [affiliate_ids] if affiliate_ids else []
    return execute_query(
        f"""
        WITH {_AFF_INFO_CTE},
        first_seen AS (
            SELECT ads.affiliate_id, MIN(ads.stat_date) AS first_date
            FROM aggregates.affiliate_daily_stats ads
            WHERE True
              {clause}
            GROUP BY ads.affiliate_id
            HAVING MIN(ads.stat_date) >= %s
        ),
        current_p AS (
            SELECT
                ads.affiliate_id,
                SUM(ads.registrations_count)                        AS regs,
                SUM(ads.ftd_count)                                  AS ftd,
                ROUND(SUM(ads.new_players_deposit_sum)::numeric, 0) AS ftd_amount,
                ROUND(SUM(ads.deposits_amount_usd)::numeric, 0)     AS deposits_usd,
                CASE WHEN SUM(ads.registrations_count) > 0
                     THEN ROUND((SUM(ads.ftd_count)::numeric
                          / SUM(ads.registrations_count) * 100), 1)
                     ELSE 0 END AS conversion_pct
            FROM aggregates.affiliate_daily_stats ads
            WHERE ads.stat_date BETWEEN %s AND %s
              {clause}
            GROUP BY ads.affiliate_id
            HAVING SUM(ads.ftd_count) > 0
        )
        SELECT
            c.affiliate_id,
            COALESCE(ai.manager, '—')    AS manager,
            COALESCE(ai.group_type, '—') AS group_type,
            fs.first_date,
            c.regs, c.ftd, c.ftd_amount, c.deposits_usd, c.conversion_pct
        FROM current_p c
        JOIN first_seen fs ON fs.affiliate_id = c.affiliate_id
        LEFT JOIN aff_info ai ON ai.affiliate_id = c.affiliate_id
        ORDER BY c.ftd DESC
        LIMIT %s
        """,
        tuple(
            extra + [periods["new_partner_cutoff"]] +
            [periods["week4_start"], periods["period_end"]] + extra +
            [NEW_PARTNERS_LIMIT]
        ),
    )


# ---------------------------------------------------------------------------
# Block 4 — Reactivation
# ---------------------------------------------------------------------------

def fetch_block4_reactivations(periods: dict, focus_geo: list[str], affiliate_ids: list[int] | None = None) -> list[dict]:
    clause = _aff_clause(affiliate_ids, alias="ads")
    extra  = [affiliate_ids] if affiliate_ids else []
    return execute_query(
        f"""
        WITH {_AFF_INFO_CTE},
        reference_p AS (
            SELECT
                ads.affiliate_id,
                ROUND((SUM(ads.ftd_count)::numeric / 90 * 28), 2) AS ftd_ref_norm
            FROM aggregates.affiliate_daily_stats ads
            WHERE ads.stat_date BETWEEN %s AND %s
              {clause}
            GROUP BY ads.affiliate_id
        ),
        current_p AS (
            SELECT
                ads.affiliate_id,
                SUM(ads.ftd_count)                                  AS ftd,
                ROUND(SUM(ads.new_players_deposit_sum)::numeric, 0) AS ftd_amount,
                ROUND(SUM(ads.deposits_amount_usd)::numeric, 0)     AS deposits_usd,
                SUM(ads.registrations_count)                        AS regs
            FROM aggregates.affiliate_daily_stats ads
            WHERE ads.stat_date BETWEEN %s AND %s
              {clause}
            GROUP BY ads.affiliate_id
            HAVING SUM(ads.ftd_count) >= 1
        )
        SELECT
            c.affiliate_id,
            COALESCE(ai.manager, '—')    AS manager,
            COALESCE(ai.group_type, '—') AS group_type,
            c.ftd, c.ftd_amount, c.deposits_usd, c.regs,
            r.ftd_ref_norm
        FROM current_p c
        JOIN reference_p r ON r.affiliate_id = c.affiliate_id
        LEFT JOIN aff_info ai ON ai.affiliate_id = c.affiliate_id
        WHERE r.ftd_ref_norm <= 1
        ORDER BY c.ftd DESC
        LIMIT %s
        """,
        tuple(
            [periods["ref_start"],   periods["ref_end"]]   + extra +
            [periods["week4_start"], periods["period_end"]] + extra +
            [REACTIVATION_LIMIT]
        ),
    )


# ---------------------------------------------------------------------------
# Block 5 — Zero Activity
# ---------------------------------------------------------------------------

def fetch_block5_zero_activity(periods: dict, focus_geo: list[str], affiliate_ids: list[int] | None = None) -> list[dict]:
    clause = _aff_clause(affiliate_ids, alias="ads")
    extra  = [affiliate_ids] if affiliate_ids else []
    return execute_query(
        f"""
        WITH {_AFF_INFO_CTE},
        historical AS (
            SELECT
                ads.affiliate_id,
                ROUND(SUM(ads.deposits_amount_usd)::numeric, 0) AS hist_deposits
            FROM aggregates.affiliate_daily_stats ads
            WHERE ads.stat_date BETWEEN %s AND %s
              {clause}
            GROUP BY ads.affiliate_id
            HAVING SUM(ads.deposits_amount_usd) > 0
        ),
        current_p AS (
            SELECT ads.affiliate_id, SUM(ads.deposits_amount_usd) AS curr_deposits
            FROM aggregates.affiliate_daily_stats ads
            WHERE ads.stat_date BETWEEN %s AND %s
              {clause}
            GROUP BY ads.affiliate_id
        )
        SELECT
            h.affiliate_id,
            COALESCE(ai.manager, '—')    AS manager,
            COALESCE(ai.group_type, '—') AS group_type,
            h.hist_deposits,
            COALESCE(c.curr_deposits, 0) AS curr_deposits
        FROM historical h
        LEFT JOIN current_p c ON c.affiliate_id = h.affiliate_id
        LEFT JOIN aff_info ai ON ai.affiliate_id = h.affiliate_id
        WHERE COALESCE(c.curr_deposits, 0) = 0
        ORDER BY h.hist_deposits DESC
        LIMIT %s
        """,
        tuple(
            [periods["month12_start"], periods["ref_end"]]   + extra +
            [periods["week4_start"],   periods["period_end"]] + extra +
            [ZERO_ACTIVITY_LIMIT]
        ),
    )


# ---------------------------------------------------------------------------
# Block 5b — High Deposits, Zero FTD (new sub-block)
# ---------------------------------------------------------------------------

def fetch_block5_high_dep_no_ftd(periods: dict, affiliate_ids: list[int] | None = None) -> list[dict]:
    """
    Partners with top 15 deposits over last 4 weeks but 0 FTDs for the same period.
    """
    clause = _aff_clause(affiliate_ids, alias="ads")
    extra  = [affiliate_ids] if affiliate_ids else []
    return execute_query(
        f"""
        WITH {_AFF_INFO_CTE}
        SELECT
            ads.affiliate_id,
            COALESCE(ai.manager, '—')                           AS manager,
            COALESCE(ai.group_type, '—')                        AS group_type,
            ROUND(SUM(ads.deposits_amount_usd)::numeric, 0)     AS deposits_usd,
            SUM(ads.registrations_count)                        AS regs,
            SUM(ads.ftd_count)                                  AS ftd
        FROM aggregates.affiliate_daily_stats ads
        LEFT JOIN aff_info ai ON ai.affiliate_id = ads.affiliate_id
        WHERE ads.stat_date BETWEEN %s AND %s
          {clause}
        GROUP BY ads.affiliate_id, ai.manager, ai.group_type
        HAVING SUM(ads.ftd_count) = 0
           AND SUM(ads.deposits_amount_usd) > 0
        ORDER BY deposits_usd DESC
        LIMIT 15
        """,
        tuple([periods["week4_start"], periods["period_end"]] + extra),
    )


# ---------------------------------------------------------------------------
# Block 6.1 — Traffic Quality: Registrations without FTD
# ---------------------------------------------------------------------------

def fetch_block6_no_ftd(periods: dict, focus_geo: list[str], affiliate_ids: list[int] | None = None) -> list[dict]:
    clause = _aff_clause(affiliate_ids, alias="ads")
    extra  = [affiliate_ids] if affiliate_ids else []
    no_ftd_rows = execute_query(
        f"""
        SELECT ads.affiliate_id,
               SUM(ads.registrations_count)                     AS regs,
               ROUND(SUM(ads.deposits_amount_usd)::numeric, 0)  AS deposits_usd
        FROM aggregates.affiliate_daily_stats ads
        WHERE ads.stat_date BETWEEN %s AND %s
          {clause}
        GROUP BY ads.affiliate_id
        HAVING SUM(registrations_count) >= 5
           AND ROUND(SUM(ftd_count)::numeric / NULLIF(SUM(registrations_count), 0) * 100, 1) < 5
        ORDER BY regs DESC
        LIMIT %s
        """,
        tuple([periods["week4_start"], periods["period_end"]] + extra + [NO_FTD_LIMIT]),
    )

    if not no_ftd_rows:
        return []

    no_ftd_ids   = [r["affiliate_id"] for r in no_ftd_rows]
    deposits_map = {r["affiliate_id"]: r["deposits_usd"] for r in no_ftd_rows}

    cutoff_180 = periods["period_end"] - timedelta(days=179)

    check_rows = execute_query(
        """
        WITH reg_cohort AS (
            SELECT
                bu.affiliate_id,
                bu.bnu_id,
                bu.registration_date_time::date AS reg_date
            FROM public.bet_users bu
            WHERE bu.registration_date_time::date BETWEEN %s AND %s
              AND bu.country = ANY(%s)
              AND bu.affiliate_id = ANY(%s)
        ),
        ftd AS (
            SELECT
                rc.affiliate_id,
                rc.bnu_id,
                (bd.date_only - rc.reg_date) AS days_lag
            FROM reg_cohort rc
            JOIN public.bet_deposits bd
              ON bd.parent_id = rc.bnu_id
             AND bd.is_firstdep = true
             AND bd.status = 'OK'
             AND bd.date_only >= rc.reg_date
        )
        SELECT
            rc.affiliate_id,
            COUNT(DISTINCT rc.bnu_id)                                       AS cohort_regs,
            COUNT(DISTINCT ft.bnu_id)                                       AS check_alltime,
            COUNT(DISTINCT CASE WHEN ft.days_lag <= 0  THEN ft.bnu_id END)  AS check0,
            COUNT(DISTINCT CASE WHEN ft.days_lag <= 3  THEN ft.bnu_id END)  AS check3,
            COUNT(DISTINCT CASE WHEN ft.days_lag <= 7  THEN ft.bnu_id END)  AS check7,
            COUNT(DISTINCT CASE WHEN ft.days_lag <= 14 THEN ft.bnu_id END)  AS check14,
            COUNT(DISTINCT CASE WHEN ft.days_lag <= 30 THEN ft.bnu_id END)  AS check30
        FROM reg_cohort rc
        LEFT JOIN ftd ft ON ft.affiliate_id = rc.affiliate_id
                         AND ft.bnu_id = rc.bnu_id
        GROUP BY rc.affiliate_id
        """,
        (cutoff_180, periods["period_end"], focus_geo, no_ftd_ids),
    )

    checks_map = {r["affiliate_id"]: r for r in check_rows}

    result = []
    for row in no_ftd_rows:
        aff_id = row["affiliate_id"]
        ch = checks_map.get(aff_id, {})
        result.append({
            "affiliate_id":  aff_id,
            "regs":          row["regs"],
            "ftd":           0,
            "deposits_usd":  deposits_map.get(aff_id, 0),
            "cohort_regs":   ch.get("cohort_regs", 0),
            "check0":        ch.get("check0", 0),
            "check3":        ch.get("check3", 0),
            "check7":        ch.get("check7", 0),
            "check14":       ch.get("check14", 0),
            "check30":       ch.get("check30", 0),
            "check_alltime": ch.get("check_alltime", 0),
        })
    return result


# ---------------------------------------------------------------------------
# Block 6.2 — Traffic Quality: Conversion below GEO average
# ---------------------------------------------------------------------------

def fetch_block6_low_conversion(periods: dict, focus_geo: list[str], affiliate_ids: list[int] | None = None) -> list[dict]:
    clause = _aff_clause(affiliate_ids, alias="ads")
    extra  = [affiliate_ids] if affiliate_ids else []
    return execute_query(
        f"""
        WITH {_AFF_INFO_CTE},
        -- GEO avg computed across ALL partners (not filtered by manager)
        geo_avg AS (
            SELECT
                country,
                ROUND(SUM(ftd_count)::numeric / NULLIF(SUM(registrations_count), 0) * 100, 2) AS avg_conv_pct
            FROM aggregates.affiliate_daily_stats
            WHERE stat_date BETWEEN %s AND %s
              AND registrations_count >= 1
            GROUP BY country
            HAVING SUM(registrations_count) >= 10
        ),
        -- partner stats filtered by manager's affiliate_ids
        partner_stats AS (
            SELECT
                ads.affiliate_id,
                ads.country,
                SUM(ads.registrations_count) AS regs,
                SUM(ads.ftd_count)           AS ftd
            FROM aggregates.affiliate_daily_stats ads
            WHERE ads.stat_date BETWEEN %s AND %s
              {clause}
            GROUP BY ads.affiliate_id, ads.country
            HAVING SUM(ads.registrations_count) >= 10
        )
        SELECT
            ps.affiliate_id,
            COALESCE(ai.manager, '—')    AS manager,
            COALESCE(ai.group_type, '—') AS group_type,
            ps.country,
            ps.regs,
            ps.ftd,
            ROUND(ps.ftd::numeric / NULLIF(ps.regs, 0) * 100, 2) AS conversion_pct,
            ga.avg_conv_pct                                        AS geo_avg_conv_pct
        FROM partner_stats ps
        JOIN geo_avg ga ON ga.country = ps.country
        LEFT JOIN aff_info ai ON ai.affiliate_id = ps.affiliate_id
        WHERE (ps.ftd::numeric / NULLIF(ps.regs, 0) * 100) < ga.avg_conv_pct
          AND ps.ftd > 0
        ORDER BY (ps.ftd::numeric / NULLIF(ps.regs, 0) * 100 - ga.avg_conv_pct) ASC
        LIMIT %s
        """,
        tuple(
            [periods["week4_start"], periods["period_end"]] +        # geo_avg
            [periods["week4_start"], periods["period_end"]] + extra + # partner_stats
            [LOW_CONV_LIMIT]
        ),
    )


# ---------------------------------------------------------------------------
# Block 7 — Partner Activity
# ---------------------------------------------------------------------------

def fetch_block7_activity(periods: dict, focus_geo: list[str], affiliate_ids: list[int] | None = None) -> dict:
    """
    Returns:
      - all_partners: total from affiliate_partners by group
      - base_12m: partners with any activity in last 12 months by group
      - active_week: partners with dep >= $100 in current week by group
      - weekly_trend: last 12 weeks active count split by group
    """
    from collections import defaultdict
    clause     = _aff_clause(affiliate_ids, alias="ads")
    clause_ai  = _aff_clause(affiliate_ids, alias="ai")
    extra      = [affiliate_ids] if affiliate_ids else []

    # 1. All partners from affiliate_partners table by group_type
    all_rows = execute_query(
        f"""
        WITH {_AFF_INFO_CTE}
        SELECT
            COALESCE(ai.group_type, 'Other') AS group_type,
            COUNT(DISTINCT ai.affiliate_id)  AS cnt
        FROM aff_info ai
        WHERE True
          {clause_ai}
        GROUP BY ai.group_type
        """,
        tuple(extra),
    )
    all_by_group = {r["group_type"]: int(r["cnt"] or 0) for r in all_rows}

    # 2. 12-month active base: had any activity in last 12 months, by group
    base_rows = execute_query(
        f"""
        WITH {_AFF_INFO_CTE}
        SELECT
            COALESCE(ai.group_type, 'Other')    AS group_type,
            COUNT(DISTINCT src.affiliate_id)    AS cnt
        FROM (
            SELECT ads.affiliate_id
            FROM aggregates.affiliate_daily_stats ads
            WHERE ads.stat_date BETWEEN %s AND %s
              {clause}
            GROUP BY ads.affiliate_id
        ) src
        LEFT JOIN aff_info ai ON ai.affiliate_id = src.affiliate_id
        GROUP BY ai.group_type
        """,
        tuple([periods["month12_start"], periods["period_end"]] + extra),
    )
    base_by_group = {r["group_type"]: int(r["cnt"] or 0) for r in base_rows}

    # 3. Active this week: dep >= $100 in current week, by group
    active_rows = execute_query(
        f"""
        WITH {_AFF_INFO_CTE}
        SELECT
            COALESCE(ai.group_type, 'Other')    AS group_type,
            COUNT(DISTINCT src.affiliate_id)    AS cnt
        FROM (
            SELECT ads.affiliate_id, SUM(ads.deposits_amount_usd) AS deps
            FROM aggregates.affiliate_daily_stats ads
            WHERE ads.stat_date BETWEEN %s AND %s
              {clause}
            GROUP BY ads.affiliate_id
            HAVING SUM(ads.deposits_amount_usd) >= 100
        ) src
        LEFT JOIN aff_info ai ON ai.affiliate_id = src.affiliate_id
        GROUP BY ai.group_type
        """,
        tuple([periods["week4_start"], periods["period_end"]] + extra),
    )
    active_by_group = {r["group_type"]: int(r["cnt"] or 0) for r in active_rows}

    # Build per-group rows (Inbound, Acquisition)
    groups = ["Inbound", "Acquisition"]
    group_rows = []
    for gt in groups:
        base   = base_by_group.get(gt, 0)
        active = active_by_group.get(gt, 0)
        total  = all_by_group.get(gt, 0)
        group_rows.append({
            "group_type":         gt,
            "base_12m":           base,
            "all":                total,
            "active":             active,
            "pct_active":         round(active / base * 100, 1) if base else 0,
            "pct_active_to_all":  round(active / total * 100, 1) if total else 0,
        })

    # Totals
    t_base   = sum(r["base_12m"] for r in group_rows)
    t_all    = sum(r["all"]      for r in group_rows)
    t_active = sum(r["active"]   for r in group_rows)
    group_rows.append({
        "group_type":         "Total",
        "base_12m":           t_base,
        "all":                t_all,
        "active":             t_active,
        "pct_active":         round(t_active / t_base * 100, 1) if t_base else 0,
        "pct_active_to_all":  round(t_active / t_all * 100, 1) if t_all else 0,
    })

    # 4. Weekly trend: last 12 weeks, active (dep >= $100) per week by group
    week12_start = periods["period_end"] - timedelta(days=83)
    trend_rows = execute_query(
        f"""
        WITH {_AFF_INFO_CTE}
        SELECT
            DATE_TRUNC('week', ads.stat_date)::date     AS week_start,
            COALESCE(ai.group_type, 'Other')            AS group_type,
            COUNT(DISTINCT ads.affiliate_id)            AS active_count
        FROM (
            SELECT ads.affiliate_id, ads.stat_date, SUM(ads.deposits_amount_usd) AS deps
            FROM aggregates.affiliate_daily_stats ads
            WHERE ads.stat_date BETWEEN %s AND %s
              {clause}
            GROUP BY ads.affiliate_id, ads.stat_date
        ) ads
        LEFT JOIN aff_info ai ON ai.affiliate_id = ads.affiliate_id
        WHERE ads.deps >= 100
        GROUP BY DATE_TRUNC('week', ads.stat_date)::date, ai.group_type
        ORDER BY 1, 2
        """,
        tuple([week12_start, periods["period_end"]] + extra),
    )

    week_gt: dict = defaultdict(dict)
    week_set: list = []
    for r in trend_rows:
        ws  = r["week_start"]
        key = ws.isoformat() if hasattr(ws, "isoformat") else str(ws)[:10]
        gt  = r["group_type"] or "Other"
        week_gt[key][gt] = int(r["active_count"] or 0)
        if key not in week_set:
            week_set.append(key)

    weekly_trend = [
        {
            "week_start":  ws,
            "inbound":     week_gt[ws].get("Inbound", 0),
            "acquisition": week_gt[ws].get("Acquisition", 0),
        }
        for ws in week_set
    ]

    return {
        "base_12m":      t_base,
        "all_partners":  t_all,
        "active_week":   t_active,
        "pct_active":    round(t_active / t_base * 100, 1) if t_base else 0,
        "group_rows":    group_rows,
        "weekly_trend":  weekly_trend,
    }


def fetch_chart_monthly_deposits(periods: dict, affiliate_ids: list[int] | None = None) -> list[dict]:
    """12 months of deposits split by group_type (Inbound / Acquisition)."""
    clause = _aff_clause(affiliate_ids, alias="ads")
    extra  = [affiliate_ids] if affiliate_ids else []
    return execute_query(
        f"""
        WITH {_AFF_INFO_CTE}
        SELECT
            DATE_TRUNC('month', ads.stat_date)::date    AS month_start,
            COALESCE(ai.group_type, 'Other')            AS group_type,
            ROUND(SUM(ads.deposits_amount_usd)::numeric, 0) AS deposits_usd
        FROM aggregates.affiliate_daily_stats ads
        LEFT JOIN aff_info ai ON ai.affiliate_id = ads.affiliate_id
        WHERE ads.stat_date BETWEEN %s AND %s
          {clause}
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
        tuple([periods["month12_start"], periods["period_end"]] + extra),
    )


# ---------------------------------------------------------------------------
# Block 8 — Affiliate Totals (last 6 weeks, inbound vs acquisition)
# ---------------------------------------------------------------------------

def fetch_block8_totals_by_week(periods: dict, focus_geo: list[str], affiliate_ids: list[int] | None = None) -> list[dict]:
    """
    Weekly totals for last 6 weeks.
    Uses affiliate_weekly_stats aggregate directly (same source as Power BI)
    to guarantee NP Dep Sum matches PBI numbers.
    Filtered by affiliate_ids when manager is specified.
    """
    clause = _aff_clause(affiliate_ids, alias="aws")
    extra  = [affiliate_ids] if affiliate_ids else []
    p_start = periods["week6_start"]
    p_end   = periods["period_end"]
    return execute_query(
        f"""
        WITH {_AFF_INFO_CTE}
        SELECT
            aws.week_start::date                                        AS week_start,
            COALESCE(ai.manager, 'No Group')                            AS manager,
            COALESCE(ai.group_type, 'Other')                            AS group_type,
            SUM(aws.registrations_count)                                AS regs,
            SUM(aws.ftd_count)                                          AS ftd,
            ROUND(SUM(aws.new_players_deposit_sum)::numeric, 0)         AS ftd_amount,
            ROUND(SUM(aws.deposits_amount_usd)::numeric, 0)             AS deposits_usd,
            CASE WHEN SUM(aws.registrations_count) > 0
                 THEN ROUND(SUM(aws.ftd_count)::numeric
                      / NULLIF(SUM(aws.registrations_count), 0) * 100, 1)
                 ELSE 0 END                                             AS conversion_pct
        FROM aggregates.affiliate_weekly_stats aws
        LEFT JOIN aff_info ai ON ai.affiliate_id = aws.affiliate_id
        WHERE aws.week_start::date BETWEEN %s AND %s
          {clause}
        GROUP BY aws.week_start::date, ai.manager, ai.group_type
        ORDER BY aws.week_start::date, ai.manager, ai.group_type
        """,
        tuple([p_start, p_end] + extra),
    )


# ---------------------------------------------------------------------------
# Block 9 — Month Comparison
# ---------------------------------------------------------------------------

def fetch_block9_month_comparison(periods: dict, affiliate_ids: list[int] | None = None) -> dict:
    """
    FTD, FTD amount, deposits split by group_type (Inbound / Acquisition / Total).
    Periods: prev2 month, prev1 month, current MTD.
    All periods use affiliate_monthly_stats for consistent NP Dep Sum logic
    (all deposits of new player within their FTD month, same as Power BI).
    """
    clause_ams = _aff_clause(affiliate_ids, alias="ams")
    extra      = [affiliate_ids] if affiliate_ids else []

    def _fetch_month(month_start: date) -> list[dict]:
        return execute_query(
            f"""
            WITH {_AFF_INFO_CTE}
            SELECT
                COALESCE(ai.group_type, 'Other')                          AS group_type,
                SUM(ams.ftd_count)                                        AS ftd,
                ROUND(SUM(ams.new_players_deposit_sum)::numeric, 0)       AS ftd_amount,
                ROUND(SUM(ams.deposits_amount_usd)::numeric, 0)           AS deposits_usd
            FROM aggregates.affiliate_monthly_stats ams
            LEFT JOIN aff_info ai ON ai.affiliate_id = ams.affiliate_id
            WHERE ams.month_start = %s
              {clause_ams}
            GROUP BY ai.group_type
            ORDER BY ai.group_type
            """,
            tuple([month_start] + extra),
        )

    def _index(rows: list[dict]) -> dict:
        return {r["group_type"]: r for r in rows}

    prev2 = _index(_fetch_month(periods["prev2_month_start"]))
    prev1 = _index(_fetch_month(periods["prev_month_start"]))
    mtd   = _index(_fetch_month(periods["current_month_start"]))

    days_elapsed  = periods["days_elapsed"]
    days_in_month = periods["days_in_month"]

    def _pct(a: float, b: float) -> float | None:
        return round((a - b) / b * 100, 1) if b else None

    result = {}
    for group in ("Inbound", "Acquisition", "Other"):
        p2 = prev2.get(group, {})
        p1 = prev1.get(group, {})
        m  = mtd.get(group, {})
        result[group] = {}
        for metric in ("ftd", "ftd_amount", "deposits_usd"):
            p2_val  = float(p2.get(metric) or 0)
            p1_val  = float(p1.get(metric) or 0)
            mtd_val = float(m.get(metric)  or 0)
            projected = round(mtd_val / days_elapsed * days_in_month, 0) if days_elapsed else 0
            result[group][metric] = {
                "prev2":     p2_val,
                "prev1":     p1_val,
                "mtd":       mtd_val,
                "projected": projected,
                "vs_prev1":  _pct(projected, p1_val),
            }

    # Total = Inbound + Acquisition + Other
    result["Total"] = {}
    for metric in ("ftd", "ftd_amount", "deposits_usd"):
        base_groups = ("Inbound", "Acquisition", "Other")
        t_prev2 = sum(result[g][metric]["prev2"] for g in base_groups)
        t_prev1 = sum(result[g][metric]["prev1"] for g in base_groups)
        t_mtd   = sum(result[g][metric]["mtd"]   for g in base_groups)
        t_proj  = round(t_mtd / days_elapsed * days_in_month, 0) if days_elapsed else 0
        result["Total"][metric] = {
            "prev2":     t_prev2,
            "prev1":     t_prev1,
            "mtd":       t_mtd,
            "projected": t_proj,
            "vs_prev1":  _pct(t_proj, t_prev1),
        }

    return result


# ---------------------------------------------------------------------------
# Main collector
# ---------------------------------------------------------------------------

def collect_weekly_metrics(report_date: date, focus_geo: list[str], manager_group: str | None = None) -> dict:
    """Collect all 9 blocks for the affiliate weekly GEO report."""
    periods = get_report_periods(report_date)
    names   = load_manager_names()

    # Per-manager filtering
    affiliate_ids: list[int] | None = None
    if manager_group:
        affiliate_ids = fetch_manager_affiliate_ids(manager_group)
        if not affiliate_ids:
            logger.warning("No affiliate IDs found for manager '%s'", manager_group)

    mgr_key = manager_group.lower().strip() if manager_group else None

    def _mgr_filter(rows: list[dict]) -> list[dict]:
        """Post-filter rows by manager group name (before enrichment)."""
        if not mgr_key:
            return rows
        return [r for r in rows if r.get("manager", "").lower().strip() == mgr_key]

    def _mgr_filter_by_id(rows: list[dict]) -> list[dict]:
        """Post-filter rows by affiliate_id (for blocks without manager column)."""
        if affiliate_ids is None:
            return rows
        id_set = set(affiliate_ids)
        return [r for r in rows if r.get("affiliate_id") in id_set]

    logger.info(
        "Collecting affiliate weekly metrics | date=%s | geo=%s | 4w: %s..%s"
        " | manager=%s | aff_ids=%s | name_map=%d entries",
        report_date, focus_geo, periods["week4_start"], periods["period_end"],
        manager_group or "ALL",
        len(affiliate_ids) if affiliate_ids else "ALL",
        len(names),
    )

    block1 = enrich_rows(fetch_block1_top_partners(periods, focus_geo, affiliate_ids=affiliate_ids), names)
    logger.info("Block 1 Top Partners (FTD): %d rows", len(block1))

    block1_top_dep = enrich_rows(fetch_block1_top_by_deposits(periods, focus_geo, affiliate_ids=affiliate_ids), names)
    logger.info("Block 1 Top Partners (Deposits): %d rows", len(block1_top_dep))

    block2 = enrich_rows(fetch_block2_falling_partners(periods, focus_geo, affiliate_ids=affiliate_ids), names)
    logger.info("Block 2 Falling Partners: %d rows", len(block2))

    block3 = enrich_rows(fetch_block3_new_partners(periods, focus_geo, affiliate_ids=affiliate_ids), names)
    logger.info("Block 3 New Partners: %d rows", len(block3))

    block4 = enrich_rows(fetch_block4_reactivations(periods, focus_geo, affiliate_ids=affiliate_ids), names)
    logger.info("Block 4 Reactivations: %d rows", len(block4))

    block5 = enrich_rows(fetch_block5_zero_activity(periods, focus_geo, affiliate_ids=affiliate_ids), names)
    logger.info("Block 5 Zero Activity: %d rows", len(block5))

    block5b = enrich_rows(fetch_block5_high_dep_no_ftd(periods, affiliate_ids=affiliate_ids), names)
    logger.info("Block 5b High Dep No FTD: %d rows", len(block5b))

    block6_no_ftd = fetch_block6_no_ftd(periods, focus_geo, affiliate_ids=affiliate_ids)
    logger.info("Block 6.1 No-FTD: %d rows", len(block6_no_ftd))

    block6_low_conv = enrich_rows(fetch_block6_low_conversion(periods, focus_geo, affiliate_ids=affiliate_ids), names)
    logger.info("Block 6.2 Low Conversion: %d rows", len(block6_low_conv))

    block7 = fetch_block7_activity(periods, focus_geo, affiliate_ids=affiliate_ids)
    logger.info("Block 7 Activity: base_12m=%d all=%d active_week=%d", block7["base_12m"], block7["all_partners"], block7["active_week"])

    block8 = enrich_rows(fetch_block8_totals_by_week(periods, focus_geo, affiliate_ids=affiliate_ids), names)
    logger.info("Block 8 Weekly Totals: %d rows", len(block8))

    block9 = fetch_block9_month_comparison(periods, affiliate_ids=affiliate_ids)
    logger.info("Block 9 Month Comparison: groups=%s", list(block9.keys()))

    chart_monthly = fetch_chart_monthly_deposits(periods, affiliate_ids=affiliate_ids)
    logger.info("Chart monthly: %d rows", len(chart_monthly))

    # Resolve manager label for report header
    manager_label = names.get(manager_group.lower().strip(), manager_group) if manager_group else "All Managers"

    return {
        "report_date":     report_date,
        "focus_geo":       focus_geo,
        "periods":         periods,
        "manager_group":   manager_group,
        "manager_label":   manager_label,
        "block1":          block1,
        "block1_top_dep":  block1_top_dep,
        "block2":          block2,
        "block3":          block3,
        "block4":          block4,
        "block5":          block5,
        "block5b":         block5b,
        "block6_no_ftd":   block6_no_ftd,
        "block6_low_conv": block6_low_conv,
        "block7":          block7,
        "block8":          block8,
        "block9":          block9,
        "chart_monthly":   chart_monthly,
    }
