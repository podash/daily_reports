"""
Fetch Top 5 players for the daily / risk report from PostgreSQL.

Sources:
  - Casino winnings/profit: aggregates.daily_player_casino_totals
  - Sport winnings/profit:  aggregates.daily_player_sport_totals
  - Deposits:               public.bet_deposits  (status = 'OK')
  - Withdrawals:            public.bet_withdrawals (status = 'Approved')

Player profit = winnings_usd - turnover_usd = -ggr_usd
"""

import logging
from datetime import date

from db_client import execute_query

logger = logging.getLogger(__name__)


def fetch_top_players(target_date: date) -> dict:
    """Return top 5 players by winnings for the daily report."""
    casino = _top_casino_winnings(target_date)
    sport  = _top_sport_winnings(target_date)
    deps   = _top_deposits(target_date)
    wds    = _top_withdrawals(target_date)

    logger.info("Top casino winnings: %d rows (date=%s)", len(casino), target_date)
    logger.info("Top sport winnings: %d rows (date=%s)",  len(sport),  target_date)
    logger.info("Top deposits: %d rows",                  len(deps))
    logger.info("Top withdrawals: %d rows",               len(wds))

    return {
        "casino":      casino,
        "sport":       sport,
        "deposits":    deps,
        "withdrawals": wds,
        "date":        target_date,
    }


def fetch_top_players_profit(target_date: date, limit: int = 5) -> dict:
    """Return top players by profit for the risk report."""
    casino = _top_casino_profit(target_date, limit=5)
    sport  = _top_sport_profit(target_date, limit=10)
    deps   = _top_deposits(target_date, limit=5)
    wds    = _top_withdrawals(target_date, limit=10)

    logger.info("Top casino profit: %d rows (date=%s)", len(casino), target_date)
    logger.info("Top sport profit: %d rows (date=%s)",  len(sport),  target_date)
    logger.info("Top deposits: %d rows",                len(deps))
    logger.info("Top withdrawals: %d rows",             len(wds))

    return {
        "casino":      casino,
        "sport":       sport,
        "deposits":    deps,
        "withdrawals": wds,
        "date":        target_date,
    }


def _top_casino_profit(target_date: date, limit: int = 5) -> list[dict]:
    """Top N players by casino profit (winnings - bets), profit > 0."""
    rows = execute_query(
        """
        SELECT t.user_id AS player_id,
               ROUND((SUM(t.winnings_usd) - SUM(t.turnover_usd))::numeric, 0) AS amount_usd,
               ROUND(SUM(t.winnings_usd)::numeric, 0)  AS winnings_usd,
               ROUND(SUM(t.turnover_usd)::numeric, 0)  AS bets_usd,
               bu.currency_code,
               bu.affiliate_id
        FROM aggregates.daily_player_casino_totals t
        LEFT JOIN aggregates.player_profile pp ON pp.user_id = t.user_id
        LEFT JOIN public.bet_users bu ON bu.bnu_id = t.user_id
        WHERE t.stat_date = %s
          AND COALESCE(pp.is_partner, false) = false
        GROUP BY t.user_id, bu.currency_code, bu.affiliate_id
        HAVING SUM(t.winnings_usd) - SUM(t.turnover_usd) > 0
        ORDER BY amount_usd DESC
        LIMIT %s
        """,
        (target_date, limit),
    )
    return [
        {
            "player_id":    r["player_id"],
            "amount_usd":   float(r["amount_usd"] or 0),
            "winnings":     float(r["winnings_usd"] or 0),
            "bets":         float(r["bets_usd"] or 0),
            "currency":     r["currency_code"] or "",
            "affiliate_id": r["affiliate_id"] or "",
        }
        for r in rows
    ]


def _top_sport_profit(target_date: date, limit: int = 5) -> list[dict]:
    """Top N players by sport profit (winnings - bets), profit > 0."""
    rows = execute_query(
        """
        SELECT t.user_id AS player_id,
               ROUND((SUM(t.winnings_usd) - SUM(t.turnover_usd))::numeric, 0) AS amount_usd,
               ROUND(SUM(t.winnings_usd)::numeric, 0)  AS winnings_usd,
               ROUND(SUM(t.turnover_usd)::numeric, 0)  AS bets_usd,
               bu.currency_code,
               bu.affiliate_id
        FROM aggregates.daily_player_sport_totals t
        LEFT JOIN aggregates.player_profile pp ON pp.user_id = t.user_id
        LEFT JOIN public.bet_users bu ON bu.bnu_id = t.user_id
        WHERE t.stat_date = %s
          AND COALESCE(pp.is_partner, false) = false
        GROUP BY t.user_id, bu.currency_code, bu.affiliate_id
        HAVING SUM(t.winnings_usd) - SUM(t.turnover_usd) > 0
        ORDER BY amount_usd DESC
        LIMIT %s
        """,
        (target_date, limit),
    )
    return [
        {
            "player_id":    r["player_id"],
            "amount_usd":   float(r["amount_usd"] or 0),
            "winnings":     float(r["winnings_usd"] or 0),
            "bets":         float(r["bets_usd"] or 0),
            "currency":     r["currency_code"] or "",
            "affiliate_id": r["affiliate_id"] or "",
        }
        for r in rows
    ]


