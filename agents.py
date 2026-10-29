"""Agentes: personalidades del coach, cada una con su system prompt completo.

Cada agente es un archivo agents/<id>.json junto a config.json:

    {"name": "Grok", "preset": "grok",
     "instrucciones": "...personalidad, tono, longitud...",
     "reglas": "...como funciona la conversacion, formato, codigo..."}

- Las dos partes se editan enteras desde Configuracion. 'reglas' es la mecanica
  de la que depende la app (secciones '##', formato de codigo, capturas); se
  puede cambiar, pero romperla estropea como se pinta la respuesta.
- 'preset' dice de que agente de ejemplo salio: "Restaurar" vuelve a su texto.
  Un agente nuevo nace como copia del Coach para que se vea lo que ya hay.
- El que se usa es config["agent"]. Al empezar la reunion su texto (mas los
  contextos activos) abre la conversacion del modelo; cambiarlo a mitad la
  reinicia con el historial (ver CoachEngine.set_agent).
- Los avisos de cada turno ("responde a esto", "puedes callarte") no son del
  agente: los pone llm.py en cada mensaje.
"""
import json
import logging
import os
import re

import config as cfg_mod
from llm import REGLAS

log = logging.getLogger("armony.agents")

AGENTS_DIR = os.path.join(cfg_mod.data_dir(), "agents")

DEFAULT_ID = "coach"


def prompt_bilingue(es, en):
    """Las mismas instrucciones en los dos idiomas, juntas a proposito: el
    modelo tiene sus reglas en el idioma que toque cuando la reunion cambia de
    uno a otro, sin reiniciar nada."""
    es, en = (es or "").strip(), (en or "").strip()
    if es and en:
        return (f"{es}\n\n---\n\n(The same instructions in English; follow "
                f"whichever matches the language being spoken.)\n\n{en}")
    return es or en


_DIRECTO = (
    "Eres mi apuntador en reuniones. Lo que escribas lo voy a decir en voz alta "
    "tal cual, en primera persona.\n"
    "- Seco y al grano: una o dos frases por idea, sin introducciones, sin "
    "«buena pregunta», sin resumir lo que me preguntaron.\n"
    "- Primero la respuesta; luego, si hace falta, el porqué en una frase.\n"
    "- Nada de relleno ni de matices que nadie pidió.\n"
    "- Si no hay datos para afirmar algo, dilo en una frase y propón cómo "
    "averiguarlo.")

_GROK = (
    "Eres mi copiloto en reuniones con la personalidad de Grok: ingenioso, "
    "irreverente, directo y con un punto rebelde. Lo que escribas lo voy a decir "
    "en voz alta, en primera persona.\n"
    "- Dices las cosas sin rodeos y sin lenguaje corporativo: si una idea es "
    "mala, se nota; si es buena, también.\n"
    "- Una chispa de humor por respuesta como mucho: un comentario agudo, una "
    "comparación inesperada o una ironía ligera. El humor es el tono, no el "
    "contenido: la respuesta tiene que aportar de verdad.\n"
    "- Nunca ofensivo ni a costa de nadie de la reunión: es una conversación "
    "profesional y lo que digo me representa.\n"
    "- Confianza sin arrogancia: opiniones claras, y si no lo sabes, lo dices "
    "con gracia en vez de inventar.\n"
    "- Breve: de una a cuatro frases que suenen a persona, no a manual.")

_SENIOR = (
    "Eres mi coach para reuniones técnicas y entrevistas de ingeniería. Lo que "
    "escribas lo voy a decir en voz alta, en primera persona, como un ingeniero "
    "senior con oficio.\n"
    "- Responde con decisiones y sus compromisos: qué elegiría, qué descarto y "
    "por qué, y en qué caso cambiaría de opinión.\n"
    "- Concreto: cifras orientativas, límites, cómo lo mediría y cómo lo "
    "pondría en producción. Mejor un ejemplo real que una definición.\n"
    "- Usa el término técnico correcto cuando es el que se usa en el oficio, "
    "con una aclaración de paso si no es común.\n"
    "- Tono tranquilo y seguro, de quien ya lo ha hecho; sin listas recitadas.\n"
    "- Si falta contexto, di qué supones y sigue.")

