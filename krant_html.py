"""HTML for the daily newspaper page (mobile first, light/dark, tap-to-translate)."""

from __future__ import annotations

import json
from html import escape

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]

FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500..800'
    '&family=Literata:ital,opsz,wght@0,7..72,400;0,7..72,600;1,7..72,400&display=swap" rel="stylesheet">'
)

CSS = """
:root{
  --bg:#f8f5ef; --paper:#fffdf9; --ink:#1f1d1a; --muted:#6f6a61; --rule:#e4ded2;
  --new:#2e8b57; --wrong:#c63a2f; --hard:#8b8476; --accent:#1f1d1a;
  --l-new:rgba(46,139,87,.55); --l-rev:rgba(46,139,87,.4); --l-wrong:rgba(198,58,47,.42); --l-hard:rgba(139,132,118,.55);
  --sheet:#ffffff; --shadow:0 -8px 30px rgba(30,25,15,.16); --chip:#efe9dd; --flame:#d9822b;
}
@media (prefers-color-scheme: dark){
  :root{
    --bg:#121211; --paper:#1a1918; --ink:#ece8e0; --muted:#a39d92; --rule:#2e2c29;
    --new:#5cc985; --wrong:#ff6f61; --hard:#9b9488; --accent:#ece8e0;
    --l-new:rgba(92,201,133,.5); --l-rev:rgba(92,201,133,.38); --l-wrong:rgba(255,111,97,.45); --l-hard:rgba(155,148,136,.55);
    --sheet:#232220; --shadow:0 -8px 30px rgba(0,0,0,.5); --chip:#2b2926; --flame:#f0a04b;
  }
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);
  font-family:"Literata",Georgia,"Times New Roman",serif;font-size:19px;line-height:1.62;
  -webkit-font-smoothing:antialiased}
.wrap{max-width:640px;margin:0 auto;padding:22px 18px 140px}
.sans,h1,h2,.kicker,.rubric,.legend,.review h3,.sheet,.foot,button{
  font-family:"Bricolage Grotesque",system-ui,-apple-system,"Segoe UI",sans-serif}
header{border-bottom:3px solid var(--accent);padding-bottom:14px;margin-bottom:18px}
.kicker{font-size:13px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);font-weight:600}
h1{font-size:44px;line-height:1;margin:6px 0 8px;font-weight:800;letter-spacing:-.02em;
  font-variation-settings:"opsz" 96}
.date{font-size:16px;color:var(--muted);font-style:italic}
.legend{display:flex;flex-wrap:wrap;gap:8px 16px;font-size:14.5px;color:var(--muted);
  padding:12px 0 16px;border-bottom:1px solid var(--rule)}
.legend b{color:var(--ink);font-weight:700}
.legend .hint{flex-basis:100%;font-size:13.5px}
article{padding:22px 0 20px;border-bottom:1px solid var(--rule)}
.rubric{display:inline-block;font-size:12.5px;font-weight:700;letter-spacing:.1em;
  text-transform:uppercase;color:var(--muted);margin-bottom:6px}
.rubric.positivo{color:var(--new)}
h2{font-size:27px;line-height:1.15;margin:0 0 10px;font-weight:700;letter-spacing:-.01em;
  font-variation-settings:"opsz" 48}
article p{margin:0 0 10px}
.src{font-size:14px;color:var(--muted)}
.src a{color:inherit;text-underline-offset:3px}
.w{cursor:pointer;text-underline-offset:5px;text-decoration-skip-ink:auto;
  border-radius:3px;transition:background .15s;-webkit-tap-highlight-color:transparent}
.w-nieuw{text-decoration:underline 1.5px var(--l-new)}
.w-herhaald{text-decoration:underline 1.5px var(--l-rev)}
.w-fout{text-decoration:underline wavy 1px var(--l-wrong)}
.w-moeilijk{text-decoration:underline dotted 1.5px var(--l-hard)}
.w.on,.w:focus-visible{background:var(--chip);outline:none}
.sample{cursor:default;font-style:normal;font-family:"Literata",Georgia,serif;color:var(--ink)}
.review{margin-top:26px;padding:18px;border:1px solid var(--rule);border-radius:16px;background:var(--paper)}
.review h3{margin:0 0 4px;font-size:20px}
.review p{margin:0 0 12px;font-size:15px;color:var(--muted)}
.chips{display:flex;flex-wrap:wrap;gap:8px}
.chip{font:inherit;font-family:"Literata",Georgia,serif;font-size:17px;color:var(--ink);
  background:var(--chip);border:1.5px solid transparent;border-radius:999px;padding:6px 14px;cursor:pointer}
.chip.on{border-color:var(--wrong)}
.pulse{margin-top:22px;padding:16px 18px;border:1px solid var(--rule);border-radius:16px;
  font-family:"Bricolage Grotesque",system-ui,sans-serif;font-size:14.5px;color:var(--muted)}
.pulse .row{display:flex;flex-wrap:wrap;gap:6px 18px;align-items:baseline}
.pulse .who{color:var(--ink);font-weight:600}
.pulse .fl{color:var(--flame);font-weight:700}
.pulse .fl.off{color:var(--muted);font-weight:600}
.mini{display:flex;gap:6px;align-items:flex-end;height:44px;margin:14px 0 4px}
.mini div{flex:1;text-align:center}
.mini i{display:block;border-radius:3px 3px 1px 1px;background:var(--l-new);min-height:3px}
.mini i.zero{background:var(--rule)}
.mini span{display:block;font-size:11.5px;margin-top:4px}
.pulse a{color:var(--ink);font-weight:600;text-underline-offset:3px}
.foot{margin-top:28px;font-size:13.5px;color:var(--muted);line-height:1.5}
.foot a{color:inherit}
.sheet{position:fixed;left:0;right:0;bottom:0;z-index:10;display:flex;justify-content:center;
  transform:translateY(110%);visibility:hidden;pointer-events:none;
  transition:transform .22s ease-out,visibility 0s .22s}
.sheet.open{transform:none;visibility:visible;pointer-events:auto;transition:transform .22s ease-out}
.sheet .card{width:100%;max-width:640px;background:var(--sheet);box-shadow:var(--shadow);
  border-radius:20px 20px 0 0;padding:14px 20px calc(18px + env(safe-area-inset-bottom))}
.grip{width:40px;height:4px;border-radius:2px;background:var(--rule);margin:0 auto 12px}
.kind{font-size:12.5px;font-weight:700;letter-spacing:.08em;text-transform:uppercase}
.kind.nieuw,.kind.herhaald{color:var(--new)} .kind.fout{color:var(--wrong)} .kind.moeilijk{color:var(--muted)}
.sw{font-size:32px;font-weight:800;line-height:1.1;margin:4px 0 2px}
.st{font-size:15px;color:var(--muted)}
.snl{font-family:"Literata",Georgia,serif;font-size:21px;margin:10px 0 14px}
.close{width:100%;font-size:16px;font-weight:600;padding:12px;border-radius:12px;border:0;
  background:var(--chip);color:var(--ink);cursor:pointer}
@media (max-width:380px){h1{font-size:38px}h2{font-size:24px}body{font-size:18px}}
@media (prefers-reduced-motion:reduce){.sheet{transition:none}}
"""

