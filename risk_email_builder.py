"""
Build HTML email for the Risk daily report.
Shows Top 5 players by profit (winnings - bets) for casino and sport,
plus Top 5 by deposits and withdrawals.
"""

from datetime import date

DAY_NAMES = {
    0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu",
    4: "Fri", 5: "Sat", 6: "Sun",
}

STYLES = """
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif; }
  .report-container { max-width: 960px; margin: 0 auto; background: #fff;
    border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.1); }
  .header { background: linear-gradient(135deg, #7c3aed 0%, #4f46e5 100%);
    padding: 24px 28px; }
  .header h1 { margin: 0 0 4px; font-size: 22px; color: #fff; font-weight: 700; }
  .header .subtitle { margin: 0; font-size: 13px; color: rgba(255,255,255,.8); }
  .footer { padding: 12px 28px; background: #f9fafb; border-top: 1px solid #e5e7eb;
    font-size: 11px; color: #9ca3af; text-align: center; }
</style>
"""


def _fmt_usd(v: float) -> str:
    return f"${v:,.0f}"


def _build_profit_table(title: str, rows: list[dict]) -> str:
    th = (
        'style="font-size:11px;font-weight:700;color:#374151;text-transform:uppercase;'
        'padding:5px 10px;border-bottom:2px solid #e5e7eb;background:#f9fafb;white-space:nowrap;"'
    )
    th_r = th.replace("text-align:left", "text-align:right").replace(
        'text-transform:uppercase;', 'text-transform:uppercase;text-align:right;'
    )

    header = (
        f'<p style="font-size:11px;font-weight:700;color:#374151;text-transform:uppercase;'
        f'letter-spacing:.05em;margin:0 0 8px 0;">{title}</p>'
        f'<table cellpadding="0" cellspacing="0" border="0" '
        f'style="border-collapse:collapse;width:100%;margin-bottom:20px;">'
        f'<thead><tr>'
        f'<th {th}>#</th>'
        f'<th {th}>Player ID</th>'
        f'<th style="font-size:11px;font-weight:700;color:#374151;text-transform:uppercase;'
        f'padding:5px 10px;border-bottom:2px solid #e5e7eb;background:#f9fafb;text-align:right;">'
        f'Profit</th>'
        f'<th style="font-size:11px;font-weight:700;color:#374151;text-transform:uppercase;'
        f'padding:5px 10px;border-bottom:2px solid #e5e7eb;background:#f9fafb;text-align:right;">'
        f'Winnings</th>'
        f'<th style="font-size:11px;font-weight:700;color:#374151;text-transform:uppercase;'
        f'padding:5px 10px;border-bottom:2px solid #e5e7eb;background:#f9fafb;text-align:right;">'
        f'Bets</th>'
        f'</tr></thead><tbody>'
    )

    if not rows:
        body = (
            '<tr><td colspan="5" style="padding:10px;font-size:12px;'
            'color:#9ca3af;font-style:italic;">No data</td></tr>'
        )
    else:
        body = ""
        for i, r in enumerate(rows):
            bg = "background:#f9fafb;" if i % 2 == 0 else ""
            profit = r["amount_usd"]
            body += (
                f'<tr style="{bg}">'
                f'<td style="padding:6px 10px;font-size:12px;color:#6b7280;">{i+1}</td>'
                f'<td style="padding:6px 10px;font-size:12px;color:#374151;">{r["player_id"]}</td>'
                f'<td style="padding:6px 10px;font-size:12px;font-weight:700;'
                f'color:#dc2626;text-align:right;">{_fmt_usd(profit)}</td>'
                f'<td style="padding:6px 10px;font-size:12px;color:#374151;text-align:right;">'
                f'{_fmt_usd(r.get("winnings", 0))}</td>'
                f'<td style="padding:6px 10px;font-size:12px;color:#6b7280;text-align:right;">'
                f'{_fmt_usd(r.get("bets", 0))}</td>'
                f'</tr>'
            )

    return header + body + '</tbody></table>'


