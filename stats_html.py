"""Shared stats page: streaks, the last 7 days head to head, a 13-week calendar per person."""

from __future__ import annotations

from datetime import date
from html import escape

from krant_html import CSS, FONTS, DAG, fecha

STATS_CSS = """
.duel{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:20px 0 6px}
.side{border:1px solid var(--rule);border-radius:16px;padding:16px;background:var(--paper)}
.side .nm{font-family:"Bricolage Grotesque",system-ui,sans-serif;font-weight:700;font-size:18px}
.side .big{font-family:"Bricolage Grotesque",system-ui,sans-serif;font-size:40px;font-weight:800;
  line-height:1.05;margin:6px 0 2px;color:var(--flame)}
.side .big.off{color:var(--muted)}
.side .lbl,.tile .lbl{font-family:"Bricolage Grotesque",system-ui,sans-serif;font-size:13px;color:var(--muted)}
.side .wk{margin-top:10px;font-family:"Bricolage Grotesque",system-ui,sans-serif;font-size:14.5px}
.side .wk b{font-size:20px}
.crown{font-family:"Bricolage Grotesque",system-ui,sans-serif;font-size:15px;color:var(--muted);margin:4px 0 0}
.person{padding:24px 0 8px;border-top:1px solid var(--rule);margin-top:24px}
.person h2{margin-bottom:12px}
.tiles{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}
.tile{border:1px solid var(--rule);border-radius:14px;padding:12px 14px}
.tile .v{font-family:"Bricolage Grotesque",system-ui,sans-serif;font-size:24px;font-weight:700;color:var(--ink)}
.tile .s{font-family:"Bricolage Grotesque",system-ui,sans-serif;font-size:12.5px;color:var(--muted)}
.cal{margin-top:18px}
.cal h3{font-family:"Bricolage Grotesque",system-ui,sans-serif;font-size:15px;margin:0 0 8px;font-weight:600}
.grid{display:grid;grid-auto-flow:column;grid-template-rows:repeat(7,1fr);gap:3px}
.grid .c{aspect-ratio:1;border-radius:3px;background:var(--h0)}
.grid .c.f{background:transparent}
.grid .c[data-l="1"]{background:var(--h1)} .grid .c[data-l="2"]{background:var(--h2)}
.grid .c[data-l="3"]{background:var(--h3)} .grid .c[data-l="4"]{background:var(--h4)}
.grid .c.today{outline:1.5px solid var(--ink);outline-offset:1px}
.calkey{display:flex;align-items:center;gap:4px;justify-content:flex-end;margin-top:8px;
  font-family:"Bricolage Grotesque",system-ui,sans-serif;font-size:12px;color:var(--muted)}
.calkey i{width:11px;height:11px;border-radius:2px;display:inline-block}
.tip{position:fixed;z-index:20;pointer-events:none;background:var(--sheet);color:var(--ink);
  box-shadow:0 4px 18px rgba(0,0,0,.18);border-radius:8px;padding:6px 10px;font-size:13.5px;
  font-family:"Bricolage Grotesque",system-ui,sans-serif;opacity:0;transition:opacity .1s}
.tip.on{opacity:1}
:root{--h0:#ece7dc;--h1:#cde6d4;--h2:#97cda8;--h3:#58aa76;--h4:#2e8b57}
@media (prefers-color-scheme: dark){:root{--h0:#252321;--h1:#1d4430;--h2:#286a44;--h3:#3c975f;--h4:#5cc985}}
@media (max-width:380px){.side .big{font-size:34px}}
"""

STATS_JS = """
const tip = document.getElementById('tip');
let pinned = null;
function show(el){
  tip.textContent = el.dataset.t; tip.classList.add('on');
  const r = el.getBoundingClientRect(), w = tip.offsetWidth;
  tip.style.left = Math.max(8, Math.min(innerWidth - w - 8, r.left + r.width/2 - w/2)) + 'px';
  tip.style.top = (r.top - tip.offsetHeight - 8) + 'px';
}
function hide(){ tip.classList.remove('on'); pinned = null; }
document.querySelectorAll('.grid .c[data-t]').forEach(el => {
  el.addEventListener('pointerenter', e => { if(e.pointerType === 'mouse') show(el); });
  el.addEventListener('pointerleave', e => { if(e.pointerType === 'mouse' && !pinned) hide(); });
  el.addEventListener('click', e => { e.stopPropagation(); if(pinned === el){ hide(); } else { pinned = el; show(el); } });
});
document.addEventListener('click', hide);
addEventListener('scroll', hide, {passive:true});
"""

MESES_KORT = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def _levels(values: list[int]) -> list[int]:
    nonzero = sorted(v for v in values if v)
    if not nonzero:
        return [0] * len(values)
    q = [nonzero[int(len(nonzero) * f)] for f in (0.25, 0.5, 0.75)]
    return [0 if v == 0 else 1 + sum(v > t for t in q) for v in values]