JS = """
const W = JSON.parse(document.getElementById('words').textContent);
const sheet = document.getElementById('sheet');
const KIND = {nieuw:'Recent geleerd in Anki', herhaald:'Herhaald in Anki (moeilijk/goed)', fout:'Fout beantwoord in Anki', moeilijk:'Moeilijk woord'};
let current = null;
function close(){ sheet.classList.remove('open'); sheet.setAttribute('aria-hidden','true');
  if(current) current.classList.remove('on'); current = null; }
function open(el){
  if(current === el){ close(); return; }
  if(current) current.classList.remove('on');
  const w = W[+el.dataset.i];
  const k = sheet.querySelector('.kind'); k.className = 'kind ' + w.k; k.textContent = KIND[w.k];
  sheet.querySelector('.sw').textContent = w.w;
  sheet.querySelector('.st').textContent = w.t || '';
  sheet.querySelector('.snl').textContent = w.nl || '–';
  el.classList.add('on'); current = el;
  sheet.classList.add('open'); sheet.setAttribute('aria-hidden','false');
}
document.addEventListener('click', e => {
  const el = e.target.closest('[data-i]');
  if(el){ open(el); return; }
  if(e.target.closest('.close')) close();
});
document.addEventListener('keydown', e => {
  if(e.key === 'Escape') close();
  const el = e.target.closest && e.target.closest('.w[data-i]');
  if(el && (e.key === 'Enter' || e.key === ' ')){ e.preventDefault(); open(el); }
});
"""


def fecha(d) -> str:
    return f"{DIAS[d.weekday()]}, {d.day} de {MESES[d.month - 1]} de {d.year}"


def _legend(c: dict) -> str:
    return (
        '<div class="legend">'
        f'<span><span class="w w-nieuw sample">groen</span> <b>{c["nieuw"] + c.get("herhaald", 0)}</b> uit je Anki</span>'
        f'<span><span class="w w-fout sample">rood</span> <b>{c["fout"]}</b> fout beantwoord</span>'
        f'<span><span class="w w-moeilijk sample">gestippeld</span> <b>{c["moeilijk"]}</b> moeilijk</span>'
        '<span class="hint">Tik op een woord voor de vertaling.</span></div>'
    )


DAG = ["ma", "di", "wo", "do", "vr", "za", "zo"]


