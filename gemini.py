"""Small Gemini REST client with structured (JSON) output."""

from __future__ import annotations

import json
import os
import re
import time

import requests

API = "https://generativelanguage.googleapis.com/v1beta"


class GeminiError(RuntimeError):
    pass


def _keys() -> list[tuple[str, str]]:
    """(label, key) pairs: the free key first, the paid backup key second."""
    keys = [("gratis", os.environ.get("GEMINI_API_KEY", "").strip()),
            ("betaald", os.environ.get("GEMINI_API_KEY_BACKUP_PAID", "").strip())]
    keys = [(label, k) for label, k in keys if k]
    if not keys:
        raise GeminiError("GEMINI_API_KEY ontbreekt in de GitHub secrets.")
    return keys


def _key() -> str:
    return _keys()[0][1]


_MODELS: list[str] | None = None
USAGE: list[dict] = []
# Paid-tier list prices per 1M tokens (input, output incl. thinking), for the cost estimate only.
PRICES = {"lite": (0.30, 2.50), "flash": (0.75, 3.75)}


def _models() -> list[str]:
    global _MODELS
    if _MODELS is None:
        r = None
        for _label, key in _keys():
            r = requests.get(f"{API}/models", headers={"x-goog-api-key": key},
                             params={"pageSize": 200}, timeout=30)
            if r.status_code == 200:
                break
        if r is None or r.status_code != 200:
            raise GeminiError(f"modellen opvragen mislukt ({r.status_code}): {r.text[:200]}")
        _MODELS = [
            m["name"].removeprefix("models/") for m in r.json().get("models", [])
            if "generateContent" in m.get("supportedGenerationMethods", [])
        ]
    return _MODELS


def _version(n: str) -> tuple:
    m = re.search(r"gemini-(\d+)(?:\.(\d+))?", n)
    stable = "preview" not in n
    return (int(m.group(1)), int(m.group(2) or 0), stable) if m else (0, 0, stable)


def pick_model(lite: bool = False) -> str:
    """Writing: GEMINI_MODEL or the newest 'flash'. Selection (lite=True): the newest
    'flash-lite' (GEMINI_LITE_MODEL overrides), falling back to the writing model."""
    wanted = os.environ.get("GEMINI_LITE_MODEL" if lite else "GEMINI_MODEL", "").strip()
    if wanted:
        return wanted.removeprefix("models/")
    names = _models()
    bad = r"image|tts|audio|live|exp|embedding|thinking|robotics|computer"
    if lite:
        cands = [n for n in names if "flash-lite" in n and not re.search(bad, n)]
        if "gemini-flash-lite-latest" in cands:
            return "gemini-flash-lite-latest"
        return max(cands, key=_version) if cands else pick_model()
    flash = [n for n in names if "flash" in n and "lite" not in n and not re.search(bad, n)]
    if "gemini-flash-latest" in flash:
        return "gemini-flash-latest"
    if not flash:
        raise GeminiError(f"geen geschikt Gemini-model gevonden in: {names[:20]}")
    return max(flash, key=_version)


def generate_json(model: str, system: str, prompt: str, schema: dict,
                  temperature: float = 0.6, thinking: str | None = None,
                  label: str = "") -> dict:
    config = {
        "temperature": temperature,
        "responseMimeType": "application/json",
        "responseSchema": schema,
        "maxOutputTokens": 32768,
    }
    if thinking:
        config["thinkingConfig"] = {"thinkingLevel": thinking}
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": config,
    }
    last = ""
    for key_label, key in _keys():
        for attempt in range(3):
            try:
                r = requests.post(f"{API}/models/{model}:generateContent",
                                  headers={"x-goog-api-key": key}, json=body, timeout=240)
            except requests.RequestException as exc:
                last = f"verbinding mislukt: {exc}"
                time.sleep(10 * (attempt + 1))
                continue
            if r.status_code == 400 and "thinking" in r.text.lower() and "thinkingConfig" in config:
                config.pop("thinkingConfig")  # model does not support this setting: use default
                continue
            if r.status_code in (429, 500, 502, 503, 504):
                last = f"{key_label} sleutel {r.status_code}: {r.text[:200]}"
                print(f"  Gemini ({label}, {key_label} sleutel) niet beschikbaar: {r.status_code}",
                      flush=True)
                time.sleep(10 * (attempt + 1))
                continue
            if r.status_code in (401, 402, 403):  # key refused / no credit: try the next key
                last = f"{key_label} sleutel {r.status_code}: {r.text[:200]}"
                print(f"  Gemini ({label}): {key_label} sleutel geweigerd ({r.status_code})", flush=True)
                break
            if r.status_code != 200:
                raise GeminiError(f"Gemini-fout {r.status_code}: {r.text[:300]}")
            data = r.json()
            u = data.get("usageMetadata", {})
            USAGE.append({"label": label, "model": model, "key": key_label,
                          "in": u.get("promptTokenCount", 0),
                          "out": u.get("candidatesTokenCount", 0) + u.get("thoughtsTokenCount", 0),
                          "thoughts": u.get("thoughtsTokenCount", 0)})
            try:
                cand = data["candidates"][0]
                text = "".join(p.get("text", "") for p in cand["content"]["parts"])
                return json.loads(text)
            except (KeyError, IndexError, json.JSONDecodeError) as exc:
                reason = data.get("candidates", [{}])[0].get("finishReason", "?")
                last = f"onleesbaar antwoord ({exc}, finishReason={reason}): {str(data)[:200]}"
                time.sleep(5)
    raise GeminiError(f"Gemini gaf met geen enkele sleutel een bruikbaar antwoord. Laatste: {last}")