# id -> (nombre, instrucciones). Las reglas de todos son las de llm.REGLAS.
PRESETS = {
    "coach": ("Coach", prompt_bilingue(cfg_mod.DEFAULT_PROMPT_ES,
                                       cfg_mod.DEFAULT_PROMPT_EN)),
    "directo": ("Directo", _DIRECTO),
    "grok": ("Grok", _GROK),
    "senior": ("Senior técnico", _SENIOR),
}


def preset(preset_id):
    """El agente de ejemplo tal cual viene (desconocido -> Coach)."""
    pid = preset_id if preset_id in PRESETS else DEFAULT_ID
    nombre, instrucciones = PRESETS[pid]
    return {"id": pid, "name": nombre, "preset": pid,
            "instrucciones": instrucciones, "reglas": REGLAS}


def nuevo(existentes, nombre="Nuevo agente"):
    """Agente nuevo: copia del Coach, para partir de lo que ya funciona."""
    base = preset(DEFAULT_ID)
    base.update(id=next_id(existentes), name=nombre)
    return base


def predeterminado(agente):
    """Texto al que vuelve "Restaurar": el de su agente de ejemplo."""
    return preset(agente.get("preset"))


def _ensure_dir():
    os.makedirs(AGENTS_DIR, exist_ok=True)


def _num(aid):
    m = re.search(r"(\d+)$", aid)
    return int(m.group(1)) if m else 0


def next_id(existentes):
    n = max([_num(a["id"]) for a in existentes
             if a["id"].startswith("agente-")], default=0) + 1
    return f"agente-{n}"


def _orden(agente):
    # Primero los de ejemplo en su orden, luego los creados por orden de alta.
    ids = list(PRESETS)
    if agente["id"] in ids:
        return (0, ids.index(agente["id"]))
    return (1, _num(agente["id"]))


def list_agents():
    """Todos los agentes. La primera vez (o si no queda ninguno) se crean los de
    ejemplo, para que siempre haya al menos uno."""
    _ensure_dir()
    out = []
    for fn in os.listdir(AGENTS_DIR):
        if not fn.lower().endswith(".json"):
            continue
        aid = os.path.splitext(fn)[0]
        try:
            data = json.loads(cfg_mod.read_user_text(os.path.join(AGENTS_DIR, fn)))
        except (OSError, ValueError) as e:
            log.warning("Agent file not readable (%s); skipped: %s",
                        type(e).__name__, fn)
            continue
        if not isinstance(data, dict):
            continue
        base = predeterminado(data)
        out.append({"id": aid,
                    "name": str(data.get("name") or aid),
                    "preset": base["preset"],
                    "instrucciones": str(data.get("instrucciones", base["instrucciones"])),
                    "reglas": str(data.get("reglas", base["reglas"]))})
    if not out:
        out = [preset(pid) for pid in PRESETS]
        try:
            write_all(out)
        except OSError as e:
            # Sin disco se siguen usando en memoria; se reintenta al guardar.
            log.warning("Preset agents not written (%s): %s",
                        type(e).__name__, AGENTS_DIR)
    out.sort(key=_orden)
    return out


def write_all(agentes):
    """Escribe la lista completa y borra los archivos que ya no estan."""
    _ensure_dir()
    vivos = set()
    for a in agentes:
        vivos.add(os.path.normcase(a["id"] + ".json"))
        datos = {"name": a.get("name", a["id"]), "preset": a.get("preset", DEFAULT_ID),
                 "instrucciones": a.get("instrucciones", ""),
                 "reglas": a.get("reglas", "")}
        with open(os.path.join(AGENTS_DIR, a["id"] + ".json"), "w",
                  encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=2)
    for fn in os.listdir(AGENTS_DIR):
        if fn.lower().endswith(".json") and os.path.normcase(fn) not in vivos:
            try:
                os.remove(os.path.join(AGENTS_DIR, fn))
            except OSError as e:
                log.warning("Deleted agent file not removed (%s): %s",
                            type(e).__name__, fn)


def get(agent_id):
    """El agente con ese id; si ya no existe, el primero (el Coach si esta)."""
    agentes = list_agents()
    return next((a for a in agentes if a["id"] == agent_id), agentes[0])


def system_prompt(agente, contexto=""):
    """Instrucciones del agente mas los contextos activos de la reunion. Las
    reglas van aparte (Coach las pone detras)."""
    texto = agente["instrucciones"].strip()
    if contexto:
        texto += "\n\n# Contexto de esta reunion\n" + contexto
    return texto
