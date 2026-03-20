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
        SELECT user_id AS player_id,
               ROUND((SUM(winnings_usd) - SUM(turnover_usd))::numeric, 0) AS amount_usd,
               ROUND(SUM(winnings_usd)::numeric, 0)  AS winnings_usd,
               ROUND(SUM(turnover_usd)::numeric, 0)  AS bets_usd
        FROM aggregates.daily_player_casino_totals
        WHERE stat_date = %s
        GROUP BY user_id
        HAVING SUM(winnings_usd) - SUM(turnover_usd) > 0
        ORDER BY amount_usd DESC
        LIMIT %s
        """,
        (target_date, limit),
    )
    return [
        {
            "player_id":   r["player_id"],
            "amount_usd":  float(r["amount_usd"] or 0),
            "winnings":    float(r["winnings_usd"] or 0),
            "bets":        float(r["bets_usd"] or 0),
        }
        for r in rows
    ]


def _top_sport_profit(target_date: date, limit: int = 5) -> list[dict]:
    """Top N players by sport profit (winnings - bets), profit > 0."""
    rows = execute_query(
        """
        SELECT user_id AS player_id,
               ROUND((SUM(winnings_usd) - SUM(turnover_usd))::numeric, 0) AS amount_usd,
               ROUND(SUM(winnings_usd)::numeric, 0)  AS winnings_usd,
               ROUND(SUM(turnover_usd)::numeric, 0)  AS bets_usd
        FROM aggregates.daily_player_sport_totals
        WHERE stat_date = %s
        GROUP BY user_id
        HAVING SUM(winnings_usd) - SUM(turnover_usd) > 0
        ORDER BY amount_usd DESC
        LIMIT %s
        """,
        (target_date, limit),
    )
    return [
        {
            "player_id":   r["player_id"],
            "amount_usd":  float(r["amount_usd"] or 0),
            "winnings":    float(r["winnings_usd"] or 0),
            "bets":        float(r["bets_usd"] or 0),
        }
        for r in rows
    ]


def _top_casino_winnings(target_date: date) -> list[dict]:
    rows = execute_query(
        """
        SELECT user_id AS player_id,
               ROUND(SUM(winnings_usd)::numeric, 0) AS amount_usd
        FROM aggregates.daily_player_casino_totals
        WHERE stat_date = %s
        GROUP BY user_id
        ORDER BY amount_usd DESC
        LIMIT 5
        """,
        (target_date,),
    )
    return [{"player_id": r["player_id"], "amount_usd": float(r["amount_usd"] or 0)} for r in rows]


def _top_sport_winnings(target_date: date) -> list[dict]:
    rows = execute_query(
        """
        SELECT user_id AS player_id,
               ROUND(SUM(winnings_usd)::numeric, 0) AS amount_usd
        FROM aggregates.daily_player_sport_totals
        WHERE stat_date = %s
        GROUP BY user_id
        ORDER BY amount_usd DESC
        LIMIT 5
        """,
        (target_date,),
    )
    return [{"player_id": r["player_id"], "amount_usd": float(r["amount_usd"] or 0)} for r in rows]


def _top_deposits(target_date: date, limit: int = 5) -> list[dict]:
    rows = execute_query(
        """
        SELECT parent_id AS player_id,
               ROUND(SUM(converted_amount)::numeric, 0) AS amount_usd
        FROM public.bet_deposits
        WHERE date_only = %s
          AND status = 'OK'
          AND converted_amount > 0
        GROUP BY parent_id
        ORDER BY amount_usd DESC
        LIMIT %s
        """,
        (target_date, limit),
    )
    return [{"player_id": r["player_id"], "amount_usd": float(r["amount_usd"] or 0)} for r in rows]


def _top_withdrawals(target_date: date, limit: int = 5) -> list[dict]:
    rows = execute_query(
        """
        SELECT parent_id AS player_id,
               ROUND(SUM(converted_amount)::numeric, 0) AS amount_usd
        FROM public.bet_withdrawals
        WHERE date_only = %s
          AND status = 'Approved'
          AND converted_amount > 0
        GROUP BY parent_id
        ORDER BY amount_usd DESC
        LIMIT %s
        """,
        (target_date, limit),
    )
    return [{"player_id": r["player_id"], "amount_usd": float(r["amount_usd"] or 0)} for r in rows]