def _calendar(o: dict) -> str:
    heat = o["heatmap"]
    first = date.fromisoformat(heat[0][0])
    pad = first.weekday()  # always 0 (we start on a Monday), kept for safety
    levels = _levels([n for _, n in heat])
    cells = ['<div class="c f"></div>'] * pad
    for (d, n), lv in zip(heat, levels):
        dd = date.fromisoformat(d)
        label = f"{DAG[dd.weekday()]} {dd.day} {MESES_KORT[dd.month - 1]}: " + (
            f"{n} herhalingen" if n else "niet geoefend")
        today = " today" if d == o["today"] else ""
        cells.append(f'<div class="c{today}" data-l="{lv}" data-t="{escape(label)}" '
                     f'aria-label="{escape(label)}"></div>')
    key = "".join(f'<i style="background:var(--h{i})"></i>' for i in range(5))
    return (f'<div class="cal"><h3>Laatste 13 weken</h3><div class="grid">{"".join(cells)}</div>'
            f'<div class="calkey">minder {key} meer</div></div>')


def _tile(value: str, label: str, sub: str = "") -> str:
    sub_html = f'<div class="s">{escape(sub)}</div>' if sub else ""
    return f'<div class="tile"><div class="lbl">{escape(label)}</div><div class="v">{escape(value)}</div>{sub_html}</div>'


def _person(o: dict) -> str:
    ret = f'{o["retention_30"]}%' if o["retention_30"] is not None else "–"
    delta = o["week_total"] - o["last_week_total"]
    tiles = "".join([
        _tile(f'🔥 {o["streak"]}', "Huidige reeks", f'langste ooit: {o["best_streak"]} dagen'),
        _tile(f'{o["days_30"]}/30', "Dagen geoefend", "afgelopen 30 dagen"),
        _tile(str(o["week_total"]), "Deze week", f'vorige week {o["last_week_total"]}'
              + (f" ({'+' if delta >= 0 else ''}{delta})" if o["last_week_total"] else "")),
        _tile(ret, "Goed beantwoord", "herhalingen, 30 dagen"),
        _tile(str(o["week_new"]), "Nieuwe kaarten", "deze week"),
        _tile(f'{o["mature_cards"]:,}'.replace(",", "."), "Goed in je geheugen",
              f'van {o["total_cards"]:,} kaarten'.replace(",", ".")),
    ])
    return (f'<section class="person"><h2>{escape(o["name"])}</h2><div class="tiles">{tiles}</div>'
            f"{_calendar(o)}</section>")


def _duel(stats: list[dict]) -> str:
    sides = []
    for o in stats:
        last7 = sum(n for _, n in o["last7"])
        days7 = sum(1 for _, n in o["last7"] if n)
        sides.append((days7, last7, o))
    html = "".join(
        f'<div class="side"><div class="nm">{escape(o["name"])}</div>'
        f'<div class="big{"" if o["streak"] else " off"}">🔥 {o["streak"]}</div>'
        f'<div class="lbl">{"dag" if o["streak"] == 1 else "dagen"} op rij</div>'
        f'<div class="wk"><b>{last7}</b> herhalingen<br>{days7}/7 dagen geoefend</div></div>'
        for days7, last7, o in sides
    )
    ranked = sorted(sides, key=lambda x: (x[0], x[1]), reverse=True)
    crown = ""
    if len(ranked) > 1 and ranked[0][1] and (ranked[0][0], ranked[0][1]) != (ranked[1][0], ranked[1][1]):
        crown = f'<p class="crown">🏆 {escape(ranked[0][2]["name"])} leidt de afgelopen 7 dagen.</p>'
    return f'<div class="duel">{html}</div>{crown}'


def render_stats(stats: list[dict], updated) -> str:
    return f"""<!doctype html>
<html lang="nl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<title>Estadísticas · Español con Anki</title>
{FONTS}
<style>{CSS}{STATS_CSS}</style></head>
<body><div class="wrap">
<header><div class="kicker">Español con Anki</div>
<h1>Estadísticas</h1><div class="date">{fecha(updated)}</div></header>
<p class="sans" style="font-size:14px;color:var(--muted);margin:14px 0 0">Afgelopen 7 dagen</p>
{_duel(stats)}
{''.join(_person(o) for o in stats)}
<div class="foot">Bijgewerkt {updated:%H:%M}, elke ochtend samen met de krant. Telt herhalingen die
in AnkiWeb staan, dus synchroniseer AnkiDroid voor het slapen gaan.<br>
{' · '.join(f'<a href="../{escape(o["slug"])}/">El diario de {escape(o["name"])}</a>' for o in stats)}</div>
</div>
<div class="tip" id="tip" role="tooltip"></div>
<script>{STATS_JS}</script>
</body></html>"""
