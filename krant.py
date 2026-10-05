"""Daily Spanish newspaper built around the words you are learning in Anki.

Usage:
  python krant.py --test   # build into out/ only (artifact), no publishing
  python krant.py          # build into docs/ (GitHub Pages) – used by the schedule
  python krant.py --demo   # canned data, no network/keys needed (for design work)

Environment: ANKI_ACCOUNTS, GEMINI_API_KEY, optional GEMINI_MODEL.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

import anki_words
import krant_html
from anki_words import Word, lemma_key

TZ = ZoneInfo("Europe/Madrid")
MAX_RECENT = 70
MAX_WRONG = 40
MAX_REVIEWED = 150
MIN_ARTICLE_CHARS = 800
MIN_BREVE_CHARS = 250
EARLIEST_HOUR = 6
# 1 lead story, 3 normal pieces and 3 short ones ("En breve")
SLOTS = {"principal": 1, "normal": 3, "breve": 3}
DEMOTE = {"principal": "normal", "normal": "breve", "breve": None}
ORDER = {"principal": 0, "normal": 1, "breve": 2}


@dataclass
class Article:
    rubrica: str
    titulo: str
    html: str
    source: str
    link: str
    tono: str
    formato: str = "normal"


@dataclass
class Edition:
    name: str
    slug: str
    date: datetime
    articles: list[Article]
    words: list[dict]                 # for the bottom sheet, referenced by index
    counts: dict[str, int]
    review: list[int] = field(default_factory=list)   # indices into words
    model: str = ""
    stats_me: dict | None = None
    stats_all: list = field(default_factory=list)


def slugify(name: str) -> str:
    s = unicodedata.normalize("NFD", name.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "lector"


# ------------------------------------------------------------- highlighting --

WORDCHARS = "A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9"
FUNCTION_POS = {"voorzetsel", "voegwoord", "lidwoord", "voornaamwoord", "telwoord"}
STOPWORDS = {"para", "como", "pero", "porque", "cuando", "donde", "desde", "hasta", "sobre",
             "entre", "este", "esta", "esto", "estos", "estas", "otro", "otra", "otros", "otras",
             "todo", "toda", "todos", "todas", "muy", "más", "mucho", "mucha", "muchos",
             "muchas", "también", "tambien", "ahora", "hacer", "tener", "estar", "haber",
             "poder", "decir", "ser", "año", "ano", "años", "anos", "cada", "bien"}


def base_form(lemma: str) -> str:
    """Dictionary form as written on the card, with accents: 'el poeta (nm)' -> 'poeta'."""
    s = re.split(r"[,/;(]", lemma or "", maxsplit=1)[0].strip()
    parts = s.split()
    if len(parts) > 1 and parts[0].lower() in anki_words.ARTICLES:
        s = " ".join(parts[1:])
    return s


def find_span(text: str, form: str, taken: list[tuple[int, int]]) -> tuple[int, int] | None:
    if not form.strip():
        return None
    pat = re.compile(rf"(?<![{WORDCHARS}]){re.escape(form.strip())}(?![{WORDCHARS}])", re.I)
    for m in pat.finditer(text):
        if all(m.end() <= a or m.start() >= b for a, b in taken):
            return m.span()
    return None


def paragraphs(text: str) -> str:
    parts = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n|\n", text.strip())]
    return "\n\n".join(p for p in parts if p)


def build_article(art: dict, recent: dict[str, Word], wrong: dict[str, Word],
                  reviewed: dict[str, Word], words: list[dict],
                  index: dict[tuple[str, str], int]) -> str:
    text = paragraphs(art["texto"])
    spans: list[tuple[int, int, int]] = []  # start, end, word index
    taken: list[tuple[int, int]] = []
    seen_lemmas: set[str] = set()

    def classify(*keys: str) -> tuple[str, Word | None]:
        for kind, d in (("fout", wrong), ("nieuw", recent), ("herhaald", reviewed)):
            for k in keys:
                if k and k in d:
                    return kind, d[k]
        return "moeilijk", None

    def mark(span, kind: str, card: Word | None, lemma: str, nl: str, tipo: str) -> None:
        key = (kind, lemma_key(lemma))
        if key not in index:
            index[key] = len(words)
            words.append({"w": lemma, "nl": nl.strip(), "t": tipo.strip(), "k": kind})
        spans.append((span[0], span[1], index[key]))
        taken.append(span)

    for p in sorted(art.get("palabras", []), key=lambda p: -len(p.get("forma", ""))):
        lemma_k, form_k = lemma_key(p.get("lema", "")), lemma_key(p.get("forma", ""))
        if not lemma_k or lemma_k in seen_lemmas:
            continue
        kind, card = classify(lemma_k, form_k)
        span = find_span(text, p.get("forma", ""), taken)
        if span is None:
            continue
        lemma = card.lemma if card else p.get("lema", "").strip()
        mark(span, kind, card, lemma,
             p.get("nl") or (card.gloss if card else ""),
             p.get("tipo") or (card.pos if card else ""))
        seen_lemmas.add(lemma_k)
        if card:
            seen_lemmas.add(card.key)

    # List words that appear literally (dictionary form) but Gemini forgot to report;
    # small function words ("para", "como") would only add noise, so they are skipped.
    for kind, d in (("fout", wrong), ("nieuw", recent), ("herhaald", reviewed)):
        for k, card in d.items():
            if k in seen_lemmas or len(k) < 4 or k in STOPWORDS or card.pos in FUNCTION_POS:
                continue
            span = find_span(text, base_form(card.lemma), taken)
            if span is None:
                continue
            mark(span, kind, card, card.lemma, card.gloss, card.pos)
            seen_lemmas.add(k)

    out, pos = [], 0
    for start, end, wi in sorted(spans):
        out.append(escape(text[pos:start]))
        kind = words[wi]["k"]
        out.append(
            f'<span class="w w-{kind}" role="button" tabindex="0" data-i="{wi}">'
            f"{escape(text[start:end])}</span>"
        )
        pos = end
    out.append(escape(text[pos:]))
    return "".join(out).replace("\n\n", "</p><p>")


# ------------------------------------------------------------------- Gemini --

def select_items(model: str, items) -> list[dict]:
    import gemini

    rank: dict[int, int] = {}
    per_source: dict[str, int] = {}
    for it in items:  # feeds list the front page roughly in order of prominence
        per_source[it.source] = per_source.get(it.source, 0) + 1
        rank[it.id] = per_source[it.source]
    listing = "\n\n".join(
        f"[{it.id}] {it.source} (#{rank[it.id]} en su portada)"
        f"{(' · ' + it.section) if it.section else ''}\n"
        f"Titular: {it.title}\nEntradilla: {it.summary[:220]}"
        for it in items
    )
    res = gemini.generate_json(model, gemini.SELECT_SYSTEM,
                               f"Noticias disponibles:\n\n{listing}",
                               gemini.SELECT_SCHEMA, temperature=0.4, thinking="low",
                               label="selectie")
    valid = {it.id for it in items}
    chosen, seen = [], set()
    for s in res.get("seleccion", []):
        if s.get("id") in valid and s["id"] not in seen:
            if s.get("formato") not in SLOTS:
                s["formato"] = "normal"
            chosen.append(s)
            seen.add(s["id"])
    if len(chosen) < 3:
        raise SystemExit(f"Gemini koos te weinig berichten: {res}")
    return chosen[:18]


def with_full_text(chosen: list[dict], by_id: dict) -> tuple[list[dict], dict]:
    """Fill 1 lead, 3 normal and 3 short slots from the ranked candidates, fetching the
    article pages; a candidate whose slot is full moves down one format."""
    from nieuws import fetch_article

    free = dict(SLOTS)
    want = sum(SLOTS.values())
    texts: dict[int, str] = {}
    keep: list[dict] = []
    topics: set[str] = set()
    for c in chosen:
        topic = (c.get("tema") or "").strip().lower()
        if topic and topic in topics:
            print(f"  overgeslagen (al een bericht over '{topic}'): {by_id[c['id']].title[:60]}")
            continue
        fmt = c.get("formato", "normal")
        while fmt and not free[fmt]:
            fmt = DEMOTE[fmt]
        if not fmt:
            continue
        item = by_id[c["id"]]
        text = item.content or fetch_article(item.link)
        if fmt == "breve" and len(text) < MIN_BREVE_CHARS and len(item.summary) >= 150:
            text = item.summary
        need = MIN_BREVE_CHARS if fmt == "breve" else MIN_ARTICLE_CHARS
        if len(text) < need and fmt != "breve" and len(text) >= MIN_BREVE_CHARS and free["breve"]:
            fmt, need = "breve", MIN_BREVE_CHARS  # too little text for a full piece
        print(f"  {len(text):5d} tekens  {fmt:<9} {item.title[:64]}")
        if len(text) >= need:
            c["formato"] = fmt
            free[fmt] -= 1
            texts[c["id"]] = text
            keep.append(c)
            if topic:
                topics.add(topic)
        if len(keep) >= want:
            break
    if len(keep) < 3:  # sites blocked us: fall back to the RSS summaries
        for c in chosen:
            if c not in keep and len(keep) < 5:
                texts[c["id"]] = by_id[c["id"]].summary
                c["formato"] = "breve"
                keep.append(c)
    if keep and not any(c["formato"] == "principal" for c in keep):
        lead = next((c for c in keep if c["formato"] == "normal"), keep[0])
        lead["formato"] = "principal"
    keep.sort(key=lambda c: ORDER[c["formato"]])  # stable: keeps the editor's ranking
    return keep, texts


def write_articles(model: str, chosen: list[dict], by_id: dict, texts: dict,
                   recent: list[Word], wrong: list[Word], reviewed: list[Word],
                   other: dict | None = None) -> dict:
    import gemini

    def fmt(ws: list[Word]) -> str:
        return "\n".join(f"- {w.lemma} — {w.gloss}" for w in ws) or "(ninguna)"

    news = "\n\n".join(
        f"[{c['id']}] formato: {c.get('formato', 'normal')} · rúbrica: {c['rubrica']} · "
        f"tono: {c['tono']} · fuente: {by_id[c['id']].source}\n"
        f"Titular: {by_id[c['id']].title}\nEntradilla: {by_id[c['id']].summary}\n"
        f"Texto del artículo:\n{texts.get(c['id'], by_id[c['id']].summary)}"
        for c in chosen
    )
    prompt = (
        f"LISTA REPASAR (palabras falladas: máxima prioridad, úsalas varias veces):\n"
        f"{fmt(wrong[:MAX_WRONG])}\n\n"
        f"LISTA NUEVAS (aprendidas hace poco: usa al menos tres cuartas partes):\n"
        f"{fmt(recent[:MAX_RECENT])}\n\n"
        f"LISTA REPASADAS (repasadas en los últimos meses: úsalas siempre que encajen):\n"
        f"{fmt(reviewed[:MAX_REVIEWED])}\n\n"
        f"Escribe una noticia para cada una de estas {len(chosen)} noticias, en el mismo orden, "
        f"con el mismo id y con la longitud que indica su formato:\n\n{news}"
    )
    if other and other.get("articulos"):
        versions = "\n\n".join(
            f"[{a.get('id')}] {a.get('titulo', '')}\n{a.get('texto', '')}" for a in other["articulos"])
        prompt += (
            "\n\nVERSIÓN QUE YA ESCRIBISTE PARA OTRO LECTOR (con otras palabras de vocabulario). "
            "Escribe para ESTE lector una versión claramente distinta de las mismas noticias: otro "
            "titular, otra entrada, otro orden de las ideas, otras frases y, si el artículo los "
            "ofrece, otros detalles. Construye las frases alrededor de las palabras de ESTE lector. "
            "No copies frases de esta versión:\n\n" + versions
        )
    return gemini.generate_json(model, gemini.WRITE_SYSTEM, prompt, gemini.WRITE_SCHEMA,
                                label="schrijven")


def make_edition(name: str, date: datetime, chosen: list[dict], by_id: dict,
                 written: dict, recent: list[Word], wrong: list[Word], reviewed: list[Word],
                 model: str) -> Edition:
    recent_d = {w.key: w for w in recent[:MAX_RECENT]}
    reviewed_d = {w.key: w for w in reviewed[:MAX_REVIEWED]}
    wrong_d = {w.key: w for w in wrong[:MAX_WRONG]}
    words: list[dict] = []
    index: dict[tuple[str, str], int] = {}
    arts: list[Article] = []
    written_by_id = {a.get("id"): a for a in written.get("articulos", [])}
    for n, c in enumerate(chosen):
        art = written_by_id.get(c["id"])
        if art is None and n < len(written.get("articulos", [])):
            art = written["articulos"][n]
        if not art or not art.get("texto"):
            continue
        item = by_id[c["id"]]
        arts.append(Article(
            rubrica=(art.get("rubrica") or c["rubrica"]).strip(),
            titulo=art["titulo"].strip(),
            html=build_article(art, recent_d, wrong_d, reviewed_d, words, index),
            source=item.source, link=item.link, tono=c.get("tono", ""),
            formato=c.get("formato", "normal"),
        ))

    counts = {"nieuw": 0, "herhaald": 0, "fout": 0, "moeilijk": 0}
    in_text: set[int] = set()
    for a in arts:
        in_text.update(int(i) for i in re.findall(r'data-i="(\d+)"', a.html))
    for i in in_text:
        counts[words[i]["k"]] += 1

    # "Herhaal deze woorden": every wrong word, with a Dutch meaning from Gemini if possible
    repaso = {lemma_key(r.get("lema", "")): r for r in written.get("repaso", [])}
    review = []
    for w in wrong[:MAX_WRONG]:
        key = ("fout", w.key)
        if key not in index:
            r = repaso.get(w.key, {})
            index[key] = len(words)
            words.append({"w": w.lemma, "nl": r.get("nl") or w.gloss,
                          "t": r.get("tipo") or w.pos, "k": "fout"})
        review.append(index[key])
    return Edition(name, slugify(name), date, arts, words, counts, review, model)


def coverage(ed: Edition, recent: list[Word], wrong: list[Word]) -> str:
    """One log line: how much of the Anki lists made it into the text."""
    used = {(w["k"], lemma_key(w["w"])) for i, w in enumerate(ed.words)
            if f'data-i="{i}"' in "".join(a.html for a in ed.articles)}
    n_wrong = sum(1 for w in wrong[:MAX_WRONG] if ("fout", w.key) in used)
    n_new = sum(1 for w in recent[:MAX_RECENT] if ("nieuw", w.key) in used)
    c = ed.counts
    anki = c["nieuw"] + c["herhaald"] + c["fout"]
    total = anki + c["moeilijk"]
    pct = round(100 * anki / total) if total else 0
    return (f"  Anki: fout {n_wrong}/{min(len(wrong), MAX_WRONG)}, "
            f"nieuw {n_new}/{min(len(recent), MAX_RECENT)}, herhaald {c['herhaald']}; "
            f"{pct}% van de gemarkeerde woorden komt uit Anki")


# --------------------------------------------------------------------- demo --

def demo_edition(name: str, date: datetime) -> Edition:
    recent = [Word("heredar", "to inherit", "werkwoord", "recent", 0),
              Word("declaración", "statement", "zelfst. nw. (vr.)", "recent", 0),
              Word("rodilla", "knee", "zelfst. nw. (vr.)", "recent", 0),
              Word("poeta", "poet", "zelfst. nw. (m/v)", "recent", 0),
              Word("crecer", "to grow", "werkwoord", "recent", 0)]
    wrong = [Word("figurar", "to appear", "werkwoord", "wrong", 0, 2),
             Word("alcanzar", "to reach", "werkwoord", "wrong", 0, 1),
             Word("lograr", "to achieve", "werkwoord", "wrong", 0, 1),
             Word("disminuir", "to decrease", "werkwoord", "wrong", 0, 1)]
    reviewed = [Word("ciudad", "city", "zelfst. nw. (vr.)", "reviewed", 0),
                Word("precio", "price", "zelfst. nw. (mnl.)", "reviewed", 0)]

    class It:  # minimal stand-in for nieuws.Item
        def __init__(self, source, link):
            self.source, self.link = source, link

    by_id = {1: It("El País", "https://elpais.com/"), 2: It("elDiario.es", "https://eldiario.es/"),
             3: It("El País", "https://elpais.com/")}
    chosen = [{"id": 1, "rubrica": "Clima", "tono": "positivo", "formato": "principal"},
              {"id": 2, "rubrica": "Sociedad", "tono": "tendencia", "formato": "normal"},
              {"id": 3, "rubrica": "Cultura", "tono": "positivo", "formato": "breve"}]
    P = lambda f, l, nl, t: {"forma": f, "lema": l, "nl": nl, "tipo": t}  # noqa: E731
    written = {
        "articulos": [
            {"id": 1, "rubrica": "Clima", "titulo": "Más coches eléctricos en las calles",
             "texto": "Cada año más familias españolas compran un coche eléctrico. Ya son uno de "
                      "cada cuatro coches nuevos. Las ayudas públicas y los precios más bajos "
                      "ayudan a alcanzar esta cifra, y las emisiones empiezan a disminuir.\n\n"
                      "En las grandes ciudades se nota más el cambio. Hay más puntos de carga y "
                      "el precio de la electricidad es más estable que el de la gasolina.\n\n"
                      "Los expertos creen que la tendencia seguirá en los próximos años.",
             "palabras": [P("alcanzar", "alcanzar", "bereiken", "werkwoord"),
                          P("disminuir", "disminuir", "afnemen", "werkwoord"),
                          P("ayudas", "ayuda", "subsidie", "zelfst. nw. (vr.)"),
                          P("emisiones", "emisión", "uitstoot", "zelfst. nw. (vr.)"),
                          P("ciudades", "ciudad", "stad", "zelfst. nw. (vr.)"),
                          P("precio", "precio", "prijs", "zelfst. nw. (mnl.)")]},
            {"id": 2, "rubrica": "Sociedad", "titulo": "La vivienda, el gran tema del año",
             "texto": "Miles de personas salieron a la calle en Madrid para pedir vivienda "
                      "asequible. Muchos jóvenes no pueden heredar una casa ni pagar un alquiler. "
                      "El tema ya figura en el centro del debate político.",
             "palabras": [P("heredar", "heredar", "erven", "werkwoord"),
                          P("figura", "figurar", "voorkomen, staan", "werkwoord"),
                          P("asequible", "asequible", "betaalbaar", "bijv. nw."),
                          P("alquiler", "alquiler", "huur", "zelfst. nw. (mnl.)")]},
            {"id": 3, "rubrica": "Cultura", "titulo": "Un museo que vuelve a crecer",
             "texto": "El Museo de Bellas Artes de Bilbao abre una nueva ampliación. Un poeta "
                      "local leyó una declaración en la inauguración. El museo quiere lograr "
                      "que más vecinos lo visiten.",
             "palabras": [P("crecer", "crecer", "groeien", "werkwoord"),
                          P("declaración", "declaración", "verklaring", "zelfst. nw. (vr.)"),
                          P("lograr", "lograr", "bereiken, voor elkaar krijgen", "werkwoord"),
                          P("ampliación", "ampliación", "uitbreiding", "zelfst. nw. (vr.)")]},
        ],
        "repaso": [{"lema": "figurar", "nl": "voorkomen, vermeld staan", "tipo": "werkwoord"},
                   {"lema": "alcanzar", "nl": "bereiken", "tipo": "werkwoord"},
                   {"lema": "lograr", "nl": "bereiken, slagen in", "tipo": "werkwoord"},
                   {"lema": "disminuir", "nl": "afnemen, verminderen", "tipo": "werkwoord"}],
    }
    return make_edition(name, date, chosen, by_id, written, recent, wrong, reviewed, "demo")


# --------------------------------------------------------------------- main --

def save(ed: Edition, root: Path, archive: bool) -> None:
    folder = root / ed.slug
    folder.mkdir(parents=True, exist_ok=True)
    day = ed.date.strftime("%Y-%m-%d")
    html = krant_html.render(ed)
    (folder / "index.html").write_text(html, encoding="utf-8")
    if archive:
        (folder / f"{day}.html").write_text(html, encoding="utf-8")
        dates = sorted((p.stem for p in folder.glob("20??-??-??.html")), reverse=True)
        (folder / "archief.html").write_text(krant_html.render_archive(ed.name, dates), "utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true", help="alleen out/ vullen, niet publiceren")
    ap.add_argument("--demo", action="store_true", help="nepgegevens, geen netwerk")
    ap.add_argument("--force", action="store_true", help="tijd- en dubbelcontrole overslaan")
    args = ap.parse_args()

    now = datetime.now(TZ)
    root = Path("out" if (args.test or args.demo) else "docs")

    if args.demo:
        import stats as st
        import stats_html
        from weekly_report import demo_collection
        overviews = []
        for seed, name in ((1, "Thomas"), (2, "Margot")):
            o = st.overview(name, demo_collection(seed, now.date()), now.date())
            o["slug"] = slugify(name)
            overviews.append(o)
        for o in overviews:
            ed = demo_edition(o["name"], now)
            ed.stats_me, ed.stats_all = o, overviews
            save(ed, root, archive=True)
        (root / "stats").mkdir(parents=True, exist_ok=True)
        (root / "stats" / "index.html").write_text(stats_html.render_stats(overviews, now), "utf-8")
        (root / "index.html").write_text(krant_html.render_home(["Thomas", "Margot"]), "utf-8")
        print(f"Demo geschreven naar {root}/")
        return

    accounts = json.loads(os.environ.get("ANKI_ACCOUNTS") or "[]")
    if not accounts:
        sys.exit("ANKI_ACCOUNTS ontbreekt.")
    if not args.test and not args.force:
        if now.hour < EARLIEST_HOUR:
            print(f"Het is {now:%H:%M} in Madrid: te vroeg, deze run slaat over.")
            return
        if (root / slugify(accounts[0]["name"]) / f"{now:%Y-%m-%d}.html").exists():
            print("De krant van vandaag bestaat al.")
            return

    import gemini
    from ankiweb_sync import download_collection
    from nieuws import fetch_items, usable_items

    print("Nieuws ophalen ...", flush=True)
    items = fetch_items()
    if len(items) < 8:
        sys.exit(f"Te weinig nieuws gevonden ({len(items)} berichten).")
    by_id = {it.id: it for it in items}
    model = gemini.pick_model()
    lite = gemini.pick_model(lite=True)
    print(f"Gemini-modellen: schrijven {model}, selectie {lite}", flush=True)
    pool = usable_items(items)
    if len(pool) < 15:
        pool = items
    candidates = select_items(lite, pool)
    print("Volledige artikelen ophalen ...", flush=True)
    chosen, texts = with_full_text(candidates, by_id)
    print("Gekozen: " + " | ".join(f"{c['formato']}/{c['tono']}: {by_id[c['id']].title[:50]}"
                                   for c in chosen))

    import stats as st
    import stats_html
    from ankiweb_sync import AnkiWebError

    people = []
    for acc in accounts:
        name = acc["name"]
        print(f"\n{name}: Anki ophalen ...", flush=True)
        try:
            path = download_collection(acc["username"], acc["password"])
        except AnkiWebError as exc:
            print(f"::warning::{name} overgeslagen: {exc}")
            continue
        recent, wrong, reviewed = anki_words.load_words(path)
        col = st.load_collection(path)
        overview = st.overview(name, col, (now - timedelta(hours=col.rollover)).date())
        overview["slug"] = slugify(name)
        print(f"  {len(recent)} nieuw, {len(wrong)} fout, {len(reviewed)} herhaald (90 dagen); "
              f"reeks {overview['streak']}")
        people.append((name, recent, wrong, reviewed, overview))
    if not people:
        sys.exit("Van geen enkel account konden de Anki-gegevens worden opgehaald.")
    overviews = [p[4] for p in people]

    names, previous = [], None
    for name, recent, wrong, reviewed, overview in people:
        print(f"\n{name}: krant schrijven ...", flush=True)
        written = write_articles(model, chosen, by_id, texts, recent, wrong, reviewed, previous)
        previous = written
        ed = make_edition(name, now, chosen, by_id, written, recent, wrong, reviewed, model)
        ed.stats_me, ed.stats_all = overview, overviews
        print(f"  {len(ed.articles)} berichten, gemarkeerd: {ed.counts}")
        print(coverage(ed, recent, wrong))
        save(ed, root, archive=not args.test)
        names.append(name)

    (root / "stats").mkdir(parents=True, exist_ok=True)
    (root / "stats" / "index.html").write_text(stats_html.render_stats(overviews, now), "utf-8")
    gemini.print_usage()
    (root / "index.html").write_text(krant_html.render_home(names), encoding="utf-8")
    (root / ".nojekyll").write_text("", encoding="utf-8")
    print(f"\nKlaar: {root}/")
    if not args.test and os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
            fh.write("published=true\n")


if __name__ == "__main__":
    main()
