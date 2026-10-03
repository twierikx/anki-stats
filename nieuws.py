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


# ------------------------------------------------------- full article text --

from html.parser import HTMLParser  # noqa: E402
import json  # noqa: E402

SKIP_TAGS = {"script", "style", "nav", "footer", "aside", "figure", "figcaption", "form",
             "button", "noscript", "header"}


class _Paragraphs(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.in_article = 0
        self.in_p = False
        self.buf: list[str] = []
        self.paras: list[tuple[bool, str]] = []  # (inside <article>, text)
        self.ldjson: list[str] = []
        self.in_ld = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script" and a.get("type") == "application/ld+json":
            self.in_ld = True
            self.ldjson.append("")
            return
        if tag in SKIP_TAGS:
            self.skip += 1
        elif tag == "article":
            self.in_article += 1
        elif tag == "p" and not self.skip:
            self.in_p, self.buf = True, []

    def handle_endtag(self, tag):
        if tag == "script" and self.in_ld:
            self.in_ld = False
            return
        if tag in SKIP_TAGS and self.skip:
            self.skip -= 1
        elif tag == "article" and self.in_article:
            self.in_article -= 1
        elif tag == "p" and self.in_p:
            self.in_p = False
            text = re.sub(r"\s+", " ", "".join(self.buf)).strip()
            if text:
                self.paras.append((self.in_article > 0, text))

    def handle_data(self, data):
        if self.in_ld:
            self.ldjson[-1] += data
        elif self.in_p and not self.skip:
            self.buf.append(data)


def _find_body(obj) -> str:
    if isinstance(obj, dict):
        body = obj.get("articleBody")
        if isinstance(body, str) and len(body) > 300:
            return body
        obj = list(obj.values())
    if isinstance(obj, list):
        for v in obj:
            found = _find_body(v)
            if found:
                return found
    return ""


def extract_text(page: str, max_chars: int = 6000) -> str:
    p = _Paragraphs()
    try:
        p.feed(page)
    except Exception:
        pass
    for raw in p.ldjson:
        try:
            body = _find_body(json.loads(raw))
        except Exception:
            continue
        if body:
            return clean(body)[:max_chars]
    paras = [t for inside, t in p.paras if inside] or [t for _, t in p.paras]
    paras = [t for t in paras if len(t) >= 60 and not re.search(
        r"suscri|cookies|newsletter|todos los derechos|publicidad", t, re.I)]
    return "\n\n".join(paras)[:max_chars]


def fetch_article(url: str) -> str:
    try:
        r = requests.get(url, headers=UA, timeout=25)
        r.raise_for_status()
        r.encoding = r.encoding if r.encoding and r.encoding.lower() != "iso-8859-1" else "utf-8"
        return extract_text(r.text)
    except Exception as exc:
        print(f"::warning::Artikel ophalen mislukt ({url}): {exc}")
        return ""
