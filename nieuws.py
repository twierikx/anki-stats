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
UA = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9",
}
MIN_TEXT = 800


@dataclass
class Item:
    id: int
    source: str
    title: str
    summary: str
    link: str
    section: str
    published: float
    content: str = ""  # full text when the feed itself carries it


def paragraphs_from_html(s: str) -> str:
    s = re.sub(r"(?i)</p\s*>|<br\s*/?>", "\n\n", s or "")
    parts = [clean(p) for p in s.split("\n\n")]
    return "\n\n".join(p for p in parts if len(p) > 1)


def clean(s: str) -> str:
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    s = re.sub(r"\s+", " ", s).strip()
    return re.sub(r"\s+([.,;:!?)»”])", r"\1", s)


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
            content = ""
            for c in e.get("content", []) or []:
                text = paragraphs_from_html(c.get("value", ""))
                if len(text) > len(content):
                    content = text
            content = content[:6000] if len(content) >= MIN_TEXT else ""
            items.append(Item(len(items), source, title, summary[:600], link, section, published,
                              content))
            n += 1
            if n >= limit:
                break
        print(f"  {source}: {n} berichten")
    return items


def readable_sources(items: list[Item]) -> set[str]:
    """Try one article per source; return the sources whose pages we can actually read."""
    ok: set[str] = set()
    tried: dict[str, int] = {}
    for it in items:
        if it.source in ok:
            continue
        if it.content:
            ok.add(it.source)
            continue
        if tried.get(it.source, 0) >= 2:
            continue
        tried[it.source] = tried.get(it.source, 0) + 1
        if len(fetch_article(it.link)) >= MIN_TEXT:
            ok.add(it.source)
    print(f"  Leesbare bronnen: {', '.join(sorted(ok)) or 'geen'}")
    return ok


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
        time.sleep(0.5)
        r = requests.get(url, headers=UA, timeout=25)
        r.raise_for_status()
        r.encoding = r.encoding if r.encoding and r.encoding.lower() != "iso-8859-1" else "utf-8"
        return extract_text(r.text)
    except Exception as exc:
        print(f"::warning::Artikel ophalen mislukt ({url}): {exc}")
        return ""