def pulse(me: dict | None, everyone: list[dict], link: str = "../stats/") -> str:
    """Small stats block under the newspaper: both streaks, my last 7 days, link."""
    if not me:
        return ""
    others = [o for o in everyone if o["name"] != me["name"]]
    flames = "".join(
        f'<span><span class="fl{"" if o["streak"] else " off"}">🔥 {o["streak"]}</span> '
        f'<span class="who">{escape(o["name"])}</span></span>'
        for o in [me] + others
    )
    top = max(n for _, n in me["last7"]) or 1
    bars = "".join(
        f'<div><i class="{"zero" if not n else ""}" style="height:{max(3, round(36 * n / top))}px"'
        f' title="{n} herhalingen"></i><span>{DAG[wd]}</span></div>'
        for wd, n in me["last7"]
    )
    total7 = sum(n for _, n in me["last7"])
    return (
        '<section class="pulse"><div class="row">' + flames + "</div>"
        f'<div class="mini" aria-label="Herhalingen per dag, laatste 7 dagen">{bars}</div>'
        f'<div class="row"><span>Gisteren <b class="who">{me["yesterday"]}</b> herhalingen</span>'
        f'<span>7 dagen <b class="who">{total7}</b></span>'
        f'<a href="{link}">Alle statistieken →</a></div></section>'
    )


def render(ed) -> str:
    arts = []
    for a in ed.articles:
        tone = " positivo" if a.tono == "positivo" else ""
        arts.append(
            f'<article><span class="rubric{tone}">{escape(a.rubrica)}</span>'
            f"<h2>{escape(a.titulo)}</h2><p>{a.html}</p>"
            f'<div class="src">Bron: <a href="{escape(a.link)}" rel="noopener" target="_blank">'
            f"{escape(a.source)}</a></div></article>"
        )
    review = ""
    if ed.review:
        chips = "".join(
            f'<button class="chip" data-i="{i}">{escape(ed.words[i]["w"])}</button>'
            for i in ed.review
        )
        review = (
            '<section class="review"><h3>Herhaal deze woorden</h3>'
            "<p>Deze had je de afgelopen twee weken fout in Anki. Tik voor de betekenis.</p>"
            f'<div class="chips">{chips}</div></section>'
        )
    words_json = json.dumps(ed.words, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<title>El diario de {escape(ed.name)} · {ed.date:%d-%m}</title>
{FONTS}
<style>{CSS}</style></head>
<body><div class="wrap">
<header><div class="kicker">El diario de {escape(ed.name)}</div>
<h1>Noticias de hoy</h1><div class="date">{fecha(ed.date)}</div></header>
{_legend(ed.counts)}
{''.join(arts)}
{review}
{pulse(getattr(ed, "stats_me", None), getattr(ed, "stats_all", []))}
<div class="foot">Noticias reales de las fuentes enlazadas, contadas de nuevo en español
(nivel B2) por Gemini. Comprueba los detalles en el artículo original.<br>
<a href="archief.html">Archief</a> · bijgewerkt {ed.date:%H:%M}</div>
</div>
<div class="sheet" id="sheet" aria-hidden="true" role="dialog" aria-live="polite"><div class="card">
<div class="grip"></div><div class="kind"></div><div class="sw"></div><div class="st"></div>
<div class="snl"></div><button class="close" type="button">Sluiten</button></div></div>
<script type="application/json" id="words">{words_json}</script>
<script>{JS}</script>
</body></html>"""


def _simple(title: str, body: str) -> str:
    return f"""<!doctype html><html lang="nl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark"><title>{escape(title)}</title>{FONTS}
<style>{CSS}
ul{{list-style:none;padding:0;margin:0}} li a{{display:block;padding:14px 0;border-bottom:1px solid var(--rule);
color:var(--ink);text-decoration:none;font-size:20px}}</style></head>
<body><div class="wrap">{body}</div></body></html>"""


def render_archive(name: str, dates: list[str]) -> str:
    from datetime import date
    items = "".join(
        f'<li><a href="{d}.html">{fecha(date.fromisoformat(d))}</a></li>' for d in dates
    )
    return _simple(f"Archief · {name}", f'<header><div class="kicker">El diario de {escape(name)}</div>'
                   f'<h1>Archivo</h1></header><p class="sans"><a href="./">← Vandaag</a></p><ul>{items}</ul>')


def render_home(names: list[str]) -> str:
    from krant import slugify
    items = "".join(f'<li><a href="{slugify(n)}/">El diario de {escape(n)}</a></li>' for n in names)
    items += '<li><a href="stats/">Estadísticas</a></li>'
    return _simple("Noticias de hoy", f'<header><div class="kicker">Español con Anki</div>'
                   f"<h1>Noticias de hoy</h1></header><ul>{items}</ul>")
