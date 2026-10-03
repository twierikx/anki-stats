"""Pick the Spanish words to practise from an Anki collection.

- recent: Spanish cards answered for the first time in the last RECENT_DAYS days
- wrong:  Spanish cards answered "Again" (ease 1) in the last WRONG_DAYS days
"""

from __future__ import annotations

import re
import sqlite3
import time
import unicodedata
from dataclasses import dataclass

RECENT_DAYS = 30
WRONG_DAYS = 14
MIN_WORDS = 20  # top up with the most recently reviewed cards below this

# (Spanish field, gloss field) candidates, in order of preference
SPANISH_FIELDS = ["Spanish", "Expression", "ES", "Español", "Espanol"]
GLOSS_FIELDS = ["Dutch", "Nederlands", "NL", "NL/EN", "English", "Meaning"]
DECK_HINTS = ("spanish", "español", "espanol", "spaans")

POS = {
    "v": "werkwoord", "nf": "zelfst. nw. (vr.)", "nm": "zelfst. nw. (mnl.)",
    "nc": "zelfst. nw. (m/v)", "nmf": "zelfst. nw. (m/v)", "n": "zelfst. nw.",
    "adj": "bijv. nw.", "adv": "bijwoord", "prep": "voorzetsel", "conj": "voegwoord",
    "pron": "voornaamwoord", "art": "lidwoord", "interj": "tussenwerpsel", "num": "telwoord",
}


@dataclass
class Word:
    lemma: str        # "heredar"
    gloss: str        # meaning on the card (often English)
    pos: str          # Dutch word type from the card, may be ""
    kind: str         # "recent" or "wrong"
    last_ms: int      # last time answered
    lapses: int = 0   # how often "Again" in the window

    @property
    def key(self) -> str:
        return norm(self.lemma)


def norm(s: str) -> str:
    s = unicodedata.normalize("NFC", s.lower()).replace("ñ", "\x00")
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").replace("\x00", "ñ")
    return re.sub(r"\s+", " ", re.sub(r"[^a-zñ ]+", " ", s)).strip()


def clean(s: str) -> str:
    s = re.sub(r"\[sound:[^\]]*\]|<[^>]+>|&nbsp;", " ", s or "")
    s = re.sub(r"&[a-z]+;", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def split_lemma(raw: str) -> tuple[str, str]:
    """'heredar (v)' -> ('heredar', 'werkwoord'); 'de (prep) de' -> ('de', 'voorzetsel')."""
    raw = clean(raw)
    m = re.match(r"^(.*?)\s*\(([a-z]{1,6})\)", raw)
    if m:
        return m.group(1).strip(" ,;"), POS.get(m.group(2), "")
    return raw.strip(" ,;"), ""


def load_words(path: str, now_ms: int | None = None) -> tuple[list[Word], list[Word]]:
    now_ms = now_ms or int(time.time() * 1000)
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        fields: dict[int, list[str]] = {}
        for ntid, _ord, name in con.execute("select ntid, ord, name from fields order by ntid, ord"):
            fields.setdefault(ntid, []).append(name)
        decks = {did: name.lower() for did, name in con.execute("select id, name from decks")}
        spanish_decks = {d for d, n in decks.items() if any(h in n for h in DECK_HINTS)}

        def mapping(ntid: int) -> tuple[int, int] | None:
            names = fields.get(ntid, [])
            es = next((names.index(f) for f in SPANISH_FIELDS if f in names), None)
            gl = next((names.index(f) for f in GLOSS_FIELDS if f in names), None)
            return (es, gl) if es is not None and gl is not None else None

        rows = con.execute(
            "select r.id, r.ease, r.type, c.id, c.did, n.mid, n.flds "
            "from revlog r join cards c on c.id = r.cid join notes n on n.id = c.nid "
            "where r.ease > 0 and r.type < 4 order by r.id"
        ).fetchall()
    finally:
        con.close()

    recent_cut = now_ms - RECENT_DAYS * 86_400_000
    wrong_cut = now_ms - WRONG_DAYS * 86_400_000
    first: dict[int, int] = {}
    last: dict[int, int] = {}
    lapses: dict[int, int] = {}
    info: dict[int, tuple[str, str, str]] = {}
    for rid, ease, _type, cid, did, mid, flds in rows:
        if did not in spanish_decks:
            continue
        mp = mapping(mid)
        if not mp:
            continue
        if cid not in info:
            vals = flds.split("\x1f")
            lemma, pos = split_lemma(vals[mp[0]])
            gloss = clean(vals[mp[1]])[:80]
            if not lemma or len(lemma) > 40:
                continue
            info[cid] = (lemma, gloss, pos)
        first.setdefault(cid, rid)
        last[cid] = rid
        if ease == 1 and rid >= wrong_cut:
            lapses[cid] = lapses.get(cid, 0) + 1

    wrong: dict[str, Word] = {}
    for cid, n in lapses.items():
        lemma, gloss, pos = info[cid]
        w = Word(lemma, gloss, pos, "wrong", last[cid], n)
        if w.key and (w.key not in wrong or wrong[w.key].lapses < n):
            wrong[w.key] = w

    recent: dict[str, Word] = {}
    for cid, f in first.items():
        if f >= recent_cut:
            lemma, gloss, pos = info[cid]
            w = Word(lemma, gloss, pos, "recent", last[cid])
            if w.key and w.key not in wrong:
                recent.setdefault(w.key, w)

    if len(recent) + len(wrong) < MIN_WORDS:  # e.g. someone who barely studied lately
        for cid in sorted(last, key=last.get, reverse=True):
            lemma, gloss, pos = info[cid]
            w = Word(lemma, gloss, pos, "recent", last[cid])
            if w.key and w.key not in wrong and w.key not in recent:
                recent[w.key] = w
            if len(recent) + len(wrong) >= MIN_WORDS:
                break

    wrong_list = sorted(wrong.values(), key=lambda w: (-w.lapses, -w.last_ms))
    recent_list = sorted(recent.values(), key=lambda w: -w.last_ms)
    return recent_list, wrong_list
