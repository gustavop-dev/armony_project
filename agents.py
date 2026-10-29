"""Agentes: personalidades del coach, cada una con su system prompt completo.

Cada agente es un archivo agents/<id>.json junto a config.json:

    {"name": "Grok", "preset": "grok",
     "instrucciones": "...personalidad, tono, longitud...",
     "reglas": "...como funciona la conversacion, formato, codigo...",
     "tono": "...como hablas: registro, muletillas, ritmo...",
     "modo": "automatico", "capturas": true, "notas": true,
     "personaje": "zorro", "color": "coral",
     "conocimiento": [{"id": "doc-1", "name": "Mi CV", "body": "..."}]}

- Las dos partes se editan enteras desde Configuracion. 'reglas' es la mecanica
  de la que depende la app (secciones '##', formato de codigo, capturas); se
  puede cambiar, pero romperla estropea como se pinta la respuesta.
- 'preset' dice de que agente de ejemplo salio: "Restaurar" vuelve a su texto.
  Un agente nuevo nace como copia del Coach para que se vea lo que ya hay.
- 'tono': como quieres que suene (markdown). Se escribe a mano o se saca de
  tus chats de WhatsApp (estilo.py). Vacio en los de ejemplo.
- permisos: 'modo' (notetaker: solo escucha y toma notas; manual: responde
  solo cuando lo pides; automatico: responde en cuanto detecta una pregunta),
  'capturas' (puede usar pantallazos) y 'notas' (notas al terminar; el
  notetaker las toma siempre).
- 'personaje' y 'color': su cara (avatares.py), en la Home y en el overlay.
- 'conocimiento': documentos markdown del agente (CV, oferta, producto...),
  como los de un GPT o un proyecto. Se le dan enteros al empezar la reunion.
- El que se usa es config["agent"]. Al empezar la reunion su texto y su
  conocimiento abren la conversacion del modelo; cambiarlo a mitad la reinicia
  con el historial (ver CoachEngine.set_agent).
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

# Como responde un agente.
NOTETAKER, MANUAL, AUTOMATICO = "notetaker", "manual", "automatico"
MODOS = (NOTETAKER, MANUAL, AUTOMATICO)


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

# Cara de cada agente de ejemplo: (personaje, color) de avatares.py.
CARAS = {"coach": ("gota", "pervinca"), "directo": ("robot", "grafito"),
         "grok": ("zorro", "coral"), "senior": ("buho", "menta")}

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
    personaje, color = CARAS[pid]
    return {"id": pid, "name": nombre, "preset": pid,
            "personaje": personaje, "color": color,
            "instrucciones": instrucciones, "reglas": REGLAS, "tono": "",
            "modo": AUTOMATICO, "capturas": True, "notas": True,
            "conocimiento": []}


def nuevo(existentes, nombre="Nuevo agente"):
    """Agente nuevo: copia del Coach, para partir de lo que ya funciona."""
    import avatares
    base = preset(DEFAULT_ID)
    # Cada agente nuevo con otra cara: personaje y color van rotando.
    n = len(existentes)
    personajes = list(avatares.PERSONAJES)
    colores = [c for c, _, _ in avatares.COLORES]
    base.update(id=next_id(existentes), name=nombre,
                personaje=personajes[n % len(personajes)],
                color=colores[(n * 3 + 1) % len(colores)])
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
        docs = data.get("conocimiento")
        out.append({"id": aid,
                    "name": str(data.get("name") or aid),
                    "preset": base["preset"],
                    "instrucciones": str(data.get("instrucciones", base["instrucciones"])),
                    "reglas": str(data.get("reglas", base["reglas"])),
                    "tono": str(data.get("tono", base["tono"])),
                    "modo": data.get("modo") if data.get("modo") in MODOS else AUTOMATICO,
                    "capturas": bool(data.get("capturas", True)),
                    "notas": bool(data.get("notas", True)),
                    "personaje": str(data.get("personaje") or base["personaje"]),
                    "color": str(data.get("color") or base["color"]),
                    "conocimiento": [
                        {"id": str(d.get("id") or f"doc-{i + 1}"),
                         "name": str(d.get("name") or "Documento"),
                         "body": str(d.get("body") or "")}
                        for i, d in enumerate(docs if isinstance(docs, list) else [])
                        if isinstance(d, dict)]})
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
                 "reglas": a.get("reglas", ""),
                 "tono": a.get("tono", ""),
                 "modo": a.get("modo", AUTOMATICO),
                 "capturas": bool(a.get("capturas", True)),
                 "notas": bool(a.get("notas", True)),
                 "personaje": a.get("personaje", ""),
                 "color": a.get("color", ""),
                 "conocimiento": a.get("conocimiento", [])}
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


def modo(agente):
    m = agente.get("modo")
    return m if m in MODOS else AUTOMATICO


def usa_capturas(agente):
    """El notetaker no resuelve nada, asi que tampoco usa capturas."""
    return modo(agente) != NOTETAKER and bool(agente.get("capturas", True))


def toma_notas(agente):
    return modo(agente) == NOTETAKER or bool(agente.get("notas", True))


def texto_conocimiento(agente):
    """Los documentos del agente, juntos, en el orden en que estan."""
    return "\n\n".join(d["body"].strip() for d in agente.get("conocimiento", [])
                       if d.get("body", "").strip())


def system_prompt(agente):
    """Instrucciones del agente, su tono y su conocimiento. Las reglas van
    aparte (Coach las pone detras)."""
    texto = agente["instrucciones"].strip()
    tono = agente.get("tono", "").strip()
    if tono:
        texto += ("\n\n# Tono y estilo\nHabla como se describe aqui: es como "
                  "habla de verdad la persona a la que le soplas.\n\n" + tono)
    contexto = texto_conocimiento(agente)
    if contexto:
        texto += "\n\n# Contexto de esta reunion\n" + contexto
    return texto


def nuevo_documento(agente, nombre="Nuevo documento"):
    n = max([_num(d["id"]) for d in agente.get("conocimiento", [])], default=0) + 1
    return {"id": f"doc-{n}", "name": nombre, "body": ""}


_MARCA_MIGRACION = ".contextos-migrados"


def migrar_contextos(agent_id):
    """Una sola vez: los contextos activos de antes (globales) pasan a ser
    conocimiento del agente en uso. Los archivos de contextos no se tocan."""
    import contexts as ctx_mod
    marca = os.path.join(AGENTS_DIR, _MARCA_MIGRACION)
    if os.path.exists(marca):
        return 0
    lista = list_agents()
    agente = next((a for a in lista if a["id"] == agent_id), lista[0])
    ya = {(d["name"], d["body"]) for d in agente["conocimiento"]}
    nuevos = 0
    for c in ctx_mod.list_contexts():
        if c["active"] and c["body"].strip() and (c["name"], c["body"]) not in ya:
            doc = nuevo_documento(agente, c["name"])
            doc["body"] = c["body"]
            agente["conocimiento"].append(doc)
            nuevos += 1
    try:
        if nuevos:
            write_all(lista)
        with open(marca, "w", encoding="utf-8") as f:
            f.write("contexts/*.md activos -> conocimiento del agente en uso\n")
    except OSError as e:
        log.warning("Context migration not saved (%s)", type(e).__name__)
    return nuevos
