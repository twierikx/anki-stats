"""One-off discovery run: what is in the Anki collections, which feeds work, which Gemini models exist.

Prints deck names, note types with their fields, sample notes from the most active
decks, test results for candidate RSS feeds and the available Gemini models.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import time
from collections import Counter


import feedparser
import requests

from ankiweb_sync import AnkiWebError, download_collection

FEEDS = [
    "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/portada",
    "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/espana/portada",
    "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/ciencia/portada",
    "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/sociedad/portada",
    "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/clima-y-medio-ambiente/portada",
    "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/cultura/portada",
    "https://www.rtve.es/api/noticias.rss",
    "https://api2.rtve.es/rss/temas_noticias.xml",
    "https://api2.rtve.es/rss/temas_espana.xml",
    "https://api2.rtve.es/rss/temas_ciencia-y-tecnologia.xml",
    "https://www.rtve.es/rss/temas_noticias.xml",
    "https://www.agenciasinc.es/rss",
    "https://www.agenciasinc.es/rss/all",
    "https://www.eldiario.es/rss/",
    "https://www.20minutos.es/rss/",
    "https://www.europapress.es/rss/rss.aspx",
    "https://www.lavanguardia.com/rss/home.xml",
    "https://www.newtral.es/feed/",
]

UA = {"User-Agent": "Mozilla/5.0 (anki-stats nieuws; +https://github.com/twierikx/anki-stats)"}


def strip(s: str, n: int = 60) -> str:
    s = re.sub(r"<[^>]+>|\[sound:[^\]]+\]|&nbsp;", " ", s or "")
    s = re.sub(r"\s+", " ", s).strip()
    return s[:n]


def explore_collection(name: str, path: str) -> None:
    con = sqlite3.connect(path)
    now_ms = int(time.time() * 1000)
    month_ago = now_ms - 30 * 86_400_000
    decks = dict(con.execute("select id, name from decks"))
    notetypes = dict(con.execute("select id, name from notetypes"))
    fields: dict[int, list[str]] = {}
    for ntid, ord_, fname in con.execute("select ntid, ord, name from fields order by ntid, ord"):
        fields.setdefault(ntid, []).append(fname)

    cards_per_deck = Counter(d for (d,) in con.execute("select did from cards"))
    recent = Counter(
        d for (d,) in con.execute(
            "select c.did from revlog r join cards c on c.id = r.cid where r.id > ?", (month_ago,)
        )
    )
    print(f"\n==================== {name} ====================")
    print("Decks (kaarten | herhalingen laatste 30 dagen):")
    for did, dname in sorted(decks.items(), key=lambda x: -recent.get(x[0], 0)):
        if cards_per_deck.get(did):
            print(f"  {dname.replace(chr(31), '::')}  | {cards_per_deck[did]} | {recent.get(did, 0)}")

    print("Notitietypes en velden:")
    used_nt = Counter(nt for (nt,) in con.execute("select mid from notes"))
    for ntid, cnt in used_nt.most_common():
        print(f"  {notetypes.get(ntid, ntid)} ({cnt} notities): {fields.get(ntid)}")

    print("Voorbeelden uit de meest actieve decks:")
    for did, _ in recent.most_common(4):
        print(f"  -- {decks[did].replace(chr(31), '::')}")
        rows = con.execute(
            "select n.mid, n.flds, c.ord from revlog r join cards c on c.id = r.cid "
            "join notes n on n.id = c.nid where c.did = ? and r.id > ? "
            "group by n.id order by max(r.id) desc limit 4",
            (did, month_ago),
        ).fetchall()
        for mid, flds, ord_ in rows:
            vals = [strip(v, 40) for v in flds.split("\x1f")]
            pairs = ", ".join(f"{f}={v!r}" for f, v in zip(fields.get(mid, []), vals) if v)
            print(f"     [kaart {ord_}] {pairs}")
    con.close()


def explore_feeds() -> None:
    print("\n==================== RSS-feeds ====================")
    for url in FEEDS:
        try:
            r = requests.get(url, headers=UA, timeout=20)
            f = feedparser.parse(r.content)
            n = len(f.entries)
            desc = sum(1 for e in f.entries if strip(e.get("summary", ""), 500))
            print(f"{r.status_code} items={n:3d} met_samenvatting={desc:3d}  {url}")
            for e in f.entries[:3]:
                print(f"      · {strip(e.get('title', ''), 90)}  [{strip(e.get('summary', ''), 80)}]")
        except Exception as exc:
            print(f"ERR {url}: {exc}")


def explore_gemini() -> None:
    print("\n==================== Gemini ====================")
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        print("GEMINI_API_KEY ontbreekt nog.")
        return
    r = requests.get(
        "https://generativelanguage.googleapis.com/v1beta/models",
        headers={"x-goog-api-key": key}, params={"pageSize": 200}, timeout=30,
    )
    if r.status_code != 200:
        print(f"Fout {r.status_code}: {r.text[:300]}")
        return
    for m in r.json().get("models", []):
        if "generateContent" in m.get("supportedGenerationMethods", []):
            print(f"  {m['name']}  ({m.get('displayName', '')})")


def main() -> None:
    explore_feeds()
    explore_gemini()
    accounts = json.loads(os.environ["ANKI_ACCOUNTS"])
    for acc in accounts:
        try:
            explore_collection(acc["name"], download_collection(acc["username"], acc["password"]))
        except AnkiWebError as exc:
            print(f"{acc['name']}: {exc}")


if __name__ == "__main__":
    main()