def _build_simple_table(title: str, rows: list[dict]) -> str:
    th = (
        'style="font-size:11px;font-weight:700;color:#374151;text-transform:uppercase;'
        'padding:5px 10px;border-bottom:2px solid #e5e7eb;background:#f9fafb;white-space:nowrap;"'
    )
    header = (
        f'<p style="font-size:11px;font-weight:700;color:#374151;text-transform:uppercase;'
        f'letter-spacing:.05em;margin:0 0 8px 0;">{title}</p>'
        f'<table cellpadding="0" cellspacing="0" border="0" '
        f'style="border-collapse:collapse;width:100%;margin-bottom:20px;">'
        f'<thead><tr>'
        f'<th {th}>#</th><th {th}>Player ID</th>'
        f'<th style="font-size:11px;font-weight:700;color:#374151;text-transform:uppercase;'
        f'padding:5px 10px;border-bottom:2px solid #e5e7eb;background:#f9fafb;text-align:right;">'
        f'Amt, USD</th>'
        f'</tr></thead><tbody>'
    )
    if not rows:
        body = (
            '<tr><td colspan="3" style="padding:10px;font-size:12px;'
            'color:#9ca3af;font-style:italic;">No data</td></tr>'
        )
    else:
        body = ""
        for i, r in enumerate(rows):
            bg = "background:#f9fafb;" if i % 2 == 0 else ""
            body += (
                f'<tr style="{bg}">'
                f'<td style="padding:6px 10px;font-size:12px;color:#6b7280;">{i+1}</td>'
                f'<td style="padding:6px 10px;font-size:12px;color:#374151;">{r["player_id"]}</td>'
                f'<td style="padding:6px 10px;font-size:12px;font-weight:600;'
                f'color:#111827;text-align:right;">{_fmt_usd(r["amount_usd"])}</td>'
                f'</tr>'
            )
    return header + body + '</tbody></table>'


def _build_risk_players(data: dict) -> str:
    casino = data.get("casino", [])
    sport  = data.get("sport", [])
    deps   = data.get("deposits", [])
    wds    = data.get("withdrawals", [])

    left_col = (
        _build_profit_table("Top 5 Casino Profit", casino)
        + _build_profit_table("Top 10 Sport Profit", sport)
    )
    right_col = (
        _build_simple_table("Top 5 Deposits", deps)
        + _build_simple_table("Top 10 Withdrawals", wds)
    )

    return (
        '<div style="padding:20px 28px;">'
        '<table cellpadding="0" cellspacing="0" border="0" style="width:100%;border-collapse:collapse;">'
        '<tr>'
        f'<td style="vertical-align:top;padding-right:32px;width:60%;">{left_col}</td>'
        f'<td style="vertical-align:top;width:40%;">{right_col}</td>'
        '</tr>'
        '</table>'
        '</div>'
    )


def build_risk_report(top_players: dict, target_date: date) -> str:
    day_name = DAY_NAMES[target_date.weekday()]
    players_html = _build_risk_players(top_players)

    if not top_players:
        players_html = (
            '<div style="padding:24px 28px;color:#9ca3af;font-size:13px;">'
            'No player data available for this date.'
            '</div>'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Risk Report {target_date.strftime('%d %b %Y')}</title>
  {STYLES}
</head>
<body style="margin:0;padding:20px 0;background:#f1f5f9;">
  <div class="report-container">

    <div class="header">
      <h1>Risk Report</h1>
      <p class="subtitle">{target_date.strftime('%d %B %Y')} ({day_name}) &bull; USD</p>
    </div>

    {players_html}

    <div class="footer">
      BetAndYou Risk &bull; Generated automatically &bull; {target_date.strftime('%d.%m.%Y')}
    </div>

  </div>
</body>
</html>"""


def build_risk_subject(target_date: date) -> str:
    return f"Risk Report {target_date.strftime('%d %b %Y')} B&U"
