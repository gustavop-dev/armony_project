"""Carga y guarda la configuracion de la app en config.json (junto a este archivo).

Guarda lo que es del usuario: API keys (OpenAI, AssemblyAI y TypeSafe), idioma
y opacidad. El resto (modelo, razonamiento, longitud, deteccion de turnos, audio,
prompt del coach) va fijo en el codigo: ver FIJAS.

config.json esta en .gitignore: las claves nunca salen del equipo.
"""
import json
import logging
import os
import sys
import time

import secretstore

log = logging.getLogger("armony.config")

_HERE = os.path.dirname(os.path.abspath(__file__))


def data_dir():
    """Donde viven config.json y los contextos.

    Ejecutando el .exe NO se puede usar la carpeta del programa: PyInstaller
    descomprime en un temporal (con --onefile desaparece al cerrar) y ademas
    Archivos de Programa no es escribible. Se usa %APPDATA%\\Armony, que persiste
    entre actualizaciones. Desde el codigo fuente se sigue usando la carpeta del
    proyecto, que es lo comodo para desarrollar.
    """
    if getattr(sys, "frozen", False):
        base = os.path.join(os.environ.get("APPDATA") or _HERE, "Armony")
        os.makedirs(base, exist_ok=True)
        return base
    return _HERE


CONFIG_PATH = os.path.join(data_dir(), "config.json")

# Campos que se cifran con DPAPI al guardar y se descifran al cargar (ver
# secretstore). La clave de Anthropic ya no esta aqui: no se descifra ni se usa,
# pero si sigue en config.json se conserva tal cual, cifrada. La integracion con
# Claude se quito "por ahora" y volver no debe exigir escribirla de nuevo.
CLAVES_SECRETAS = ("openai_api_key", "assemblyai_api_key", "typesafe_api_key")

# Prompts por defecto: uno por idioma (cada instruccion va en su idioma).
DEFAULT_PROMPT_ES = (
    "Eres mi coach de reuniones en tiempo real. Escuchas lo que dicen los demas "
    "y me soplas que responder. Yo lo voy a decir en voz alta TAL CUAL, asi que "
    "tiene que sonar a mi hablando, no a un texto leido.\n"
    "Reglas:\n"
    "- Responde SIEMPRE en primera persona, listo para soltarlo tal cual.\n"
    "- Se conciso: 1 a 4 frases. Nada de rodeos ni de 'podrias decir'.\n"
    "- Habla como habla la gente, no como escribe un manual: frases de largo "
    "desigual, conectores normales, cero enumeraciones recitadas.\n"
    "- NADA de terminos tecnicos en ingles sueltos (audit trail, rollback, "
    "trade-off, deadline). Dilo en el idioma de la conversacion: 'un registro "
    "de quien toco que', 'deshacerlo todo', 'lo que ganas y lo que pierdes'.\n"
    "- Tampoco palabras de manual (idempotencia, trazabilidad, observabilidad). "
    "Di lo que significan con palabras normales.\n"
    "- Regla de oro: no uses una palabra que yo no sabria defender si me "
    "preguntan '¿y eso que es?'. Si el termino es el que se usa de verdad ahi, "
    "usalo pero acláralo en la misma frase, como quien lo explica de paso.\n"
    "- Mejor concreto que abstracto: lo que hice y por que, no la definicion.\n"
    "- Si te falta contexto, da la mejor respuesta razonable sin inventar datos."
)
DEFAULT_PROMPT_EN = (
    "You are my real-time meeting coach. You listen to the others and feed me "
    "what to say. I will say it OUT LOUD exactly as you write it, so it has to "
    "sound like me talking, not like a text being read.\n"
    "Rules:\n"
    "- ALWAYS answer in the first person, ready to say as is.\n"
    "- Be concise: 1 to 4 sentences. No filler, no 'you could say'.\n"
    "- Talk like people talk, not like a manual reads: uneven sentence length, "
    "plain connectors, no recited lists.\n"
    "- No jargon dropped in for effect (audit trail, idempotency, "
    "observability, trade-off). Say what it means in plain words: 'a record of "
    "who changed what', 'what you gain and what you lose'.\n"
    "- Golden rule: never use a word I couldn't defend if they ask 'what do you "
    "mean by that?'. If the term is the one actually used there, use it but "
    "explain it in the same breath, like someone clarifying in passing.\n"
    "- Concrete beats abstract: what I did and why, not the definition.\n"
    "- If you lack context, give the best reasonable answer without making up facts."
)
DEFAULT_SYSTEM_PROMPT = DEFAULT_PROMPT_ES   # compatibilidad

