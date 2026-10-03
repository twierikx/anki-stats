"""Daily Spanish newspaper built around the words you are learning in Anki.

Usage:
  python krant.py --test     # build into out/ only (artifact), no publishing
  python krant.py            # build into docs/ (GitHub Pages) – used by the schedule
  python krant.py --demo     # canned data, no network/keys needed (for design work)

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
from datetime import datetime
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

import anki_words
import krant_html
from anki_words import Word, norm

TZ = ZoneInfo("Europe/Madrid")
MAX_RECENT = 70
MAX_WRONG = 40
MAX_REVIEWED = 60
MIN_ARTICLE_CHARS = 800
EARLIEST_HOUR = 6


@dataclass
class Article:
    rubrica: str
    titulo: str
    html: str
    source: str
    link: str
    tono: str


@dataclass
class Edition:
    name: str
    slug: str
    date: datetime
    articles: list[Article]
    words: list[dict]                       # for the bottom sheet, referenced by index
    counts: dict[str, int]
    review: list[int] = field(default_factory=list)  # indices into words
    model: str = ""


def slugify(name: str) -> str:
    s = unicodedata.normalize("NFD", name.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "lector"


# ------------------------------------------------------------- highlighting --

WORDCHARS = "A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9"


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
    for p in sorted(art.get("palabras", []), key=lambda p: -len(p.get("forma", ""))):
        lemma_key, form_key = norm(p.get("lema", "")), norm(p.get("forma", ""))
        if not lemma_key or lemma_key in seen_lemmas:
            continue
        if lemma_key in wrong or form_key in wrong:
            kind, card = "fout", wrong.get(lemma_key) or wrong.get(form_key)
        elif lemma_key in recent or form_key in recent:
            kind, card = "nieuw", recent.get(lemma_key) or recent.get(form_key)
        elif lemma_key in reviewed or form_key in reviewed:
            kind, card = "herhaald", reviewed.get(lemma_key) or reviewed.get(form_key)
        else:
            kind, card = "moeilijk", None
        span = find_span(text, p.get("forma", ""), taken)
        if span is None:
            continue
        lemma = card.lemma if card else p.get("lema", "").strip()
        key = (kind, norm(lemma))
        if key not in index:
            index[key] = len(words)
            words.append({
                "w": lemma,
                "nl": (p.get("nl") or (card.gloss if card else "")).strip(),
                "t": (p.get("tipo") or (card.pos if card else "")).strip(),
                "k": kind,
            })
        spans.append((span[0], span[1], index[key]))
        taken.append(span)
        seen_lemmas.add(lemma_key)

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

    listing = "\n\n".join(
        f"[{it.id}] {it.source}{(' · ' + it.section) if it.section else ''}\n"
        f"Titular: {it.title}\nEntradilla: {it.summary}"
        for it in items
    )
    res = gemini.generate_json(model, gemini.SELECT_SYSTEM,
                               f"Noticias disponibles:\n\n{listing}",
                               gemini.SELECT_SCHEMA, temperature=0.4)
    valid = {it.id for it in items}
    chosen, seen = [], set()
    for s in res.get("seleccion", []):
        if s.get("id") in valid and s["id"] not in seen:
            chosen.append(s)
            seen.add(s["id"])
    if len(chosen) < 3:
        raise SystemExit(f"Gemini koos te weinig berichten: {res}")
    return chosen[:12]


def with_full_text(chosen: list[dict], by_id: dict, want: int = 5) -> tuple[list[dict], dict]:
    """Fetch the article pages; keep the first `want` candidates that have enough text."""
    from nieuws import fetch_article

    texts: dict[int, str] = {}
    keep: list[dict] = []
    for c in chosen:
        text = by_id[c["id"]].content or fetch_article(by_id[c["id"]].link)
        print(f"  {len(text):5d} tekens  {by_id[c['id']].title[:70]}")
        if len(text) >= MIN_ARTICLE_CHARS:
            texts[c["id"]] = text
            keep.append(c)
        if len(keep) >= want:
            break
    if len(keep) < 3:  # sites blocked us: fall back to the RSS summaries
        for c in chosen:
            if c not in keep and len(keep) < want:
                texts[c["id"]] = by_id[c["id"]].summary
                keep.append(c)
    return keep, texts


def write_articles(model: str, chosen: list[dict], by_id: dict, texts: dict,
                   recent: list[Word], wrong: list[Word], reviewed: list[Word]) -> dict:
    import gemini

    def fmt(ws: list[Word]) -> str:
        return "\n".join(f"- {w.lemma} — {w.gloss}" for w in ws) or "(ninguna)"

    news = "\n\n".join(
        f"[{c['id']}] rúbrica: {c['rubrica']} · tono: {c['tono']} · fuente: {by_id[c['id']].source}\n"
        f"Titular: {by_id[c['id']].title}\nEntradilla: {by_id[c['id']].summary}\n"
        f"Texto del artículo:\n{texts.get(c['id'], by_id[c['id']].summary)}"
        for c in chosen
    )
    prompt = (
        f"LISTA REPASAR (palabras falladas, máxima prioridad):\n{fmt(wrong[:MAX_WRONG])}\n\n"
        f"LISTA NUEVAS (aprendidas hace poco):\n{fmt(recent[:MAX_RECENT])}\n\n"
        f"LISTA REPASADAS (contestadas 'difícil' o 'bien'; menos prioridad, úsalas si encajan):\n"
        f"{fmt(reviewed[:MAX_REVIEWED])}\n\n"
        f"Escribe una noticia para cada una de estas {len(chosen)} noticias, en el mismo orden "
        f"y con el mismo id:\n\n{news}"
    )
    return gemini.generate_json(model, gemini.WRITE_SYSTEM, prompt, gemini.WRITE_SCHEMA)


def make_edition(name: str, date: datetime, chosen: list[dict], by_id: dict,
                 written: dict, recent: list[Word], wrong: list[Word], reviewed: list[Word],
                 model: str) -> Edition:
    recent_d = {w.key: w for w in recent}
    reviewed_d = {w.key: w for w in reviewed}
    wrong_d = {w.key: w for w in wrong}
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
        ))

    # "Herhaal deze woorden": every wrong word, with a Dutch meaning from Gemini if possible
    repaso = {norm(r.get("lema", "")): r for r in written.get("repaso", [])}
    review = []
    for w in wrong[:MAX_WRONG]:
        key = ("fout", w.key)
        if key not in index:
            r = repaso.get(w.key, {})
            index[key] = len(words)
            words.append({"w": w.lemma, "nl": r.get("nl") or w.gloss,
                          "t": r.get("tipo") or w.pos, "k": "fout"})
        review.append(index[key])

    counts = {"nieuw": 0, "herhaald": 0, "fout": 0, "moeilijk": 0}
    in_text: set[int] = set()
    for a in arts:
        in_text.update(int(i) for i in re.findall(r'data-i="(\d+)"', a.html))
    for i in in_text:
        counts[words[i]["k"]] += 1
    return Edition(name, slugify(name), date, arts, words, counts, review, model)


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
    chosen = [{"id": 1, "rubrica": "Clima", "tono": "positivo"},
              {"id": 2, "rubrica": "Sociedad", "tono": "tendencia"},
              {"id": 3, "rubrica": "Cultura", "tono": "positivo"}]
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
                          P("poeta", "poeta", "dichter", "zelfst. nw. (m/v)"),
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
        for name in ("Thomas", "Margot"):
            save(demo_edition(name, now), root, archive=True)
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
    from nieuws import fetch_items, readable_sources

    print("Nieuws ophalen ...", flush=True)
    items = fetch_items()
    if len(items) < 8:
        sys.exit(f"Te weinig nieuws gevonden ({len(items)} berichten).")
    by_id = {it.id: it for it in items}
    model = gemini.pick_model()
    print(f"Gemini-model: {model}", flush=True)
    readable = readable_sources(items)
    pool = [it for it in items if it.content or it.source in readable]
    if len(pool) < 15:
        pool = items
    candidates = select_items(model, pool)
    print("Volledige artikelen ophalen ...", flush=True)
    chosen, texts = with_full_text(candidates, by_id)
    print("Gekozen: " + " | ".join(f"{c['tono']}: {by_id[c['id']].title[:60]}" for c in chosen))

    names = []
    for acc in accounts:
        name = acc["name"]
        print(f"\n{name}: Anki-woorden ophalen ...", flush=True)
        recent, wrong, reviewed = anki_words.load_words(
            download_collection(acc["username"], acc["password"]))
        print(f"  {len(recent)} nieuw, {len(wrong)} fout, {len(reviewed)} moeilijk/goed herhaald")
        written = write_articles(model, chosen, by_id, texts, recent, wrong, reviewed)
        ed = make_edition(name, now, chosen, by_id, written, recent, wrong, reviewed, model)
        print(f"  {len(ed.articles)} berichten, gemarkeerd: {ed.counts}")
        save(ed, root, archive=not args.test)
        names.append(name)

    (root / "index.html").write_text(krant_html.render_home(names), encoding="utf-8")
    (root / ".nojekyll").write_text("", encoding="utf-8")
    print(f"\nKlaar: {root}/")
    if not args.test and os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
            fh.write("published=true\n")


if __name__ == "__main__":
    main()
