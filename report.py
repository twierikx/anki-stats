"""Render the weekly report as an e-mail friendly HTML page and plain text."""

from __future__ import annotations

from datetime import timedelta
from html import escape

from stats import WeekStats

MONTHS = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"]
DAYS = ["ma", "di", "wo", "do", "vr", "za", "zo"]

GREEN = "#58cc02"
GREEN_DARK = "#46a302"
ORANGE = "#ff9600"
BLUE = "#1cb0f6"
GREY = "#e5e5e5"
TEXT = "#3c3c3c"
MUTED = "#777777"


def fmt_date(d) -> str:
    return f"{d.day} {MONTHS[d.month - 1]}"


def week_label(week_start) -> str:
    end = week_start + timedelta(days=6)
    week_no = week_start.isocalendar()[1]
    return f"Week {week_no} · {fmt_date(week_start)} – {fmt_date(end)}"


def delta(now: float, before: float) -> str:
    if before <= 0:
        return "nieuw!" if now > 0 else ""
    pct = round(100 * (now - before) / before)
    if pct == 0:
        return "gelijk aan vorige week"
    return f"{'+' if pct > 0 else ''}{pct}% t.o.v. vorige week"


def cheer(s: WeekStats) -> str:
    if s.error:
        return "Geen gegevens deze week."
    if s.days_studied == 7:
        return "Elke dag geoefend. Perfecte week!"
    if s.days_studied >= 5:
        return "Sterke week, bijna elke dag geoefend."
    if s.days_studied >= 3:
        return "Goed bezig, probeer er deze week een dag bij te pakken."
    if s.days_studied >= 1:
        return "Een begin is er. Elke dag een paar kaarten maakt het verschil."
    return "Deze week niet geoefend. Vandaag is een mooie dag om weer te beginnen!"


def winner(stats: list[WeekStats]) -> WeekStats | None:
    ok = [s for s in stats if not s.error and s.reviews > 0]
    if len(ok) < 2:
        return None
    ok.sort(key=lambda s: (s.days_studied, s.reviews), reverse=True)
    if (ok[0].days_studied, ok[0].reviews) == (ok[1].days_studied, ok[1].reviews):
        return None
    return ok[0]


# ---------------------------------------------------------------- HTML ----

def _tile(value: str, label: str, color: str) -> str:
    return (
        f'<td width="25%" align="center" style="padding:10px 4px;border:2px solid {GREY};'
        f'border-radius:14px;">'
        f'<div style="font-size:22px;font-weight:800;color:{color};">{escape(value)}</div>'
        f'<div style="font-size:12px;color:{MUTED};padding-top:2px;">{escape(label)}</div></td>'
    )


def _bars(per_day: list[int]) -> str:
    top = max(per_day) or 1
    cells = []
    for n, day in zip(per_day, DAYS):
        h = max(4, round(70 * n / top)) if n else 4
        color = GREEN if n else GREY
        cells.append(
            '<td align="center" valign="bottom" style="padding:0 3px;">'
            f'<div style="font-size:11px;color:{MUTED};padding-bottom:3px;">{n or ""}</div>'
            f'<div style="height:{h}px;width:26px;background:{color};border-radius:6px 6px 3px 3px;'
            'margin:0 auto;"></div>'
            f'<div style="font-size:11px;color:{MUTED};padding-top:4px;">{day}</div></td>'
        )
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" width="100%" '
        f'style="height:100px;"><tr>{"".join(cells)}</tr></table>'
    )


