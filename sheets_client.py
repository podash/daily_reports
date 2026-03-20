"""
Fetch daily metrics from Google Sheets 'Daily Report' worksheet.

Columns in the sheet (EUR values):
  [0]  Day of week
  [1]  Date (DD.MM.YYYY)
  [5]  Registrations
  [6]  FTD
  [7]  Deposits EUR
  [8]  Withdrawals EUR
  [9]  CashFlow EUR
  [10] Deposits no commission
  [11] Withdrawals no commission
  [12] Balance with commissions
  [13] Turnover Sports EUR
  [14] Win Sports EUR
  [15] GGR Sports EUR
  [16] Turnover Casino EUR
  [17] Win Casino EUR
  [18] GGR Casino EUR
  [19] Total Turnover EUR
  [20] Total Win EUR
  [21] GGR EUR (total)
  [22] Promo
  [23] Bonus Sports
  [24] Bonus Casino
"""

import logging
from datetime import date, datetime, timedelta
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

from calendar import monthrange
from config import GOOGLE_SHEETS_URL, GOOGLE_CREDENTIALS_PATH, ALERT_THRESHOLD_PCT, TOP_COUNTRIES_LIMIT

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

WORKSHEET_NAME = "Daily Report"
WORKSHEET_DEPOSITS = "Deposits&Withdraws"
WORKSHEET_TURNOVER = "Turnover by country"
WORKSHEET_DEP_COUNTRY = "Dep_country"
WORKSHEET_REG_FTD_DATA = " Registation - FTD DATA"

COUNTRY_ALERT_THRESHOLD_PCT = 30
COUNTRY_ALERT_MIN_REGS = 10

FOCUS_MARKETS = {
    "Europe": ["Portugal", "Germany", "Austria", "Slovenia", "Latvia", "Poland", "Spain", "Canada"],
    "Asia": ["Turkey", "Azerbaijan", "Uzbekistan", "India", "Bangladesh"],
    "LatAm": ["Chile", "Peru", "Argentina", "Colombia"],
    "Arab": ["Morocco", "Egypt"],
}


# ------------------------------------------------------------------
# Parsing helpers
# ------------------------------------------------------------------

def _parse_number(val: str) -> float:
    """Parse a number string with non-breaking spaces, commas, etc."""
    if not val or val.strip() == "":
        return 0.0
    cleaned = val.replace("\xa0", "").replace(" ", "").replace("\u202f", "")
    # Handle European decimal comma: if there's a comma and no dot, treat comma as decimal
    if "," in cleaned and "." not in cleaned:
        cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _parse_date(val: str) -> date | None:
    """Parse DD.MM.YYYY date string."""
    try:
        return datetime.strptime(val.strip(), "%d.%m.%Y").date()
    except (ValueError, AttributeError):
        return None


# ------------------------------------------------------------------
# Fetch data
# ------------------------------------------------------------------

def _connect():
    creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_PATH, scopes=SCOPES)
    return gspread.authorize(creds)


def _load_all_rows(client) -> list[dict]:
    """Load all rows from the Daily Report worksheet and parse into dicts."""
    spreadsheet = client.open_by_url(GOOGLE_SHEETS_URL)
    ws = spreadsheet.worksheet(WORKSHEET_NAME)
    raw = ws.get_all_values()

    rows = []
    for row in raw[1:]:  # skip header
        if len(row) < 22:
            continue
        d = _parse_date(row[1])
        if d is None:
            continue
        deposits = _parse_number(row[7])
        if deposits == 0 and _parse_number(row[5]) == 0 and _parse_number(row[15]) == 0:
            continue  # empty future row

        rows.append({
            "stat_date": d,
            "day_of_week": row[0],
            "registrations": int(_parse_number(row[5])),
            "ftd": int(_parse_number(row[6])),
            "deposits": _parse_number(row[7]),
            "withdrawals": _parse_number(row[8]),
            "cash_flow": _parse_number(row[9]),
            "deposits_no_comm": _parse_number(row[10]),
            "withdrawals_no_comm": _parse_number(row[11]),
            "balance_with_comm": _parse_number(row[12]),
            "sport_turnover": _parse_number(row[13]),
            "sport_win": _parse_number(row[14]),
            "sport_ggr": _parse_number(row[15]),
            "casino_turnover": _parse_number(row[16]),
            "casino_win": _parse_number(row[17]),
            "casino_ggr": _parse_number(row[18]),
            "total_turnover": _parse_number(row[19]),
            "total_win": _parse_number(row[20]),
            "total_ggr": _parse_number(row[21]),
            "promo": _parse_number(row[22]) if len(row) > 22 else 0.0,
        })

    logger.info("Loaded %d rows from Google Sheets", len(rows))
    return rows


def _find_row(rows: list[dict], target: date) -> dict | None:
    for r in rows:
        if r["stat_date"] == target:
            return r
    return None


