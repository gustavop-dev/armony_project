"""Carga y guarda la configuracion de la app en config.json (junto a este archivo).

Guarda: API keys (Anthropic y AssemblyAI), modelo LLM, ajustes de transcripcion
(nube o modo offline con Whisper), idioma, prompt de coach y estado de "ventana
invisible".

config.json esta en .gitignore: las claves nunca salen del equipo.
"""
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(_HERE, "config.json")

# Prompts por defecto: uno por idioma (cada instruccion va en su idioma).
DEFAULT_PROMPT_ES = (
    "Eres un coach de reuniones en tiempo real. Escuchas lo que dicen los demas "
    "participantes y me sugieres, de forma breve y natural, que deberia responder yo. "
    "Reglas:\n"
    "- Responde SIEMPRE como si fueras yo hablando (primera persona), listo para decirlo en voz alta.\n"
    "- Se conciso: 1 a 4 frases. Nada de rodeos ni de 'podrias decir'.\n"
    "- Suena humano, cercano y seguro. Evita sonar robotico o generico.\n"
    "- Si te falta contexto, da la mejor respuesta razonable sin inventar datos."
)
DEFAULT_PROMPT_EN = (
    "You are a real-time meeting coach. You listen to what the other participants say "
    "and suggest, briefly and naturally, what I should reply. "
    "Rules:\n"
    "- ALWAYS answer as if I were speaking (first person), ready to say out loud.\n"
    "- Be concise: 1 to 4 sentences. No filler, no 'you could say'.\n"
    "- Sound human, warm and confident. Avoid sounding robotic or generic.\n"
    "- If you lack context, give the best reasonable answer without making up facts."
)
DEFAULT_SYSTEM_PROMPT = DEFAULT_PROMPT_ES   # compatibilidad

DEFAULTS = {
    "anthropic_api_key": "",
    "llm_model": "claude-haiku-4-5",   # el mas rapido; cambiar a claude-opus-4-8 para mas calidad
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
    "max_tokens": 400,

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
    # Migracion: si venia un unico system_prompt (version anterior), pasarlo a ES.
    legacy = cfg.pop("system_prompt", None)
    if legacy and cfg.get("system_prompt_es") == DEFAULT_PROMPT_ES:
        cfg["system_prompt_es"] = legacy
    return cfg


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False
