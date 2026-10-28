"""Carga y guarda la configuracion de la app en config.json (junto a este archivo).

Guarda: API keys (Anthropic, OpenAI y AssemblyAI), proveedor y modelo, ajustes
de transcripcion
(nube o modo offline con Whisper), idioma, prompt de coach y estado de "ventana
invisible".

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

# Campos que se guardan cifrados con DPAPI (ver secretstore).
CLAVES_SECRETAS = ("anthropic_api_key", "openai_api_key", "assemblyai_api_key")

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
    # --- Proveedor de las respuestas ---
    # 'anthropic' | 'openai'. Cada uno con su clave y sus modelos, para poder
    # cambiar de uno a otro sin volver a escribir nada.
    #
    # Hay DOS modelos por proveedor porque los dos usos no se parecen:
    #   voz     -> alguien pregunta hablando. Manda la latencia: la respuesta
    #              tiene que estar antes de que el silencio se note.
    #   captura -> hay un ejercicio o codigo en pantalla. Manda la capacidad, y
    #              un par de segundos de mas no se notan porque estas leyendo.
    "llm_provider": "anthropic",

    "anthropic_api_key": "",
    "anthropic_model_voice": "claude-haiku-4-5",     # el mas rapido
    "anthropic_tokens_voice": 400,
    "anthropic_model_vision": "claude-sonnet-5",     # mas capaz para codigo
    # El codigo comentado linea a linea mas el enfoque y el coste ocupan: con
    # 1200 se quedaba a medias.
    "anthropic_tokens_vision": 2500,

    "openai_api_key": "",
    # gpt-5.4-nano queda fuera a proposito: es el mas rapido, pero 1 de cada 5
    # veces ignora la instruccion de callarse cuando no hay pregunta y escribe
    # excusas en el panel. La velocidad no compensa ensuciar la pantalla.
    "openai_model_voice": "gpt-5.6-terra",           # 0,8 s a la primera palabra
    "openai_tokens_voice": 400,
    "openai_model_vision": "gpt-5.6-sol",
    "openai_tokens_vision": 2500,
    # --- Transcripcion ---
    # Por defecto se transcribe en la nube (AssemblyAI Universal Streaming): el
    # texto llega palabra a palabra mientras se habla, no al terminar la frase.
    "assemblyai_api_key": "",
    "assemblyai_model": "universal-3-5-pro",
    # Confianza para dar el turno por terminado (0-1). Mas alto = mas prudente,
    # espera mas antes de cerrar el turno; mas bajo = reacciona antes.
    "end_of_turn_threshold": 0.4,
    # Modo offline: vuelve a la transcripcion local con Whisper. Sirve si no hay
    # internet o no quieres que el audio salga del equipo. Mas lento y no da
    # texto en vivo: hay que esperar a que la frase termine.
    "offline_mode": False,
    "whisper_size": "base",            # tiny | base | small | medium (solo offline)
    "whisper_device": "auto",          # auto | cpu | cuda (solo offline)
    "language": "es",                  # es | en | auto (None)
    # Prompt del coach por idioma (Opcion B: el idioma solo afecta a coach + contexts).
    "system_prompt_es": DEFAULT_PROMPT_ES,
    "system_prompt_en": DEFAULT_PROMPT_EN,
    "invisible_on_share": True,        # ocultar la ventana al compartir pantalla
    "window_opacity": 0.65,            # 0.15 (muy transparente) a 1.0 (opaco)

    # --- Sensibilidad y ganancia ---
    # Ganancia digital aplicada antes de medir el nivel y de detectar voz.
    # Sube estas si las barras se quedan cortas. 1.0 = sin cambios.
    "gain_system": 1.0,
    # Ojo: subir mucho la ganancia del micro amplifica tambien el zumbido electrico
    # y el eco de los altavoces. Mejor subir el nivel de entrada en Windows.
    "gain_mic": 1.0,
    # Ignora el microfono mientras suena el audio de la reunion. Evita que el eco de
    # los altavoces se transcriba como si fuera tu voz (duplicando lo que ya capta
    # el loopback, pero sucio). Con auriculares da igual; con altavoces es clave.
    "mic_echo_gate": True,
    # Transcribir tambien tu voz en modo normal. Sirve para dos cosas:
    # 1) Acta completa de la reunion (lo que dijo cada uno).
    # 2) Claude sabe que respondiste ya y no te sugiere repetirlo.
    # Nunca dispara una sugerencia: solo responde a lo que dicen los demas.
    "transcribe_mic": True,
    # Umbral de energia para considerar que hay voz. MAS BAJO = MAS SENSIBLE.
    # 0.012 por defecto; 0.006 capta susurros pero tambien mas ruido.
    "speech_threshold": 0.012,
    # Normaliza cada frase al nivel optimo antes de Whisper. Resuelve el problema
    # de volumen bajo mucho mejor que la ganancia manual. Recomendado: True.
    "auto_normalize": True,

    # --- Segmentacion de frases ---
    # Silencio necesario para dar la frase por terminada (= te cedieron el turno).
    "silence_hang": 0.7,
    # Corte de seguridad para monologos largos sin pausas. Estos fragmentos se
    # transcriben pero NO disparan respuesta (nadie te ha preguntado nada aun).
    "max_utterance": 8.0,
}


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

    # Migracion: antes habia UN modelo por proveedor y un unico max_tokens. Lo
    # guardado se conserva como modelo de voz, para no cambiarle la configuracion
    # a nadie por debajo; el de capturas se queda con el valor por defecto.
    for viejo, nuevo in (("llm_model", "anthropic_model_voice"),
                         ("openai_model", "openai_model_voice")):
        anterior = cfg.pop(viejo, None)
        if anterior:
            cfg[nuevo] = anterior
    tokens = cfg.pop("max_tokens", None)
    if tokens:
        cfg["anthropic_tokens_voice"] = cfg["openai_tokens_voice"] = int(tokens)
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
