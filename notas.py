"""Notas de la reunion: resumen, decisiones, tareas y preguntas abiertas.

Se generan al terminar, a partir de lo que se dijo (lo de los demas y lo tuyo;
las sugerencias no, porque no sabemos si las dijiste), y quedan en el historial
junto a la transcripcion. El agente notetaker las toma siempre; los demas, si
tienen "Notas al terminar".
"""
import logging

log = logging.getLogger("armony.notas")

# Con menos que esto no hay reunion que resumir.
MIN_INTERVENCIONES = 2
# Tope de lo que se manda: una reunion de una hora cabe de sobra.
MAX_CARACTERES = 120_000

PROMPT_NOTAS = (
    "Eres quien toma las notas de una reunion. Te paso la transcripcion: 'Ellos' "
    "son los demas participantes y 'Yo' soy yo. Escribe las notas en markdown, "
    "en el idioma en que se hablo, con estas secciones (omite las que queden "
    "vacias):\n"
    "## Resumen — de que se hablo, en 3 a 6 lineas.\n"
    "## Decisiones — lo que quedo decidido.\n"
    "## Tareas — quien hace que y para cuando, si se dijo ('- [ ] ...').\n"
    "## Preguntas abiertas — lo que quedo sin responder o pendiente.\n"
    "## Datos clave — cifras, nombres de producto, fechas, requisitos.\n\n"
    "Se fiel a lo dicho: no inventes nada ni rellenes huecos. La transcripcion "
    "es automatica y puede tener errores: si algo no se entiende, no lo "
    "deduzcas.")


def transcripcion(registro):
    """Lo hablado, linea a linea. Fuera las sugerencias y los avisos internos."""
    lineas = [f"{quien}: {texto.strip()}" for quien, texto in registro
              if quien in ("Ellos", "Yo") and str(texto).strip()]
    texto = "\n".join(lineas)
    return texto[-MAX_CARACTERES:]


def hay_que_resumir(registro):
    return sum(1 for quien, t in registro
               if quien in ("Ellos", "Yo") and str(t).strip()) >= MIN_INTERVENCIONES


def generar(api_key, model, registro, effort="low"):
    """Notas en markdown (llamada a OpenAI; tarda unos segundos)."""
    import openai
    cliente = openai.OpenAI(api_key=api_key, max_retries=1,
                            timeout=openai.Timeout(120, connect=10))
    respuesta = cliente.responses.create(
        model=model,
        input=[{"role": "developer", "content": [{"type": "input_text", "text": PROMPT_NOTAS}]},
               {"role": "user", "content": [{"type": "input_text",
                                             "text": transcripcion(registro)}]}],
        reasoning={"effort": effort}, max_output_tokens=4000)
    texto = (getattr(respuesta, "output_text", "") or "").strip()
    if not texto:
        raise RuntimeError("el modelo no devolvió texto")
    return texto
