"""Fetch recent Spanish news items from RSS feeds."""

from __future__ import annotations

import calendar
import html
import re
import time
from dataclasses import dataclass

import feedparser
import requests

EP = "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com"
FEEDS = [
    ("El País", f"{EP}/portada", 25),
    ("El País", f"{EP}/section/ciencia/portada", 12),
    ("El País", f"{EP}/section/clima-y-medio-ambiente/portada", 10),
    ("El País", f"{EP}/section/sociedad/portada", 10),
    ("El País", f"{EP}/section/cultura/portada", 8),
    ("elDiario.es", "https://www.eldiario.es/rss/", 20),
    ("20minutos", "https://www.20minutos.es/rss/", 20),
    ("Europa Press", "https://www.europapress.es/rss/rss.aspx", 10),
    ("La Vanguardia", "https://www.lavanguardia.com/rss/home.xml", 15),
]
MAX_AGE_H = 48
UA = {"User-Agent": "Mozilla/5.0 (anki-stats krant; +https://github.com/twierikx/anki-stats)"}


@dataclass
class Item:
    id: int
    source: str
    title: str
    summary: str
    link: str
    section: str
    published: float


def clean(s: str) -> str:
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s).strip()


def fetch_items() -> list[Item]:
    items: list[Item] = []
    seen: set[str] = set()
    now = time.time()
    for source, url, limit in FEEDS:
        try:
            r = requests.get(url, headers=UA, timeout=25)
            r.raise_for_status()
            feed = feedparser.parse(r.content)
        except Exception as exc:
            print(f"::warning::Feed {url} mislukt: {exc}")
            continue
        n = 0
        for e in feed.entries:
            title = clean(e.get("title", ""))
            summary = clean(e.get("summary", ""))
            link = e.get("link", "")
            ts = e.get("published_parsed") or e.get("updated_parsed")
            published = calendar.timegm(ts) if ts else now
            key = re.sub(r"\W+", "", title.lower())[:60]
            if not title or not link or key in seen or len(summary) < 40:
                continue
            if now - published > MAX_AGE_H * 3600:
                continue
            seen.add(key)
            section = clean(" / ".join(t.get("term", "") for t in e.get("tags", [])[:2]))
            items.append(Item(len(items), source, title, summary[:600], link, section, published))
            n += 1
            if n >= limit:
                break
        print(f"  {source}: {n} berichten")
    return items
