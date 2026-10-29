"""Historial de reuniones: la transcripcion de cada una, con su agente.

Cada reunion se guarda al terminar en sesiones/sesion-AAAAMMDD-HHMMSS.md:

    ---
    agent: grok
    agent_name: Grok
    title: ¿Qué harías si llegan dos solicitudes iguales…
    ---
    # Reunion del 29/10/2026 16:18
    **Ellos:** ...
    ### Sugerido
    ...

La Home lista las reuniones de cada agente (como el historial de un chat) y
abre su transcripcion. Las guardadas antes de los agentes no llevan cabecera:
salen sin agente y con la fecha del nombre del archivo.
"""
import datetime as dt
import logging
import os
import re

import config as cfg_mod

log = logging.getLogger("armony.sesiones")

SESIONES_DIR = os.path.join(cfg_mod.data_dir(), "sesiones")

_LARGO_TITULO = 48
_MESES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct",
          "nov", "dic")


def _titulo(registro):
    """Lo primero que preguntaron los demas, recortado: como el titulo que un
    chat pone a una conversacion."""
    for quien, texto in registro:
        texto = " ".join(str(texto).split())
        if quien == "Ellos" and texto:
            if len(texto) <= _LARGO_TITULO:
                return texto
            return texto[:_LARGO_TITULO].rsplit(" ", 1)[0] + "…"
    return "Reunión"


def guardar(registro, agente_id="", agente_nombre="", ahora=None):
    """Escribe la reunion. Devuelve la ruta, o None si no hay nada o falla."""
    if not registro:
        return None
    ahora = ahora or dt.datetime.now()
    try:
        os.makedirs(SESIONES_DIR, exist_ok=True)
        ruta = os.path.join(SESIONES_DIR, f"sesion-{ahora:%Y%m%d-%H%M%S}.md")
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(f"---\nagent: {agente_id}\nagent_name: {agente_nombre}\n"
                    f"title: {_titulo(registro)}\n---\n")
            f.write(f"# Reunion del {ahora:%d/%m/%Y %H:%M}\n\n")
            for quien, texto in registro:
                if quien.startswith("Sugerido"):
                    f.write(f"### {quien}\n\n{texto.strip()}\n\n")
                else:
                    f.write(f"**{quien}:** {texto.strip()}\n\n")
        return ruta
    except OSError:
        log.warning("Session transcript not written under %s", SESIONES_DIR,
                    exc_info=True)
        return None


def _parse(texto):
    texto = texto.replace("\r\n", "\n")      # en Windows se escriben con CRLF
    cabecera, cuerpo = {}, texto
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", texto, re.S)
    if m:
        cuerpo = m.group(2)
        for linea in m.group(1).splitlines():
            if ":" in linea:
                k, v = linea.split(":", 1)
                cabecera[k.strip().lower()] = v.strip()
    return cabecera, cuerpo


def _fecha(sid):
    m = re.search(r"(\d{8})-(\d{6})", sid)
    if not m:
        return None
    try:
        return dt.datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
    except ValueError:
        return None


def listar():
    """Todas las reuniones, la mas reciente primero:
    [{id, agent, agent_name, title, started}]."""
    if not os.path.isdir(SESIONES_DIR):
        return []
    out = []
    for fn in os.listdir(SESIONES_DIR):
        if not fn.lower().endswith(".md") or fn.lower().endswith(_NOTAS):
            continue
        sid = os.path.splitext(fn)[0]
        try:
            cabecera, _ = _parse(cfg_mod.read_user_text(os.path.join(SESIONES_DIR, fn)))
        except OSError as e:
            log.warning("Session not readable (%s); skipped: %s", type(e).__name__, fn)
            continue
        out.append({"id": sid, "agent": cabecera.get("agent", ""),
                    "agent_name": cabecera.get("agent_name", ""),
                    "title": cabecera.get("title") or "Reunión",
                    "started": _fecha(sid)})
    out.sort(key=lambda s: s["started"] or dt.datetime.min, reverse=True)
    return out


def leer(sid):
    """La transcripcion (markdown, sin cabecera)."""
    _, cuerpo = _parse(cfg_mod.read_user_text(os.path.join(SESIONES_DIR, sid + ".md")))
    return cuerpo.strip()


def borrar(sid):
    try:
        os.remove(os.path.join(SESIONES_DIR, sid + ".md"))
        notas = os.path.join(SESIONES_DIR, sid + _NOTAS)
        if os.path.exists(notas):
            os.remove(notas)
        return True
    except OSError as e:
        log.warning("Session not deleted (%s): %s", type(e).__name__, sid)
        return False


# Las notas de una reunion van al lado de su transcripcion.
_NOTAS = ".notas.md"


def id_de(ruta):
    """Id de la reunion a partir de la ruta que devuelve guardar()."""
    return os.path.splitext(os.path.basename(ruta))[0]


def guardar_notas(sid, texto):
    try:
        with open(os.path.join(SESIONES_DIR, sid + _NOTAS), "w", encoding="utf-8") as f:
            f.write(texto.strip() + "\n")
        return True
    except OSError:
        log.warning("Meeting notes not written: %s", sid, exc_info=True)
        return False


def leer_notas(sid):
    """Las notas de la reunion, o "" si no tiene."""
    ruta = os.path.join(SESIONES_DIR, sid + _NOTAS)
    if not os.path.exists(ruta):
        return ""
    return cfg_mod.read_user_text(ruta).replace("\r\n", "\n").strip()


def etiqueta_fecha(cuando, hoy=None):
    """'Hoy 16:18', 'Ayer 11:02' o '27 oct 09:30'."""
    if cuando is None:
        return ""
    hoy = (hoy or dt.datetime.now()).date()
    hora = f"{cuando:%H:%M}"
    if cuando.date() == hoy:
        return f"Hoy {hora}"
    if cuando.date() == hoy - dt.timedelta(days=1):
        return f"Ayer {hora}"
    return f"{cuando.day} {_MESES[cuando.month - 1]} {hora}"