def print_usage() -> None:
    paid = 0.0
    print("\nGemini-gebruik deze run:")
    for u in USAGE:
        pin, pout = PRICES["lite" if "lite" in u["model"] else "flash"]
        cost = (u["in"] * pin + u["out"] * pout) / 1e6
        if u["key"] == "betaald":
            paid += cost
        print(f"  {u['label']:<10} {u['model']:<26} {u['key']:<8} in {u['in']:>7,}  uit {u['out']:>6,} "
              f"(denken {u['thoughts']:,})  ≈ ${cost:.3f}" + ("" if u["key"] == "betaald" else " (gratis)"))
    print(f"  Betaald deze run ≈ ${paid:.3f}")
    if paid:
        print(f"::notice::Gemini viel terug op de betaalde sleutel (≈ ${paid:.3f}).")


# ------------------------------------------------------------------ prompts --

SELECT_SYSTEM = """Eres el editor de un pequeño periódico diario en español para dos \
estudiantes de español (nivel B2) que viven en Madrid. Quieren seguir lo que pasa de verdad \
en España, pero se desaniman con el sesgo negativo de las noticias. Tu trabajo es ELEGIR, no escribir.

Cada noticia trae su fuente y su posición en la portada de esa fuente (#1 = la que abre). \
Una noticia que abre varias portadas, o cuyo tema aparece en varias fuentes, es importante hoy.

La edición tiene tres formatos:
- "principal": LA noticia del día, la que más pesa en las portadas. Puede ser política, \
economía, Europa o cualquier tema, siempre que sea de verdad lo que hoy importa en España. \
Se explica con contexto.
- "normal": noticias de peso medio.
- "breve": noticias pequeñas que se cuentan en un solo párrafo.

Devuelve 16 noticias ordenadas por preferencia (la mejor primero). Algunas páginas no se pueden \
leer; entonces se usan las siguientes, así que marca 2 como "principal" (la mejor primero), unas \
6 como "normal" y unas 8 como "breve". La edición final tiene 1 principal, 3 normales y 3 breves.

Criterios de mezcla para la edición:
- La principal y 1 o 2 normales o breves siguen la actualidad del día, también la política \
(gobierno, Congreso, partidos, elecciones, Unión Europea), si es lo que domina las portadas.
- El resto: tendencias de largo plazo y cambios estructurales (sociedad, ciencia, clima y \
soluciones, economía cotidiana, salud, cultura, ciudades, tecnología) y al menos 2 noticias \
claramente positivas o esperanzadoras.
- Evita sucesos, crímenes, accidentes, violencia gráfica, cotilleo, resultados deportivos, \
directos ("en directo", "última hora" con muchos temas) y columnas de opinión. La política \
sí, pero con contenido: decisiones, leyes, negociaciones, resultados; no meros insultos entre partidos.
- Variedad: como máximo una noticia sobre el mismo asunto. Prefiere noticias sobre España.
- Elige solo noticias cuya entradilla tenga suficiente información."""

SELECT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "seleccion": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "id": {"type": "INTEGER"},
                    "formato": {"type": "STRING", "enum": ["principal", "normal", "breve"]},
                    "rubrica": {"type": "STRING", "description":
                                "Etiqueta corta en español: España, Política, Sociedad, Ciencia, "
                                "Clima, Cultura, Economía, Salud, Tecnología, Europa, Mundo o "
                                "Buenas noticias"},
                    "tono": {"type": "STRING", "enum": ["tendencia", "positivo", "actualidad"]},
                    "tema": {"type": "STRING", "description":
                             "El asunto en una o dos palabras en minúscula, p. ej. 'vivienda', "
                             "'clima', 'inteligencia artificial'. Noticias del mismo asunto llevan "
                             "exactamente el mismo tema."},
                },
                "required": ["id", "formato", "rubrica", "tono", "tema"],
            },
        }
    },
    "required": ["seleccion"],
}