def _person(s: WeekStats, is_winner: bool) -> str:
    crown = " 🏆" if is_winner else ""
    if s.error:
        body = (
            f'<p style="color:#ea2b2b;font-size:14px;margin:8px 0 0;">'
            f'Kon de gegevens niet ophalen: {escape(s.error)}</p>'
        )
    else:
        retention = f"{s.retention:.0f}%" if s.retention is not None else "–"
        trend = delta(s.reviews, s.prev_reviews)
        body = f"""
<table role="presentation" cellpadding="0" cellspacing="6" width="100%" style="margin-top:10px;">
  <tr>
    {_tile(str(s.reviews), "herhalingen", BLUE)}
    {_tile(f"{s.minutes:.0f}", "minuten", BLUE)}
    {_tile(str(s.new_cards), "nieuwe kaarten", GREEN_DARK)}
    {_tile(retention, "goed", GREEN_DARK)}
  </tr>
</table>
<div style="padding:14px 4px 4px;">{_bars(s.per_day)}</div>
<p style="font-size:13px;color:{MUTED};margin:10px 4px 0;">
  {s.days_studied}/7 dagen geoefend{(" · " + escape(trend)) if trend else ""}<br>
  {s.mature_cards} van {s.total_cards} kaarten zitten goed in je geheugen (interval ≥ 21 dagen)
  · langste reeks ooit: {s.best_streak} dagen
</p>
<p style="font-size:14px;color:{TEXT};margin:10px 4px 0;font-weight:600;">{escape(cheer(s))}</p>"""

    flame_color = ORANGE if s.streak else "#afafaf"
    return f"""
<tr><td style="padding:0 0 16px;">
<table role="presentation" cellpadding="0" cellspacing="0" width="100%"
  style="background:#ffffff;border:2px solid {GREY};border-radius:18px;">
<tr><td style="padding:18px 18px 16px;">
  <table role="presentation" cellpadding="0" cellspacing="0" width="100%"><tr>
    <td style="font-size:20px;font-weight:800;color:{TEXT};">{escape(s.name)}{crown}</td>
    <td align="right" style="font-size:20px;font-weight:800;color:{flame_color};white-space:nowrap;">
      🔥 {s.streak} {"dag" if s.streak == 1 else "dagen"}</td>
  </tr></table>
  {body}
</td></tr></table>
</td></tr>"""


def render_html(stats: list[WeekStats]) -> str:
    week = week_label(stats[0].week_start)
    win = winner(stats)
    headline = (
        f"{escape(win.name)} wint deze week! 🏆" if win else "Jullie weekoverzicht"
    )
    together = sum(s.reviews for s in stats if not s.error)
    people = "".join(_person(s, s is win) for s in stats)
    return f"""<!doctype html>
<html lang="nl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Anki-weekrapport</title></head>
<body style="margin:0;padding:0;background:#f7f7f7;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:{TEXT};">
<table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="background:#f7f7f7;">
<tr><td align="center" style="padding:20px 12px;">
<table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="max-width:560px;">
  <tr><td style="background:{GREEN};border-radius:18px;padding:22px 20px;color:#ffffff;">
    <div style="font-size:13px;font-weight:700;opacity:.9;text-transform:uppercase;letter-spacing:.06em;">
      Anki-weekrapport · {escape(week)}</div>
    <div style="font-size:26px;font-weight:800;padding-top:6px;">{headline}</div>
    <div style="font-size:15px;padding-top:6px;">Samen {together} kaarten herhaald.</div>
  </td></tr>
  <tr><td style="height:16px;"></td></tr>
  {people}
  <tr><td align="center" style="font-size:12px;color:#afafaf;padding:4px 0 10px;">
    Elke maandag automatisch verstuurd vanuit GitHub (twierikx/anki-stats).
  </td></tr>
</table>
</td></tr></table>
</body></html>"""


# ---------------------------------------------------------------- text ----

def render_text(stats: list[WeekStats]) -> str:
    lines = [f"Anki-weekrapport · {week_label(stats[0].week_start)}", ""]
    win = winner(stats)
    if win:
        lines += [f"{win.name} wint deze week!", ""]
    for s in stats:
        lines.append(f"{s.name} — reeks: {s.streak} dagen")
        if s.error:
            lines.append(f"  Kon de gegevens niet ophalen: {s.error}")
        else:
            ret = f"{s.retention:.0f}%" if s.retention is not None else "–"
            lines += [
                f"  {s.reviews} herhalingen, {s.minutes:.0f} min, {s.new_cards} nieuwe kaarten, {ret} goed",
                f"  {s.days_studied}/7 dagen geoefend  " + "  ".join(
                    f"{d}:{n}" for d, n in zip(DAYS, s.per_day)
                ),
                f"  {delta(s.reviews, s.prev_reviews)}",
                f"  {cheer(s)}",
            ]
        lines.append("")
    return "\n".join(lines)


def subject(stats: list[WeekStats]) -> str:
    streaks = " · ".join(f"{s.name} 🔥{s.streak}" for s in stats)
    return f"Anki-weekrapport {fmt_date(stats[0].week_start)}: {streaks}"