DEFAULTS = {
    # --- Modelo de las respuestas (OpenAI) ---
    # UN modelo para todo (la cache de prompt es por modelo: con dos se perdia
    # en cada salto). Lo que cambia entre los dos usos es cuanto razona:
    #   voz     -> alguien pregunta hablando. Manda la latencia: la respuesta
    #              tiene que estar antes de que el silencio se note.
    #   captura -> hay un ejercicio o codigo en pantalla. Manda la capacidad, y
    #              un par de segundos de mas no se notan porque estas leyendo.
    # Medido con 12 preguntas habladas: sol 'low' da la primera palabra en
    # ~1,05 s (terra ~0,9 s) con respuestas claramente mejores.
    "openai_api_key": "",
    "openai_model": "gpt-6.1-sol",
    "openai_effort_voice": "low",
    # Los limites de longitud van al maximo: son solo un tope (la longitud la
    # marca el prompt y solo se paga lo que se escribe) y uno justo corta
    # respuestas a medias. El razonamiento tiene su reserva aparte (llm.py).
    "openai_tokens_voice": 1000,
    "openai_effort_vision": "medium",
    # El codigo comentado linea a linea mas el enfoque y el coste ocupan: con
    # 1200 se quedaba a medias.
    "openai_tokens_vision": 4000,
    # --- Arbitro de anadidos (Jev, TypeSafe) ---
    # Decide si lo que anaden a una pregunta abierta cambia la respuesta, pide
    # otra o es ruido (followup.py). Sin clave se usa la regla fija de hilo.py:
    # todo anadido es contexto hasta que contestas.
    "typesafe_api_key": "",
    # --- Transcripcion ---
    # Por defecto se transcribe en la nube (AssemblyAI Universal Streaming): el
    # texto llega palabra a palabra mientras se habla, no al terminar la frase.
    "assemblyai_api_key": "",
    "assemblyai_model": "universal-3-5-pro",
    # Confianza para dar el turno por terminado (0-1). Mas alto = mas prudente,
    # espera mas antes de cerrar el turno; mas bajo = reacciona antes.
    "end_of_turn_threshold": 0.4,
    "language": "es",                  # es | en | auto (None)
    # Prompt del coach por idioma (Opcion B: el idioma solo afecta a coach + contexts).
    "system_prompt_es": DEFAULT_PROMPT_ES,
    "system_prompt_en": DEFAULT_PROMPT_EN,
    "invisible_on_share": True,        # ocultar la ventana al compartir pantalla
    "window_opacity": 0.65,            # 0.15 (muy transparente) a 1.0 (opaco)

    # --- Sensibilidad y ganancia ---
    # Ganancia digital aplicada antes de medir el nivel y de transcribir.
    # Sube estas si las barras se quedan cortas. 1.0 = sin cambios.
    "gain_system": 1.0,
    # Ojo: subir mucho la ganancia del micro amplifica tambien el zumbido electrico.
    # Mejor subir el nivel de entrada en Windows.
    "gain_mic": 1.0,
    # Transcribir tu micro (segundo stream de AssemblyAI, ~0,45 USD/h mas). Nunca
    # dispara respuestas: sirve para saber que ya contestaste y no ponerte otra
    # respuesta encima mientras hablas. Pensado para usar con auriculares.
    "listen_mic": True,

    # --- Agrupacion de turnos ---
    # Pausa que se espera tras un turno cerrado antes de responder: junta las
    # frases seguidas de una misma intervencion.
    "silence_hang": 0.7,
}

