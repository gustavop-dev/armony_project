"""Sistema de contexto: documentos markdown que la IA lee al iniciar la reunion.

Cada contexto es un archivo contexts/<id>.md con cabecera (frontmatter):

    ---
    name: Producto X
    active: true
    ---
    # Producto X
    ...contenido markdown...

- Se pueden crear varios; los marcados como active se concatenan y se inyectan
  en el system prompt de Claude al iniciar la reunion.
- El contenido se congela al iniciar (para no romper el cache a media llamada).
"""
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
CONTEXTS_DIR = os.path.join(_HERE, "contexts")


def _ensure_dir():
    os.makedirs(CONTEXTS_DIR, exist_ok=True)


def _parse(text):
    """Devuelve (name, active, lang, body) a partir del contenido de un .md."""
    name, active, lang, body = "", False, "both", text
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if m:
        head, body = m.group(1), m.group(2)
        for linea in head.splitlines():
            if ":" not in linea:
                continue
            k, v = linea.split(":", 1)
            k, v = k.strip().lower(), v.strip()
            if k == "name":
                name = v
            elif k == "active":
                active = v.lower() in ("true", "1", "yes", "si", "sí")
            elif k == "lang":
                lang = v.lower() if v.lower() in ("es", "en", "both") else "both"
    return name, active, lang, body.strip()


def _serialize(name, active, lang, body):
    return (f"---\nname: {name}\nactive: {'true' if active else 'false'}\n"
            f"lang: {lang}\n---\n{body.strip()}\n")


def list_contexts():
    """Lista todos los contextos: [{id, name, active, body}] ordenados por id."""
    _ensure_dir()
    out = []
    for fn in os.listdir(CONTEXTS_DIR):
        if not fn.lower().endswith(".md"):
            continue
        cid = os.path.splitext(fn)[0]
        try:
            with open(os.path.join(CONTEXTS_DIR, fn), "r", encoding="utf-8") as f:
                name, active, lang, body = _parse(f.read())
        except OSError:
            continue
        out.append({"id": cid, "name": name or cid, "active": active,
                    "lang": lang, "body": body})
    out.sort(key=lambda c: _num(c["id"]))
    return out


def _num(cid):
    m = re.search(r"(\d+)", cid)
    return int(m.group(1)) if m else 0


def next_id(existing):
    """Devuelve un id nuevo que no colisiona con los existentes."""
    n = max([_num(c["id"]) for c in existing], default=0) + 1
    return f"ctx-{n}"


def write_all(contexts):
    """Escribe la lista completa y borra los archivos que ya no estan."""
    _ensure_dir()
    vivos = set()
    for c in contexts:
        cid = c["id"]
        vivos.add(cid + ".md")
        with open(os.path.join(CONTEXTS_DIR, cid + ".md"), "w", encoding="utf-8") as f:
            f.write(_serialize(c.get("name", cid), c.get("active", False),
                               c.get("lang", "both"), c.get("body", "")))
    # borrar los que se eliminaron
    for fn in os.listdir(CONTEXTS_DIR):
        if fn.lower().endswith(".md") and fn not in vivos:
            try:
                os.remove(os.path.join(CONTEXTS_DIR, fn))
            except OSError:
                pass


def _matches_lang(ctx_lang, meeting_lang):
    """Un contexto aplica si es 'both', o coincide con el idioma de la reunion.

    Con idioma de reunion 'auto', aplican todos.
    """
    if meeting_lang not in ("es", "en"):
        return True
    return ctx_lang == "both" or ctx_lang == meeting_lang


def active_text(meeting_lang="auto"):
    """Concatena los contextos activos que aplican al idioma de la reunion."""
    partes = [c["body"].strip() for c in list_contexts()
              if c["active"] and c["body"].strip()
              and _matches_lang(c.get("lang", "both"), meeting_lang)]
    return "\n\n".join(partes)


def active_count(meeting_lang="auto"):
    return sum(1 for c in list_contexts()
               if c["active"] and _matches_lang(c.get("lang", "both"), meeting_lang))


def estimate_tokens(text):
    """Estimacion barata de tokens (~4 caracteres por token)."""
    return max(0, round(len(text or "") / 4))
