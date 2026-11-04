"""Precargar el agente antes de la reunion.

Lo que el agente sabe (instrucciones, tono, documentos, la memoria de sus
repositorios) abre la conversacion del modelo. La primera vez que el proveedor
lo procesa tarda en proporcion a su tamano; despues queda en cache (30 min) y
cada respuesta solo paga lo nuevo. Antes se calentaba al empezar la reunion,
con una clave de cache nueva cada vez: con mucho conocimiento, la primera
pregunta podia llegar antes de que terminara.

Ahora:
- La clave de cache es la del agente (no la de la reunion): lo calentado en
  una reunion o en la Home sirve para la siguiente mientras siga en cache.
- La Home lo calienta en segundo plano al abrir el agente (precalentar), asi
  que al pulsar Iniciar reunion ya esta listo. Sin repetir: una vez por agente
  y contenido cada VIGENCIA_S.
- Los coaches se crean igual aqui y en la reunion (crear_coaches): si el
  principio de la conversacion no fuera identico byte a byte, la cache no
  serviria.
"""
import hashlib
import logging
import threading
import time

import agents as agents_mod

log = logging.getLogger("armony.precarga")

# La cache dura 30 min; se recalienta antes de que caduque.
VIGENCIA_S = 20 * 60

_lock = threading.Lock()
_recientes = {}          # (agente, firma) -> instante del ultimo calentamiento


def cache_key(agente):
    return f"armony-{agente['id']}"


def crear_coaches(cfg, agente, herramientas=None):
    """(hablado, pantalla): las dos conversaciones de la reunion.

    Un modelo y dos conversaciones: la hablada razona poco y la de la pantalla
    mas. Empiezan igual (prompt + conocimiento), y la de la pantalla, que
    tambien responde la caja de preguntas, puede leer el codigo de los repos.
    """
    import llm
    comun = dict(api_key=cfg["openai_api_key"],
                 system_prompt=agents_mod.system_prompt(agente),
                 model=cfg["openai_model"], cache_key=cache_key(agente),
                 reglas=agente["reglas"])
    voz = llm.Coach(tokens_voice=int(cfg["openai_tokens_voice"]),
                    tokens_vision=int(cfg["openai_tokens_vision"]),
                    effort_voice=cfg.get("openai_effort_voice", "low"),
                    effort_vision=cfg.get("openai_effort_vision", "medium"),
                    **comun)
    esfuerzo = cfg.get("openai_effort_vision", "medium")
    extra = {"herramientas": herramientas} if herramientas else {}
    pantalla = llm.Coach(tokens_voice=int(cfg["openai_tokens_vision"]),
                         tokens_vision=int(cfg["openai_tokens_vision"]),
                         effort_voice=esfuerzo, effort_vision=esfuerzo,
                         **comun, **extra)
    return voz, pantalla


def _firma(cfg, agente, herramientas):
    texto = "\n".join([cfg.get("openai_model", ""), agents_mod.system_prompt(agente),
                       agente["reglas"], ",".join(herramientas.nombres) if herramientas else ""])
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def precalentar(cfg, agente, esperar=False, reloj=time.monotonic):
    """Calienta en segundo plano el principio de las dos conversaciones del
    agente. Devuelve True si lo lanzo (False: sin clave, modo prueba o ya
    estaba caliente)."""
    if not cfg.get("openai_api_key") or cfg.get("test_mode"):
        return False
    import repos
    herramientas = repos.herramientas(agente)
    clave = (agente["id"], _firma(cfg, agente, herramientas))
    ahora = reloj()
    with _lock:
        if ahora - _recientes.get(clave, float("-inf")) < VIGENCIA_S:
            return False
        _recientes[clave] = ahora

    def calentar():
        try:
            for coach in crear_coaches(cfg, agente, herramientas):
                coach.calentar()
            log.info("Agent prompt prewarmed: %s", agente["id"])
        except Exception as e:
            with _lock:
                _recientes.pop(clave, None)          # que se reintente
            log.warning("Agent prewarm failed (%s)", type(e).__name__)

    hilo = threading.Thread(target=calentar, daemon=True, name="precarga")
    hilo.start()
    if esperar:
        hilo.join()
    return True


def olvidar():
    """Para las pruebas: nada se da por caliente."""
    with _lock:
        _recientes.clear()
