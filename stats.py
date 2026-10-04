"""Turn an Anki collection (revlog + cards) into weekly statistics."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Madrid")
DEFAULT_ROLLOVER = 4  # Anki's day starts at 04:00 by default

# revlog.type: 0 learn, 1 review, 2 relearn, 3 filtered, 4 manual, 5 rescheduled
STUDY_TYPES = (0, 1, 2, 3)


@dataclass
class Collection:
    revlog: list[tuple[int, int, int, int, int]]  # (id_ms, cid, ease, time_ms, type)
    card_ivls: list[int]  # interval (days) of every card; <=0 for new/learning
    rollover: int = DEFAULT_ROLLOVER


@dataclass
class WeekStats:
    name: str
    week_start: date
    per_day: list[int]  # reviews for each of the 7 days
    reviews: int
    minutes: float
    new_cards: int
    retention: float | None  # % correct on mature/young reviews (type 1)
    days_studied: int
    streak: int
    best_streak: int
    total_cards: int
    mature_cards: int
    prev_reviews: int
    prev_minutes: float
    prev_days_studied: int
    error: str | None = None
    extra: dict = field(default_factory=dict)


def load_collection(path: str) -> Collection:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        revlog = con.execute("select id, cid, ease, time, type from revlog").fetchall()
        ivls = [r[0] for r in con.execute("select ivl from cards")]
        rollover = DEFAULT_ROLLOVER
        try:
            row = con.execute("select val from config where key = 'rollover'").fetchone()
            if row is not None:
                rollover = int(json.loads(row[0]))
        except Exception:
            pass
    finally:
        con.close()
    return Collection(revlog=revlog, card_ivls=ivls, rollover=rollover)


def anki_day(ts_ms: int, rollover: int) -> date:
    return (datetime.fromtimestamp(ts_ms / 1000, TZ) - timedelta(hours=rollover)).date()


def last_full_week(today: date) -> date:
    """Monday of the most recent complete Monday–Sunday week."""
    this_monday = today - timedelta(days=today.weekday())
    return this_monday - timedelta(days=7)


def _streak_ending(days: set[date], end: date) -> int:
    n = 0
    d = end
    while d in days:
        n += 1
        d -= timedelta(days=1)
    return n


def compute(name: str, col: Collection, week_start: date, today: date) -> WeekStats:
    week_end = week_start + timedelta(days=7)  # exclusive
    prev_start = week_start - timedelta(days=7)

    study = [r for r in col.revlog if r[4] in STUDY_TYPES and r[2] > 0]
    day_of = {r[0]: anki_day(r[0], col.rollover) for r in study}

    per_day = [0] * 7
    minutes = 0.0
    prev_reviews = 0
    prev_minutes = 0.0
    prev_days: set[date] = set()
    week_days: set[date] = set()
    review_total = review_ok = 0
    for r in study:
        d = day_of[r[0]]
        t = min(r[3], 60_000) / 60_000  # Anki caps answer time at 60 s
        if week_start <= d < week_end:
            per_day[(d - week_start).days] += 1
            minutes += t
            week_days.add(d)
            if r[4] == 1:
                review_total += 1
                review_ok += r[2] > 1
        elif prev_start <= d < week_start:
            prev_reviews += 1
            prev_minutes += t
            prev_days.add(d)

    # New cards = cards whose very first answer happened this week.
    first_seen: dict[int, date] = {}
    for r in sorted(study):
        first_seen.setdefault(r[1], day_of[r[0]])
    new_cards = sum(1 for d in first_seen.values() if week_start <= d < week_end)

    all_days = set(day_of.values())
    # Current streak: up to the last day of the week, or up to today if they
    # already studied today (the mail goes out on Monday morning).
    end = today if today in all_days else today - timedelta(days=1)
    streak = _streak_ending(all_days, end)

    best = run = 0
    prev = None
    for d in sorted(all_days):
        run = run + 1 if prev is not None and d - prev == timedelta(days=1) else 1
        best = max(best, run)
        prev = d

    return WeekStats(
        name=name,
        week_start=week_start,
        per_day=per_day,
        reviews=sum(per_day),
        minutes=minutes,
        new_cards=new_cards,
        retention=(100 * review_ok / review_total) if review_total else None,
        days_studied=len(week_days),
        streak=streak,
        best_streak=best,
        total_cards=len(col.card_ivls),
        mature_cards=sum(1 for i in col.card_ivls if i >= 21),
        prev_reviews=prev_reviews,
        prev_minutes=prev_minutes,
        prev_days_studied=len(prev_days),
    )


def error_stats(name: str, week_start: date, message: str) -> WeekStats:
    return WeekStats(
        name=name, week_start=week_start, per_day=[0] * 7, reviews=0, minutes=0,
        new_cards=0, retention=None, days_studied=0, streak=0, best_streak=0,
        total_cards=0, mature_cards=0, prev_reviews=0, prev_minutes=0,
        prev_days_studied=0, error=message,
    )


# ------------------------------------------------------------ daily overview --

HEATMAP_WEEKS = 13


def overview(name: str, col: Collection, today: date) -> dict:
    """Numbers for the stats page and the footer of the newspaper (JSON-friendly)."""
    study = [r for r in col.revlog if r[4] in STUDY_TYPES and r[2] > 0]
    per_day: dict[date, int] = {}
    minutes: dict[date, float] = {}
    first_seen: dict[int, date] = {}
    for r in sorted(study):
        d = anki_day(r[0], col.rollover)
        per_day[d] = per_day.get(d, 0) + 1
        minutes[d] = minutes.get(d, 0) + min(r[3], 60_000) / 60_000
        first_seen.setdefault(r[1], d)
    new_per_day: dict[date, int] = {}
    for d in first_seen.values():
        new_per_day[d] = new_per_day.get(d, 0) + 1

    days = set(per_day)
    end = today if today in days else today - timedelta(days=1)
    streak = _streak_ending(days, end)
    best = run = 0
    prev = None
    for d in sorted(days):
        run = run + 1 if prev is not None and d - prev == timedelta(days=1) else 1
        best = max(best, run)
        prev = d

    monday = today - timedelta(days=today.weekday())
    week = [monday + timedelta(days=i) for i in range(7)]
    last_week = [monday - timedelta(days=7 - i) for i in range(7)]
    cut30 = today - timedelta(days=29)
    rev30 = [r for r in study if r[4] == 1 and anki_day(r[0], col.rollover) >= cut30]
    retention = round(100 * sum(r[2] > 1 for r in rev30) / len(rev30)) if rev30 else None

    start = monday - timedelta(weeks=HEATMAP_WEEKS - 1)
    heat = [[d.isoformat(), per_day.get(d, 0)]
            for d in (start + timedelta(days=i) for i in range((today - start).days + 1))]
    return {
        "name": name,
        "today": today.isoformat(),
        "streak": streak,
        "studied_today": today in days,
        "best_streak": best,
        "yesterday": per_day.get(today - timedelta(days=1), 0),
        "today_reviews": per_day.get(today, 0),
        "week": [per_day.get(d, 0) for d in week],
        "last7": [[(today - timedelta(days=6 - i)).weekday(),
                   per_day.get(today - timedelta(days=6 - i), 0)] for i in range(7)],
        "week_total": sum(per_day.get(d, 0) for d in week),
        "week_minutes": round(sum(minutes.get(d, 0) for d in week)),
        "week_new": sum(new_per_day.get(d, 0) for d in week),
        "last_week_total": sum(per_day.get(d, 0) for d in last_week),
        "last_week_days": sum(1 for d in last_week if d in days),
        "days_30": sum(1 for i in range(30) if today - timedelta(days=i) in days),
        "reviews_30": sum(per_day.get(today - timedelta(days=i), 0) for i in range(30)),
        "retention_30": retention,
        "total_reviews": len(study),
        "total_cards": len(col.card_ivls),
        "mature_cards": sum(1 for i in col.card_ivls if i >= 21),
        "heatmap": heat,
    }
