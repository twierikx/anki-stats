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


def _key() -> str:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise GeminiError("GEMINI_API_KEY ontbreekt in de GitHub secrets.")
    return key


def pick_model() -> str:
    """Use GEMINI_MODEL if set, otherwise the newest general 'flash' model available."""
    wanted = os.environ.get("GEMINI_MODEL", "").strip()
    if wanted:
        return wanted.removeprefix("models/")
    r = requests.get(f"{API}/models", headers={"x-goog-api-key": _key()},
                     params={"pageSize": 200}, timeout=30)
    if r.status_code != 200:
        raise GeminiError(f"modellen opvragen mislukt ({r.status_code}): {r.text[:200]}")
    names = [
        m["name"].removeprefix("models/") for m in r.json().get("models", [])
        if "generateContent" in m.get("supportedGenerationMethods", [])
    ]
    flash = [n for n in names if "flash" in n and not re.search(
        r"lite|image|tts|audio|live|exp|embedding|thinking|robotics|computer", n)]
    if "gemini-flash-latest" in flash:
        return "gemini-flash-latest"

    def version(n: str) -> tuple:
        m = re.search(r"gemini-(\d+)(?:\.(\d+))?", n)
        stable = "preview" not in n
        return (int(m.group(1)), int(m.group(2) or 0), stable) if m else (0, 0, stable)

    if not flash:
        raise GeminiError(f"geen geschikt Gemini-model gevonden in: {names[:20]}")
    return max(flash, key=version)


def generate_json(model: str, system: str, prompt: str, schema: dict,
                  temperature: float = 0.6) -> dict:
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "responseMimeType": "application/json",
            "responseSchema": schema,
            "maxOutputTokens": 16384,
        },
    }
    last = ""
    for attempt in range(5):
        r = requests.post(f"{API}/models/{model}:generateContent",
                          headers={"x-goog-api-key": _key()}, json=body, timeout=180)
        if r.status_code in (429, 500, 502, 503, 504):
            last = f"{r.status_code}: {r.text[:200]}"
            time.sleep(10 * (attempt + 1))
            continue
        if r.status_code != 200:
            raise GeminiError(f"Gemini-fout {r.status_code}: {r.text[:300]}")
        data = r.json()
        try:
            text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
            return json.loads(text)
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            last = f"onleesbaar antwoord ({exc}): {str(data)[:300]}"
            time.sleep(5)
    raise GeminiError(f"Gemini gaf na 5 pogingen geen bruikbaar antwoord. Laatste: {last}")


# ------------------------------------------------------------------ prompts --

SELECT_SYSTEM = """Eres el editor de un pequeño periódico diario en español para un estudiante \
de español (nivel B1) que vive en Madrid. El lector se desanima con el sesgo negativo de las \
noticias. Tu trabajo es ELEGIR, no escribir.

Devuelve 8 noticias ordenadas por preferencia (la mejor primero). Algunas páginas no se pueden leer; entonces se usan las siguientes de tu lista, así que cualquier grupo de 5 consecutivas debería cumplir los criterios de mezcla.

Criterios:
- Prioriza piezas que muestren tendencias de largo plazo o cambios estructurales (sociedad, \
ciencia, clima y soluciones, economía cotidiana, salud pública, cultura, ciudades, tecnología).
- Incluye al menos 2 noticias claramente positivas o esperanzadoras (un avance, una solución \
que funciona, un descubrimiento, un logro colectivo, algo bonito de la cultura).
- Como máximo 2 noticias de actualidad dura (última hora, política), y solo si son realmente \
importantes para la vida en España.
- Evita sucesos, crímenes, accidentes, violencia gráfica, cotilleo, resultados deportivos, \
directos ("en directo", "última hora" con muchos temas), columnas de opinión y peleas \
partidistas sin contenido.
- Busca variedad de temas y de fuentes. Prefiere noticias sobre España.
- Elige solo noticias cuya entradilla tenga suficiente información para resumirlas."""

SELECT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "seleccion": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "id": {"type": "INTEGER"},
                    "rubrica": {"type": "STRING", "description":
                                "Etiqueta corta en español: España, Sociedad, Ciencia, Clima, "
                                "Cultura, Economía, Salud, Tecnología, Mundo o Buenas noticias"},
                    "tono": {"type": "STRING", "enum": ["tendencia", "positivo", "actualidad"]},
                },
                "required": ["id", "rubrica", "tono"],
            },
        }
    },
    "required": ["seleccion"],
}

WRITE_SYSTEM = """Escribes un pequeño periódico diario en español fácil (nivel B1) para un \
estudiante neerlandés. Reglas estrictas:
1. NO INVENTES NADA. Usa solo los hechos del titular y la entradilla que recibes. No añadas \
cifras, nombres, fechas, causas ni consecuencias que no estén en el texto original.
2. Escribe con tus propias palabras cada noticia en 3 a 5 párrafos de 2 a 4 frases. Separa los \
párrafos con una línea en blanco en "texto". Basa todo en el "Texto del artículo": primero lo \
esencial, después el contexto, las causas o la tendencia de fondo que explica el artículo, y si \
el artículo lo menciona, lo que viene después o lo que da esperanza. No copies frases del \
original; como mucho una cita de pocas palabras.
3. Usa vocabulario y gramática de nivel B1: frases claras, sin jerga.
4. Usa con naturalidad TANTAS palabras de las listas del estudiante como puedas. Prioridad: \
primero REPASAR (respuestas falladas), después NUEVAS, y por último REPASADAS (solo si encajan \
bien). Puedes conjugarlas o ponerlas en plural. No fuerces palabras que no encajen con el hecho.
5. Tono tranquilo y constructivo. En noticias duras, neutral y sin sensacionalismo.
6. Titular corto y propio (no copies el original).

En "palabras" de cada noticia incluye:
- cada palabra de las listas que hayas usado, y
- 5 a 10 palabras más que un estudiante B1 probablemente no conoce.
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