def _top_casino_winnings(target_date: date) -> list[dict]:
    rows = execute_query(
        """
        SELECT t.user_id AS player_id,
               ROUND(SUM(t.winnings_usd)::numeric, 0) AS amount_usd
        FROM aggregates.daily_player_casino_totals t
        LEFT JOIN aggregates.player_profile pp ON pp.user_id = t.user_id
        WHERE t.stat_date = %s
          AND COALESCE(pp.is_partner, false) = false
        GROUP BY t.user_id
        ORDER BY amount_usd DESC
        LIMIT 5
        """,
        (target_date,),
    )
    return [{"player_id": r["player_id"], "amount_usd": float(r["amount_usd"] or 0)} for r in rows]


def _top_sport_winnings(target_date: date) -> list[dict]:
    rows = execute_query(
        """
        SELECT t.user_id AS player_id,
               ROUND(SUM(t.winnings_usd)::numeric, 0) AS amount_usd
        FROM aggregates.daily_player_sport_totals t
        LEFT JOIN aggregates.player_profile pp ON pp.user_id = t.user_id
        WHERE t.stat_date = %s
          AND COALESCE(pp.is_partner, false) = false
        GROUP BY t.user_id
        ORDER BY amount_usd DESC
        LIMIT 5
        """,
        (target_date,),
    )
    return [{"player_id": r["player_id"], "amount_usd": float(r["amount_usd"] or 0)} for r in rows]


def _top_deposits(target_date: date, limit: int = 5) -> list[dict]:
    rows = execute_query(
        """
        SELECT bd.parent_id AS player_id,
               ROUND(SUM(bd.converted_amount)::numeric, 0) AS amount_usd,
               bu.currency_code,
               bu.affiliate_id
        FROM public.bet_deposits bd
        LEFT JOIN aggregates.player_profile pp ON pp.user_id = bd.parent_id
        LEFT JOIN public.bet_users bu ON bu.bnu_id = bd.parent_id
        WHERE bd.date_only = %s
          AND bd.status = 'OK'
          AND bd.converted_amount > 0
          AND COALESCE(pp.is_partner, false) = false
        GROUP BY bd.parent_id, bu.currency_code, bu.affiliate_id
        ORDER BY amount_usd DESC
        LIMIT %s
        """,
        (target_date, limit),
    )
    return [
        {
            "player_id":    r["player_id"],
            "amount_usd":   float(r["amount_usd"] or 0),
            "currency":     r["currency_code"] or "",
            "affiliate_id": r["affiliate_id"] or "",
        }
        for r in rows
    ]


def _top_withdrawals(target_date: date, limit: int = 5) -> list[dict]:
    rows = execute_query(
        """
        SELECT bw.parent_id AS player_id,
               ROUND(SUM(bw.converted_amount)::numeric, 0) AS amount_usd,
               bu.currency_code,
               bu.affiliate_id
        FROM public.bet_withdrawals bw
        LEFT JOIN aggregates.player_profile pp ON pp.user_id = bw.parent_id
        LEFT JOIN public.bet_users bu ON bu.bnu_id = bw.parent_id
        WHERE bw.date_only = %s
          AND bw.status = 'Approved'
          AND bw.converted_amount > 0
          AND COALESCE(pp.is_partner, false) = false
        GROUP BY bw.parent_id, bu.currency_code, bu.affiliate_id
        ORDER BY amount_usd DESC
        LIMIT %s
        """,
        (target_date, limit),
    )
    return [
        {
            "player_id":    r["player_id"],
            "amount_usd":   float(r["amount_usd"] or 0),
            "currency":     r["currency_code"] or "",
            "affiliate_id": r["affiliate_id"] or "",
        }
        for r in rows
    ]
