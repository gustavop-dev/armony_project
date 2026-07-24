"""Cliente de Claude (Anthropic) con streaming.

Recibe el contexto de la reunion (ultimas frases) y, opcionalmente, un screenshot,
y devuelve token por token la respuesta sugerida.
"""
import anthropic


class Coach:
    def __init__(self, api_key, model="claude-haiku-4-5", system_prompt="", max_tokens=400):
        self.model = model
        self.system_prompt = system_prompt
        self.max_tokens = max_tokens
        self.client = anthropic.Anthropic(api_key=api_key)

    def stream_response(self, context_text, latest, images=None, note=None,
                        on_delta=None, on_done=None, on_error=None):
        """Genera la respuesta sugerida en streaming.

        context_text: transcripcion reciente (contexto).
        latest: la ultima frase de los demas (lo que hay que responder).
        image_b64: PNG en base64 opcional (screenshot) para preguntas visuales.
        """
        content = []
        for img in (images or []):
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": img},
            })
        n_img = len(images or [])
        extra = f"\n\nIndicacion mia para orientar la respuesta: \"{note}\"" if note else ""
        if n_img:
            extra += (f"\n\nAdjunto {n_img} captura(s) de mi pantalla. Si contienen el "
                      "enunciado o el codigo del que se habla, respondele a eso.")
        prompt = (
            "Contexto reciente de la reunion. 'Ellos' son los demas participantes "
            "y 'Yo' es lo que ya he dicho:\n"
            f"{context_text or '(sin contexto previo)'}\n\n"
            f"Lo ultimo que dijeron los demas: \"{latest}\"{extra}\n\n"
            "Dame, en primera persona y listo para decir en voz alta, que deberia "
            "responder yo. IMPORTANTE: no repitas lo que yo ya dije en el contexto; "
            "si ya respondi algo, continua o complementa.\n\n"
            "FORMATO OBLIGATORIO: divide la respuesta en secciones, cada una con un "
            "encabezado en su propia linea que empiece por '## '. Usa de una a cuatro "
            "secciones con encabezados cortos y propios, elegidos segun la pregunta "
            "(por ejemplo '## Answer', '## Context', '## Example', '## Next step'). "
            "Cada seccion, una o dos frases. Sin texto fuera de las secciones."
        )
        content.append({"type": "text", "text": prompt})

        try:
            with self.client.messages.stream(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self.system_prompt,
                messages=[{"role": "user", "content": content}],
            ) as stream:
                for text in stream.text_stream:
                    if on_delta:
                        on_delta(text)
            if on_done:
                on_done()
        except Exception as e:
            if on_error:
                on_error(str(e))