# ------------------------------------------------------------------
# MTD & Plan data
# ------------------------------------------------------------------

def _compute_mtd(rows: list[dict], target_date: date) -> dict:
    """Sum metrics from the 1st of the month through target_date."""
    first_of_month = target_date.replace(day=1)
    mtd_rows = [r for r in rows if first_of_month <= r["stat_date"] <= target_date]

    if not mtd_rows:
        return {}

    return {
        "days_elapsed": len(mtd_rows),
        "days_in_month": _days_in_month(target_date),
        "registrations": sum(r["registrations"] for r in mtd_rows),
        "ftd": sum(r["ftd"] for r in mtd_rows),
        "deposits": sum(r["deposits"] for r in mtd_rows),
        "withdrawals": sum(r["withdrawals"] for r in mtd_rows),
        "cash_flow": sum(r["cash_flow"] for r in mtd_rows),
        "total_turnover": sum(r["total_turnover"] for r in mtd_rows),
        "total_ggr": sum(r["total_ggr"] for r in mtd_rows),
        "promo": sum(r["promo"] for r in mtd_rows),
        "ggr_net_promo": sum(r.get("total_ggr", 0) + r.get("promo", 0) for r in mtd_rows),
        "sport_ggr": sum(r["sport_ggr"] for r in mtd_rows),
        "casino_ggr": sum(r["casino_ggr"] for r in mtd_rows),
        "sport_turnover": sum(r["sport_turnover"] for r in mtd_rows),
        "casino_turnover": sum(r["casino_turnover"] for r in mtd_rows),
    }


def _compute_prev_month_totals(rows: list[dict], target_date: date) -> dict:
    """Sum metrics for the entire previous month."""
    prev_month = target_date.month - 1 if target_date.month > 1 else 12
    prev_year = target_date.year if target_date.month > 1 else target_date.year - 1
    days_prev = monthrange(prev_year, prev_month)[1]
    prev_start = date(prev_year, prev_month, 1)
    prev_end = date(prev_year, prev_month, days_prev)

    prev_rows = [r for r in rows if prev_start <= r["stat_date"] <= prev_end]
    if not prev_rows:
        return {}

    return {
        "deposits": sum(r["deposits"] for r in prev_rows),
        "total_ggr": sum(r["total_ggr"] for r in prev_rows),
        "registrations": sum(r["registrations"] for r in prev_rows),
        "ftd": sum(r["ftd"] for r in prev_rows),
        "withdrawals": sum(r["withdrawals"] for r in prev_rows),
        "cash_flow": sum(r["cash_flow"] for r in prev_rows),
        "total_turnover": sum(r["total_turnover"] for r in prev_rows),
        "promo": sum(r["promo"] for r in prev_rows),
        "ggr_net_promo": sum(r.get("total_ggr", 0) + r.get("promo", 0) for r in prev_rows),
        "sport_ggr": sum(r["sport_ggr"] for r in prev_rows),
        "casino_ggr": sum(r["casino_ggr"] for r in prev_rows),
        "sport_turnover": sum(r["sport_turnover"] for r in prev_rows),
        "casino_turnover": sum(r["casino_turnover"] for r in prev_rows),
    }


def _days_in_month(d: date) -> int:
    if d.month == 12:
        next_month = d.replace(year=d.year + 1, month=1, day=1)
    else:
        next_month = d.replace(month=d.month + 1, day=1)
    return (next_month - d.replace(day=1)).days