WRITE_SYSTEM = """Escribes un pequeño periódico diario en español de nivel B2 para un \
estudiante neerlandés que vive en Madrid. El periódico tiene dos objetivos: que entienda las \
noticias reales del día y que repase SU vocabulario de Anki leyéndolas. Reglas:

1. NO INVENTES NADA. Usa solo los hechos del titular, la entradilla y el "Texto del artículo". \
No añadas cifras, nombres, fechas, causas ni consecuencias que no estén ahí. No copies frases \
del original; como mucho una cita de pocas palabras.

2. LA LONGITUD DEPENDE DEL FORMATO, y dentro del margen, de lo importante y complejo que sea el tema:
   - "principal": la noticia del día, de 5 a 7 párrafos. Lo esencial primero; después el \
contexto, las causas, qué significa para la gente en España y qué viene ahora. En política, \
explica con neutralidad qué hace o propone cada parte y qué critican los demás, sin opinar.
   - "normal": de 2 a 4 párrafos. Más si el tema es complejo o importante, menos si es sencillo.
   - "breve": UN solo párrafo de 2 a 4 frases.
   Párrafos de 2 a 4 frases, separados por una línea en blanco en "texto". No rellenes: si el \
artículo da poco, escribe menos.

3. VOCABULARIO DEL ESTUDIANTE. Es lo más importante después de los hechos.
   - Antes de escribir cada noticia, busca en las listas todas las palabras que encajan con su \
tema y construye las frases a su alrededor. Las listas son la materia prima del texto.
   - Objetivo para el periódico entero: usar al menos tres cuartas partes de las palabras de \
REPASAR y de NUEVAS, repartidas entre las noticias.
   - Las palabras de REPASAR (falladas) deben salir varias veces: si encajan, en dos o más \
noticias distintas.
   - Las de REPASADAS (repasadas en los últimos meses) úsalas libremente siempre que encajen; \
cuantas más, mejor.
   - Orientación: una principal lleva unas 20 a 30 palabras de las listas, una normal de 8 a \
15, una breve de 3 a 6.
   - Puedes conjugar, poner en plural o en femenino, y usar la palabra en una explicación, una \
comparación o una frase de contexto relacionada con la noticia. Lo que NO puedes es cambiar los \
hechos ni escribir frases raras o forzadas: si una palabra no encaja en ninguna noticia, déjala.

4. Nivel B2: frases naturales y variadas, vocabulario rico pero claro, sin jerga innecesaria.
5. Tono tranquilo y constructivo. En noticias duras y en política, neutral y sin sensacionalismo.
6. Titular corto y propio (no copies el original).

En "palabras" de cada noticia incluye:
- CADA palabra de las listas que hayas usado en esa noticia (también si ya la usaste en otra \
noticia), con el "lema" EXACTAMENTE como aparece en la lista;
- además, como mucho 3 palabras difíciles que NO están en las listas y que un estudiante B2 \
probablemente no conoce.
Para cada una: "forma" = exactamente como aparece en "texto" (o en "titulo"); "lema" = forma \
de diccionario (verbos en infinitivo, sustantivos en singular); "nl" = significado en \
neerlandés en este contexto (corto); "tipo" = categoría en neerlandés (werkwoord, \
zelfst. nw. (mnl.), zelfst. nw. (vr.), bijv. nw., bijwoord, voorzetsel, voegwoord, uitdrukking).

En "repaso" da para CADA palabra de la lista REPASAR su lema, su significado en neerlandés y \
su tipo, aunque no la hayas usado."""

WORD = {
    "type": "OBJECT",
    "properties": {
        "forma": {"type": "STRING"},
        "lema": {"type": "STRING"},
        "nl": {"type": "STRING"},
        "tipo": {"type": "STRING"},
    },
    "required": ["forma", "lema", "nl", "tipo"],
}

WRITE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "articulos": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "id": {"type": "INTEGER"},
                    "rubrica": {"type": "STRING"},
                    "titulo": {"type": "STRING"},
                    "texto": {"type": "STRING"},
                    "palabras": {"type": "ARRAY", "items": WORD},
                },
                "required": ["id", "rubrica", "titulo", "texto", "palabras"],
            },
        },
        "repaso": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "lema": {"type": "STRING"},
                    "nl": {"type": "STRING"},
                    "tipo": {"type": "STRING"},
                },
                "required": ["lema", "nl", "tipo"],
            },
        },
    },
    "required": ["articulos", "repaso"],
}