# Ajustes que ya no hacen nada; se borran del config.json al cargarlo para que
# no queden de recuerdo:
#   - los del antiguo modo offline (Whisper local)
#   - el modelo de voz y el de capturas por separado: ahora hay uno solo, y
#     conservarlos dejaria a cada usuario con los modelos viejos que guardo.
#   - system_prompt y max_tokens: versiones viejas del prompt y la longitud,
#     que ahora son fijos.
OBSOLETAS = ("offline_mode", "whisper_size", "whisper_device", "auto_normalize",
             "transcribe_mic", "speech_threshold", "mic_echo_gate",
             "max_utterance", "openai_model_voice", "openai_model_vision",
             "system_prompt", "max_tokens")

# Ajustes internos: ya decididos y medidos, no se configuran. Siempre valen lo
# de DEFAULTS aunque config.json traiga otro valor de una version anterior, y no
# se escriben al guardar. (test_mode, solo para desarrollo, no esta en DEFAULTS:
# se lee de config.json si alguien lo pone a mano.)
FIJAS = ("openai_model", "openai_effort_voice", "openai_tokens_voice",
         "openai_effort_vision", "openai_tokens_vision", "assemblyai_model",
         "end_of_turn_threshold", "invisible_on_share", "gain_system",
         "gain_mic", "listen_mic", "silence_hang", "system_prompt_es",
         "system_prompt_en")


def read_user_text(path):
    """Read a file the user may have edited by hand.

    Tries UTF-8 (with or without BOM), then cp1252 (Windows "ANSI"), then
    latin-1, which decodes any byte sequence. Raises OSError if unreadable.
    """
    with open(path, "rb") as f:
        raw = f.read()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    return raw.decode("latin-1")


def _quarantine(path):
    """Rename an unparseable file so the next save cannot overwrite it."""
    destino = f"{path}.bad-{time.strftime('%Y%m%d-%H%M%S')}"
    try:
        os.replace(path, destino)
        log.warning("Unparseable config moved to %s", destino)
    except OSError as e:
        log.warning("Quarantine of %s failed: %s", path, type(e).__name__)


def load_config():
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        try:
            data = json.loads(read_user_text(CONFIG_PATH))
        except OSError as e:
            # unreadable now (e.g. locked): keep the file as is
            log.warning("Config not readable (%s): %s; using defaults",
                        type(e).__name__, CONFIG_PATH)
            data = {}
        except ValueError as e:
            # not JSON; position only, never the file content
            log.warning("Config is not valid JSON (%s at line %s column %s): %s",
                        type(e).__name__, getattr(e, "lineno", None),
                        getattr(e, "colno", None), CONFIG_PATH)
            data = None
        if isinstance(data, dict):
            cfg.update(data)
        else:
            if data is not None:
                log.warning("Config top level is %s, not an object: %s",
                            type(data).__name__, CONFIG_PATH)
            _quarantine(CONFIG_PATH)
    # Las claves se guardan cifradas; el resto de la app las usa en claro.
    for k in CLAVES_SECRETAS:
        if cfg.get(k):
            cfg[k] = secretstore.revelar(cfg[k])
    for k in OBSOLETAS:
        cfg.pop(k, None)
    for k in FIJAS:
        cfg[k] = DEFAULTS[k]
    return cfg


def save_config(cfg):
    """Guarda la configuracion, cifrando las claves antes de escribirlas."""
    a_disco = {k: v for k, v in cfg.items() if k not in FIJAS}
    for k in CLAVES_SECRETAS:
        if a_disco.get(k):
            a_disco[k] = secretstore.proteger(a_disco[k])
    try:
        texto = json.dumps(a_disco, ensure_ascii=False, indent=2)
    except (TypeError, ValueError) as e:
        log.warning("Config not serializable (%s); not saved", type(e).__name__)
        return False
    # Write to a temp file and swap it in: config.json is never left truncated.
    tmp = CONFIG_PATH + ".tmp"
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH) or ".", exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(texto)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, CONFIG_PATH)
        return True
    except OSError as e:
        log.warning("Config save failed (%s): %s", type(e).__name__, CONFIG_PATH)
        try:
            os.remove(tmp)
        except OSError:
            log.debug("Temp config not removed: %s", tmp)
        return False