def _fetch_country_deposits(client, target_date: date) -> dict:
    """
    Fetch deposits by country from 'Dep_country' sheet.

    Returns dict with:
      - today: list of {country, deposits} for target_date
      - yesterday: same for prev day
      - mtd: list of {country, deposits} (MTD totals)
      - plan: list of {country, deposits_plan}
      - prev_months: {jan: [...], dec: [...], nov: [...]}
    """
    spreadsheet = client.open_by_url(GOOGLE_SHEETS_URL)
    result = {"today": [], "yesterday": [], "mtd": [], "plan": [], "prev_months": {}}

    try:
        ws = spreadsheet.worksheet(WORKSHEET_DEP_COUNTRY)
        data = ws.get_all_values()
    except Exception as e:
        logger.warning("Failed to read Dep_country: %s", e)
        return result

    # Row 4 has country names as headers
    if len(data) < 15:
        return result

    header_row = data[4]
    # Countries start from col 1, end before "Загальний результат"
    countries = []
    for i in range(1, len(header_row)):
        name = header_row[i].strip()
        if not name or name.startswith("Загальний") or name.startswith("Agents"):
            break
        countries.append((i, name))

    # Parse daily rows (rows 5+): [0]=date, [1..N]=country deposits
    daily_by_date = {}
    for row in data[5:]:
        d = _parse_date(row[0])
        if d is None:
            continue
        country_vals = {}
        for col_idx, country_name in countries:
            if col_idx < len(row):
                country_vals[country_name] = _parse_number(row[col_idx])
        daily_by_date[d] = country_vals

    # Today
    if target_date in daily_by_date:
        today_vals = daily_by_date[target_date]
        result["today"] = [
            {"country": c, "deposits": today_vals.get(c, 0)}
            for _, c in countries
        ]
        result["today"].sort(key=lambda x: x["deposits"], reverse=True)

    # Yesterday
    prev_day = target_date - timedelta(days=1)
    if prev_day in daily_by_date:
        prev_vals = daily_by_date[prev_day]
        result["yesterday"] = [
            {"country": c, "deposits": prev_vals.get(c, 0)}
            for _, c in countries
        ]

    month_names_ru = {
        1: "январь", 2: "февраль", 3: "март", 4: "апрель",
        5: "май", 6: "июнь", 7: "июль", 8: "август",
        9: "сентябрь", 10: "октябрь", 11: "ноябрь", 12: "декабрь",
    }
    cur_month = target_date.month
    cur_month_ru = month_names_ru[cur_month]
    prev1 = month_names_ru[(cur_month - 2) % 12 + 1]
    prev2 = month_names_ru[(cur_month - 3) % 12 + 1]
    prev3 = month_names_ru[(cur_month - 4) % 12 + 1]

    named_rows = {}
    row_labels = {
        "mtd": ["загальний результат", f"{cur_month_ru} факт"],
        "plan": [f"{cur_month_ru} прогноз"],
        "prev1": [prev1],
        "prev2": [prev2],
        "prev3": [prev3],
    }
    for row in data:
        if not row or not row[0]:
            continue
        label = row[0].strip().lower()
        for key, patterns in row_labels.items():
            if any(p in label for p in patterns):
                if key not in named_rows:
                    named_rows[key] = row
                break

    def _extract_countries(row_data):
        items = []
        for col_idx, country_name in countries:
            val = _parse_number(row_data[col_idx]) if col_idx < len(row_data) else 0
            items.append({"country": country_name, "deposits": val})
        items.sort(key=lambda x: x["deposits"], reverse=True)
        return items

    if "mtd" in named_rows:
        result["mtd"] = _extract_countries(named_rows["mtd"])

    if "plan" in named_rows:
        result["plan"] = [
            {"country": item["country"], "deposits_plan": item["deposits"]}
            for item in _extract_countries(named_rows["plan"])
        ]

    month_names_en = {
        1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
        7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
    }
    prev1_en = month_names_en[(cur_month - 2) % 12 + 1]
    prev2_en = month_names_en[(cur_month - 3) % 12 + 1]
    prev3_en = month_names_en[(cur_month - 4) % 12 + 1]

    for key in ("prev1", "prev2", "prev3"):
        if key in named_rows:
            result["prev_months"][key] = _extract_countries(named_rows[key])

    result["prev_month_labels"] = {
        "prev1": prev1_en,
        "prev2": prev2_en,
        "prev3": prev3_en,
    }

    logger.info("Country deposits: %d countries, %d daily dates", len(countries), len(daily_by_date))
    return result


WORKSHEET_ALL_INDICATORS = "All indicators"


def _fetch_plan_data(client) -> dict:
    """
    Fetch all monthly forecasts from 'All indicators' sheet.

    Sections with 'all month forecast' rows:
      - Registrations/FTD:       col2=Regs, col3=FTD
      - Total Sport & Casino:    col2=Turnover, col4=GGR, col5=Promo, col6=GGR-Promo
      - Sport:                   col2=Sport Turnover, col4=Sport GGR
      - Casino:                  col2=Casino Turnover, col4=Casino GGR
      - Deposits:                col2=Deposits, col3=Withdrawals, col4=CashFlow
    """
    spreadsheet = client.open_by_url(GOOGLE_SHEETS_URL)
    plan = {}

    try:
        ws = spreadsheet.worksheet(WORKSHEET_ALL_INDICATORS)
        data = ws.get_all_values()

        forecast_rows = []
        for row in data:
            if row and "all month forecast" in str(row[0]).lower():
                forecast_rows.append(row)

        # Map forecast rows by section order:
        # 0 = Registrations/FTD
        # 1 = Total Sport & Casino
        # 2 = Sport
        # 3 = Casino
        # 4 = Deposits
        if len(forecast_rows) >= 5:
            # Registrations / FTD
            plan["registrations_plan"] = int(_parse_number(forecast_rows[0][2]))
            plan["ftd_plan"] = int(_parse_number(forecast_rows[0][3]))

            # Total Sport & Casino
            plan["turnover_plan"] = _parse_number(forecast_rows[1][2])
            plan["total_ggr_plan"] = _parse_number(forecast_rows[1][4])
            plan["promo_plan"] = _parse_number(forecast_rows[1][5])
            plan["ggr_net_promo_plan"] = _parse_number(forecast_rows[1][6])

            # Sport
            plan["sport_turnover_plan"] = _parse_number(forecast_rows[2][2])
            plan["sport_ggr_plan"] = _parse_number(forecast_rows[2][4])

            # Casino
            plan["casino_turnover_plan"] = _parse_number(forecast_rows[3][2])
            plan["casino_ggr_plan"] = _parse_number(forecast_rows[3][4])

            # Deposits
            plan["deposits_plan"] = _parse_number(forecast_rows[4][2])
            plan["withdrawals_plan"] = _parse_number(forecast_rows[4][3])
            plan["cash_flow_plan"] = _parse_number(forecast_rows[4][4])
        else:
            logger.warning("Expected 5 forecast rows in All indicators, found %d", len(forecast_rows))

    except Exception as e:
        logger.warning("Failed to read All indicators plan: %s", e)

    logger.info("Plan data: %s", {k: f"{v:,.0f}" if isinstance(v, float) else str(v) for k, v in plan.items()})
    return plan


