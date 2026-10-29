"""Carga y guarda la configuracion de la app en config.json (junto a este archivo).

Guarda: API keys (OpenAI y AssemblyAI), modelos, ajustes de transcripcion,
idioma, prompt de coach y estado de "ventana invisible".

config.json esta en .gitignore: las claves nunca salen del equipo.
"""
import json
import os
import sys

import secretstore

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

# Campos que se guardan cifrados con DPAPI (ver secretstore). Los de Anthropic ya
# no se leen, pero si estan en config.json se conservan tal cual (cifrados): la
# integracion con Claude se quito "por ahora" y volver no debe exigir reescribirlos.
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
    "openai_tokens_voice": 400,
    "openai_effort_vision": "medium",
    # El codigo comentado linea a linea mas el enfoque y el coste ocupan: con
    # 1200 se quedaba a medias.
    "openai_tokens_vision": 2500,
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
OBSOLETAS = ("offline_mode", "whisper_size", "whisper_device", "auto_normalize",
             "transcribe_mic", "speech_threshold", "mic_echo_gate",
             "max_utterance", "openai_model_voice", "openai_model_vision")


def load_config():
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except (json.JSONDecodeError, OSError):
            pass
    # Las claves se guardan cifradas; el resto de la app las usa en claro.
    for k in CLAVES_SECRETAS:
        if cfg.get(k):
            cfg[k] = secretstore.revelar(cfg[k])
    # Migracion: si venia un unico system_prompt (version anterior), pasarlo a ES.
    legacy = cfg.pop("system_prompt", None)
    if legacy and cfg.get("system_prompt_es") == DEFAULT_PROMPT_ES:
        cfg["system_prompt_es"] = legacy

    # Migracion: antes habia un unico max_tokens; pasa a ser el de voz.
    tokens = cfg.pop("max_tokens", None)
    if tokens:
        cfg["openai_tokens_voice"] = int(tokens)
    for k in OBSOLETAS:
        cfg.pop(k, None)
    return cfg


def save_config(cfg):
    """Guarda la configuracion, cifrando las claves antes de escribirlas."""
    a_disco = dict(cfg)
    for k in CLAVES_SECRETAS:
        if a_disco.get(k):
            a_disco[k] = secretstore.proteger(a_disco[k])
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH) or ".", exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(a_disco, f, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False