# ------------------------------------------------------------------
# Deltas
# ------------------------------------------------------------------

def _pct_change(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return ((current - previous) / abs(previous)) * 100


def _pp_change(current: float, previous: float) -> float | None:
    if current is None or previous is None:
        return None
    return current - previous


def _with_deltas(today: dict, yesterday: dict, last_week: dict, avg_7d: dict, ratio_keys=None) -> dict:
    ratio_keys = ratio_keys or set()
    enriched = {}
    for key, val in today.items():
        if key in ("stat_date", "day_of_week"):
            enriched[key] = val
            continue
        enriched[key] = val
        prev = yesterday.get(key)
        week = last_week.get(key)
        avg = avg_7d.get(key)
        if key in ratio_keys:
            enriched[f"{key}_dod"] = _pp_change(val, prev)
            enriched[f"{key}_wow"] = _pp_change(val, week)
            enriched[f"{key}_7d"] = _pp_change(val, avg) if avg is not None else None
        else:
            enriched[f"{key}_dod"] = _pct_change(val, prev) if prev is not None else None
            enriched[f"{key}_wow"] = _pct_change(val, week) if week is not None else None
            enriched[f"{key}_7d"] = _pct_change(val, avg) if avg is not None else None
    return enriched


# ------------------------------------------------------------------
# Country traffic alerts (Registation - FTD DATA)
# ------------------------------------------------------------------

def _fetch_country_traffic_alerts(client, target_date: date) -> list[dict]:
    """
    Read 'Registation - FTD DATA' sheet (cols A:G).
    Compare today's registrations, FTD, conversion per country
    against the daily average of the previous month.
    Return list of alert dicts for countries with sharp changes.

    Columns: A=Date, B=Country, C=Registrations, D=FTD, E=Conversion%, F=month, G=year
    """
    spreadsheet = client.open_by_url(GOOGLE_SHEETS_URL)
    alerts = []

    try:
        ws = spreadsheet.worksheet(WORKSHEET_REG_FTD_DATA)
        raw = ws.get_all_values()
    except Exception as e:
        logger.warning("Failed to read %s: %s", WORKSHEET_REG_FTD_DATA, e)
        return alerts

    if len(raw) < 2:
        return alerts

    rows_parsed = []
    for row in raw[1:]:
        if len(row) < 5:
            continue
        d = _parse_date(row[0])
        if d is None:
            continue
        country = row[1].strip() if row[1] else ""
        if not country:
            continue
        regs = int(_parse_number(row[2]))
        ftd = int(_parse_number(row[3]))
        conv = _parse_number(row[4])
        rows_parsed.append({
            "stat_date": d,
            "country": country,
            "registrations": regs,
            "ftd": ftd,
            "conversion": conv,
        })

    if not rows_parsed:
        return alerts

    today_rows = [r for r in rows_parsed if r["stat_date"] == target_date]
    if not today_rows:
        logger.warning("No country traffic data for %s", target_date)
        return alerts

    prev_month = target_date.month - 1 if target_date.month > 1 else 12
    prev_year = target_date.year if target_date.month > 1 else target_date.year - 1
    days_in_prev = monthrange(prev_year, prev_month)[1]
    prev_start = date(prev_year, prev_month, 1)
    prev_end = date(prev_year, prev_month, days_in_prev)

    prev_rows = [r for r in rows_parsed if prev_start <= r["stat_date"] <= prev_end]

    prev_avg = {}
    for r in prev_rows:
        c = r["country"]
        if c not in prev_avg:
            prev_avg[c] = {"regs_sum": 0, "ftd_sum": 0, "days": 0}
        prev_avg[c]["regs_sum"] += r["registrations"]
        prev_avg[c]["ftd_sum"] += r["ftd"]
        prev_avg[c]["days"] += 1

    for c in prev_avg:
        d = prev_avg[c]["days"]
        prev_avg[c]["regs_avg"] = prev_avg[c]["regs_sum"] / d if d > 0 else 0
        prev_avg[c]["ftd_avg"] = prev_avg[c]["ftd_sum"] / d if d > 0 else 0
        regs_avg = prev_avg[c]["regs_avg"]
        ftd_avg = prev_avg[c]["ftd_avg"]
        prev_avg[c]["conv_avg"] = (ftd_avg / regs_avg * 100) if regs_avg > 0 else 0

    threshold = COUNTRY_ALERT_THRESHOLD_PCT

    for tr in today_rows:
        country = tr["country"]
        regs_today = tr["registrations"]
        ftd_today = tr["ftd"]
        conv_today = (ftd_today / regs_today * 100) if regs_today > 0 else 0

        if country not in prev_avg:
            continue
        pa = prev_avg[country]

        if pa["regs_avg"] < COUNTRY_ALERT_MIN_REGS:
            continue

        regs_pct = _pct_change(regs_today, pa["regs_avg"])
        ftd_pct = _pct_change(ftd_today, pa["ftd_avg"])
        conv_diff = conv_today - pa["conv_avg"]

        triggered = []
        if regs_pct is not None and abs(regs_pct) > threshold:
            triggered.append(("Regs", regs_today, pa["regs_avg"], regs_pct))
        if ftd_pct is not None and abs(ftd_pct) > threshold:
            triggered.append(("FTD", ftd_today, pa["ftd_avg"], ftd_pct))
        if abs(conv_diff) > 10:
            triggered.append(("Conv", conv_today, pa["conv_avg"], conv_diff))

        if triggered:
            alerts.append({
                "country": country,
                "regs_today": regs_today,
                "ftd_today": ftd_today,
                "conv_today": conv_today,
                "regs_avg": pa["regs_avg"],
                "ftd_avg": pa["ftd_avg"],
                "conv_avg": pa["conv_avg"],
                "triggered": triggered,
            })

    alerts.sort(key=lambda x: x["regs_today"], reverse=True)
    logger.info("Country traffic alerts: %d countries triggered", len(alerts))
    return alerts


# ------------------------------------------------------------------
# Somalia traffic split
# ------------------------------------------------------------------

def _fetch_somalia_split(client, target_date: date) -> dict:
    """
    Read Registation - FTD DATA and split regs/FTD into Somalia vs rest.
    Returns dict with somalia/excl_somalia for today, yesterday, last_week, 7d avg.
    """
    spreadsheet = client.open_by_url(GOOGLE_SHEETS_URL)
    result = {}

    try:
        ws = spreadsheet.worksheet(WORKSHEET_REG_FTD_DATA)
        raw = ws.get_all_values()
    except Exception as e:
        logger.warning("Somalia split: failed to read: %s", e)
        return result

    by_date = {}
    for row in raw[1:]:
        if len(row) < 4:
            continue
        d = _parse_date(row[0])
        if d is None:
            continue
        country = row[1].strip()
        if not country:
            continue
        regs = int(_parse_number(row[2]))
        ftd = int(_parse_number(row[3]))
        entry = by_date.setdefault(d, {"somalia_regs": 0, "somalia_ftd": 0, "other_regs": 0, "other_ftd": 0})
        if country == "Somalia":
            entry["somalia_regs"] += regs
            entry["somalia_ftd"] += ftd
        else:
            entry["other_regs"] += regs
            entry["other_ftd"] += ftd

    prev_day = target_date - timedelta(days=1)
    prev_week = target_date - timedelta(days=7)
    week_dates = [target_date - timedelta(days=i) for i in range(1, 8)]
    month_start = target_date.replace(day=1)
    mtd_dates = [month_start + timedelta(days=i) for i in range((target_date - month_start).days + 1)]

    def _get(dt):
        return by_date.get(dt, {"somalia_regs": 0, "somalia_ftd": 0, "other_regs": 0, "other_ftd": 0})

    def _sum_dates(dates):
        sums = {"somalia_regs": 0, "somalia_ftd": 0, "other_regs": 0, "other_ftd": 0}
        for dt in dates:
            dd = _get(dt)
            for k in sums:
                sums[k] += dd[k]
        return sums

    def _avg(dates):
        n = len(dates)
        if n == 0:
            return {"somalia_regs": 0, "somalia_ftd": 0, "other_regs": 0, "other_ftd": 0}
        sums = _sum_dates(dates)
        return {k: v / n for k, v in sums.items()}

    today = _get(target_date)
    yesterday = _get(prev_day)
    last_week = _get(prev_week)
    avg_7d = _avg(week_dates)
    mtd_totals = _sum_dates(mtd_dates)

    import calendar
    days_elapsed = len(mtd_dates)
    total_days = calendar.monthrange(target_date.year, target_date.month)[1]

    def _forecast(mtd_val):
        if days_elapsed == 0:
            return 0
        return int(round(mtd_val / days_elapsed * total_days))

    def _conv(regs, ftd):
        return (ftd / regs * 100) if regs > 0 else 0.0

    for prefix, r_key, f_key in [("somalia", "somalia_regs", "somalia_ftd"),
                                   ("excl_somalia", "other_regs", "other_ftd")]:
        result[f"{prefix}_regs"] = today[r_key]
        result[f"{prefix}_ftd"] = today[f_key]
        result[f"{prefix}_conv"] = _conv(today[r_key], today[f_key])
        result[f"{prefix}_regs_mtd"] = mtd_totals[r_key]
        result[f"{prefix}_ftd_mtd"] = mtd_totals[f_key]
        result[f"{prefix}_conv_mtd"] = _conv(mtd_totals[r_key], mtd_totals[f_key])
        result[f"{prefix}_regs_forecast"] = _forecast(mtd_totals[r_key])
        result[f"{prefix}_ftd_forecast"] = _forecast(mtd_totals[f_key])
        fc_regs = result[f"{prefix}_regs_forecast"]
        fc_ftd = result[f"{prefix}_ftd_forecast"]
        result[f"{prefix}_conv_forecast"] = _conv(fc_regs, fc_ftd)
        result[f"{prefix}_regs_dod"] = _pct_change(today[r_key], yesterday[r_key])
        result[f"{prefix}_ftd_dod"] = _pct_change(today[f_key], yesterday[f_key])
        result[f"{prefix}_conv_dod"] = _pp_change(_conv(today[r_key], today[f_key]),
                                                   _conv(yesterday[r_key], yesterday[f_key]))
        result[f"{prefix}_regs_wow"] = _pct_change(today[r_key], last_week[r_key])
        result[f"{prefix}_ftd_wow"] = _pct_change(today[f_key], last_week[f_key])
        result[f"{prefix}_conv_wow"] = _pp_change(_conv(today[r_key], today[f_key]),
                                                   _conv(last_week[r_key], last_week[f_key]))
        result[f"{prefix}_regs_7d"] = _pct_change(today[r_key], avg_7d[r_key])
        result[f"{prefix}_ftd_7d"] = _pct_change(today[f_key], avg_7d[f_key])
        result[f"{prefix}_conv_7d"] = _pp_change(_conv(today[r_key], today[f_key]),
                                                  _conv(avg_7d[r_key], avg_7d[f_key]))

    logger.info("Somalia split: Somalia regs=%d ftd=%d, Other regs=%d ftd=%d",
                today["somalia_regs"], today["somalia_ftd"], today["other_regs"], today["other_ftd"])
    return result


# ------------------------------------------------------------------
# Focus Markets
# ------------------------------------------------------------------

def _fetch_focus_markets_data(client, target_date: date) -> dict:
    """
    Aggregate daily metrics for focus market regions.
    Sources:
      - Registation - FTD DATA: regs, FTD per country per day
      - Dep_country: deposits per country per day
      - Turnover by country: turnover MTD, plan, vs Jan, vs Feb 2025
    Returns dict keyed by region name with today/yesterday/7d avg aggregates.
    """
    spreadsheet = client.open_by_url(GOOGLE_SHEETS_URL)
    all_countries = set()
    for countries in FOCUS_MARKETS.values():
        all_countries.update(countries)

    prev_day = target_date - timedelta(days=1)
    start_7d = target_date - timedelta(days=7)

    result = {}

    # --- Regs / FTD from Registation - FTD DATA ---
    reg_by_date_country = {}
    try:
        ws = spreadsheet.worksheet(WORKSHEET_REG_FTD_DATA)
        raw = ws.get_all_values()
        for row in raw[1:]:
            if len(row) < 5:
                continue
            d = _parse_date(row[0])
            if d is None:
                continue
            country = row[1].strip()
            if country not in all_countries:
                continue
            reg_by_date_country.setdefault(d, {})[country] = {
                "regs": int(_parse_number(row[2])),
                "ftd": int(_parse_number(row[3])),
            }
    except Exception as e:
        logger.warning("Focus markets: failed to read reg/ftd: %s", e)

    # --- Deposits from dep_c (cols M:P = indices 12-15: Month, Date, Country, Amount) ---
    dep_by_date_country = {}
    try:
        ws = spreadsheet.worksheet("dep_c")
        data = ws.get_all_values()
        for row in data[1:]:
            if len(row) < 16:
                continue
            country = row[14].strip()
            if not country or country not in all_countries:
                continue
            d = _parse_date(row[13])
            if d is None:
                continue
            val = _parse_number(row[15])
            dep_by_date_country.setdefault(d, {})[country] = val
    except Exception as e:
        logger.warning("Focus markets: failed to read deposits from dep_c: %s", e)

    # --- Turnover MTD from Turnover by country ---
    # col 0: Country, col 1: Turnover MTD, col 2: Deposits MTD,
    # col 4: Turnover Plan, col 5: Deps Plan,
    # col 6: Fact prev month (turnover), col 7: vs prev month %,
    # col 8: Fact same month last year (turnover), col 9: vs same month LY %
    turnover_data = {}
    turnover_col_labels = {"col6": "Prev Month", "col8": "Same Month LY"}
    try:
        ws = spreadsheet.worksheet(WORKSHEET_TURNOVER)
        data = ws.get_all_values()
        if len(data) > 2:
            header = data[2]
            if len(header) > 6 and header[6].strip():
                turnover_col_labels["col6"] = header[6].strip()
            if len(header) > 8 and header[8].strip():
                turnover_col_labels["col8"] = header[8].strip()
        for row in data[3:]:
            country = row[0].strip() if row[0] else ""
            if country not in all_countries:
                continue
            def _safe_pct(idx):
                if len(row) <= idx or not row[idx].strip():
                    return None
                return _parse_number(row[idx].replace(",", ".").replace("%", "").replace("\xa0", ""))
            turnover_data[country] = {
                "turnover_mtd": _parse_number(row[1]),
                "deposits_mtd": _parse_number(row[2]),
                "turnover_plan": _parse_number(row[4]),
                "deps_plan": _parse_number(row[5]),
                "fact_prev": _parse_number(row[6]) if len(row) > 6 else 0,
                "vs_prev_pct": _safe_pct(7),
                "fact_ly": _parse_number(row[8]) if len(row) > 8 else 0,
                "vs_ly_pct": _safe_pct(9),
            }
    except Exception as e:
        logger.warning("Focus markets: failed to read turnover: %s", e)

    # --- Per-country metrics ---
    first_of_month = target_date.replace(day=1)
    mtd_dates = [d for d in sorted(reg_by_date_country.keys()) if first_of_month <= d <= target_date]
    mtd_dep_dates = [d for d in sorted(dep_by_date_country.keys()) if first_of_month <= d <= target_date]

    def _country_metrics(country):
        td = turnover_data.get(country, {})

        regs_mtd = sum(reg_by_date_country.get(dt, {}).get(country, {}).get("regs", 0) for dt in mtd_dates)
        ftd_mtd = sum(reg_by_date_country.get(dt, {}).get(country, {}).get("ftd", 0) for dt in mtd_dates)
        deps_mtd_calc = sum(dep_by_date_country.get(dt, {}).get(country, 0) for dt in mtd_dep_dates)

        return {
            "regs_mtd": regs_mtd,
            "ftd_mtd": ftd_mtd,
            "deposits_mtd": td.get("deposits_mtd", 0) or deps_mtd_calc,
            "turnover_mtd": td.get("turnover_mtd", 0),
            "turnover_plan": td.get("turnover_plan", 0),
            "deps_plan": td.get("deps_plan", 0),
            "fact_prev": td.get("fact_prev", 0),
            "vs_prev_pct": td.get("vs_prev_pct"),
            "fact_ly": td.get("fact_ly", 0),
            "vs_ly_pct": td.get("vs_ly_pct"),
        }

    for region, countries in FOCUS_MARKETS.items():
        country_data = {}
        for c in countries:
            country_data[c] = _country_metrics(c)
        result[region] = {
            "countries": countries,
            "country_data": country_data,
        }

    result["_labels"] = {
        "turn_prev": f"Turn {turnover_col_labels['col6']}",
        "vs_prev": f"vs {turnover_col_labels['col6']}",
        "turn_ly": f"Turn {turnover_col_labels['col8']}",
        "vs_ly": f"vs {turnover_col_labels['col8']}",
    }

    logger.info("Focus markets: %d regions loaded", len(result))
    return result


# ------------------------------------------------------------------
# Alerts
# ------------------------------------------------------------------

def _build_alerts(today: dict, rows: list[dict], target_date: date) -> list[str]:
    threshold = ALERT_THRESHOLD_PCT
    # 7-day average (excluding target_date)
    start = target_date - timedelta(days=7)
    week_rows = [r for r in rows if start <= r["stat_date"] < target_date]

    if len(week_rows) < 3:
        return ["[!] Not enough data for 7d average alerts"]

    checks = [
        ("Registrations", "registrations"),
        ("Deposits EUR", "deposits"),
        ("Withdrawals EUR", "withdrawals"),
        ("FTD", "ftd"),
        ("Sport GGR EUR", "sport_ggr"),
        ("Casino GGR EUR", "casino_ggr"),
        ("Total GGR EUR", "total_ggr"),
    ]

    alerts = []
    for label, key in checks:
        avg = sum(r[key] for r in week_rows) / len(week_rows)
        current = today.get(key, 0)
        pct = _pct_change(current, avg)
        if pct is not None and abs(pct) > threshold:
            direction = "+" if pct > 0 else ""
            alerts.append(f"[!] {label} {direction}{pct:,.1f}% vs 7d avg (threshold {threshold:.0f}%)")

    return alerts


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

_EMPTY = {
    "registrations": 0, "ftd": 0, "deposits": 0.0, "withdrawals": 0.0,
    "cash_flow": 0.0, "deposits_no_comm": 0.0, "withdrawals_no_comm": 0.0,
    "balance_with_comm": 0.0, "sport_turnover": 0.0, "sport_win": 0.0,
    "sport_ggr": 0.0, "casino_turnover": 0.0, "casino_win": 0.0,
    "casino_ggr": 0.0, "total_turnover": 0.0, "total_win": 0.0,
    "total_ggr": 0.0, "promo": 0.0,
}


def collect_sheets_metrics(target_date: date) -> dict:
    """
    Collect metrics from Google Sheets for the target_date.
    Returns structured dict with values, DoD/WoW deltas, MTD, plan, and alerts.
    All monetary values are in EUR.
    """
    client = _connect()
    spreadsheet = client.open_by_url(GOOGLE_SHEETS_URL)

    # Load daily report rows
    rows = _load_all_rows(client)

    prev_day = target_date - timedelta(days=1)
    prev_week = target_date - timedelta(days=7)

    today = _find_row(rows, target_date) or _EMPTY.copy()
    yesterday = _find_row(rows, prev_day) or _EMPTY.copy()
    last_week = _find_row(rows, prev_week) or _EMPTY.copy()

    # 7-day average (7 days before target_date, excluding target_date)
    start_7d = target_date - timedelta(days=7)
    week_rows = [r for r in rows if start_7d <= r["stat_date"] < target_date]
    avg_7d = _EMPTY.copy()
    if week_rows:
        n = len(week_rows)
        for key in avg_7d:
            avg_7d[key] = sum(r.get(key, 0) for r in week_rows) / n

    # Conversion
    for d in (today, yesterday, last_week):
        regs = d.get("registrations", 0)
        ftd = d.get("ftd", 0)
        d["conversion"] = (ftd / regs * 100) if regs > 0 else 0.0

    # Conversion for 7d avg
    avg_regs = avg_7d.get("registrations", 0)
    avg_ftd = avg_7d.get("ftd", 0)
    avg_7d["conversion"] = (avg_ftd / avg_regs * 100) if avg_regs > 0 else 0.0

    # GGR net promo
    for d in (today, yesterday, last_week):
        d["ggr_net_promo"] = d.get("total_ggr", 0) + d.get("promo", 0)
    avg_7d["ggr_net_promo"] = avg_7d.get("total_ggr", 0) + avg_7d.get("promo", 0)

    # Sport/Casino share
    total_ggr = today.get("total_ggr", 0)
    sport_share = (today["sport_ggr"] / total_ggr * 100) if total_ggr != 0 else 0.0

    # Deltas
    enriched = _with_deltas(today, yesterday, last_week, avg_7d, ratio_keys={"conversion"})

    # MTD
    mtd = _compute_mtd(rows, target_date)

    # Previous month totals (for MoM comparison)
    prev_month_totals = _compute_prev_month_totals(rows, target_date)

    # Plan data (reuse existing client connection)
    plan = _fetch_plan_data(client)

    # Country deposits
    country_data = _fetch_country_deposits(client, target_date)

    # Country traffic alerts (regs/FTD/conversion by country vs prev month avg)
    country_traffic_alerts = _fetch_country_traffic_alerts(client, target_date)

    # Somalia split
    somalia_split = _fetch_somalia_split(client, target_date)

    # Focus markets
    focus_markets = _fetch_focus_markets_data(client, target_date)

    # Alerts
    alerts = _build_alerts(today, rows, target_date)

    # Top 5 players from PostgreSQL
    try:
        from top_players import fetch_top_players
        top_players_data = fetch_top_players(target_date)
    except Exception as e:
        logger.warning("Failed to fetch top players: %s", e)
        top_players_data = {}

    return {
        "target_date": target_date,
        "currency": "EUR",
        "data": enriched,
        "sport_share": sport_share,
        "mtd": mtd,
        "plan": plan,
        "prev_month_totals": prev_month_totals,
        "country_deposits": country_data,
        "country_traffic_alerts": country_traffic_alerts,
        "somalia_split": somalia_split,
        "focus_markets": focus_markets,
        "alerts": alerts,
        "top_players": top_players_data,
    }
