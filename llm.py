"""Cliente del coach con streaming: Anthropic o OpenAI, a elegir.

Recibe el contexto de la reunion (ultimas frases) y, opcionalmente, capturas de
pantalla, y devuelve token por token la respuesta sugerida.

Los dos proveedores comparten exactamente el mismo prompt. Lo unico que cambia
es como se empaqueta la peticion y de donde se sacan los trozos de texto, asi
que el resto de la app no sabe cual esta configurado.
"""

ANTHROPIC = "anthropic"
OPENAI = "openai"

# Los modelos gpt-5 razonan antes de responder y ese razonamiento, aunque no se
# vea, gasta del mismo presupuesto de tokens. Sin esta reserva un limite bajo se
# lo comeria el razonamiento y la respuesta llegaria vacia. El ajuste del usuario
# sigue significando lo que dice: longitud de la RESPUESTA.
_RESERVA_RAZONAMIENTO = 1000


class Coach:
    def __init__(self, api_key, model="claude-haiku-4-5", system_prompt="",
                 max_tokens=400, provider=ANTHROPIC):
        self.provider = (provider or ANTHROPIC).lower()
        self.model = model
        self.system_prompt = system_prompt
        self.max_tokens = int(max_tokens)
        # Importe perezoso: solo se exige tener instalado el proveedor que se usa.
        if self.provider == OPENAI:
            from openai import OpenAI
            self.client = OpenAI(api_key=api_key)
        else:
            import anthropic
            self.client = anthropic.Anthropic(api_key=api_key)

    # ------------------------------------------------------------------ prompt
    def _prompt(self, context_text, latest, images, note, allow_silence):
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
        if allow_silence:
            # Segunda puerta: en una reunion la mayor parte del tiempo el otro
            # esta dando contexto, no preguntando. El filtro local ya descarto lo
            # evidente; aqui se descarta lo que solo lo parecia.
            prompt += (
                "\n\nANTES DE RESPONDER: mira si en 'lo ultimo que dijeron' hay "
                "de verdad una pregunta o una peticion dirigida a mi. Si solo "
                "estan contando algo, dando contexto o pensando en voz alta, "
                "responde EXACTAMENTE la palabra NO_RESPONSE y nada mas, sin "
                "secciones ni explicaciones. Ante la duda, responde normal."
            )
        return prompt

    # ------------------------------------------------------------------ publico
    def stream_response(self, context_text, latest, images=None, note=None,
                        on_delta=None, on_done=None, on_error=None,
                        allow_silence=False):
        """Genera la respuesta sugerida en streaming.

        context_text: transcripcion reciente (contexto).
        latest: la ultima frase de los demas (lo que hay que responder).
        images: lista de PNG en base64 (capturas) para preguntas visuales.
        allow_silence: permitir que el modelo se calle si no le han preguntado
            nada. Devuelve NO_RESPONSE y quien llama decide no mostrar nada.
            Se desactiva cuando el usuario pide la respuesta a mano: entonces
            quiere una sugerencia si o si.
        """
        prompt = self._prompt(context_text, latest, images, note, allow_silence)
        try:
            if self.provider == OPENAI:
                self._stream_openai(prompt, images, on_delta)
            else:
                self._stream_anthropic(prompt, images, on_delta)
            if on_done:
                on_done()
        except Exception as e:
            if on_error:
                on_error(str(e))

    # ---------------------------------------------------------------- backends
    def _stream_anthropic(self, prompt, images, on_delta):
        content = []
        for img in (images or []):
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": img},
            })
        content.append({"type": "text", "text": prompt})

        with self.client.messages.stream(
            model=self.model,
            max_tokens=self.max_tokens,
            system=self.system_prompt,
            messages=[{"role": "user", "content": content}],
        ) as stream:
            for text in stream.text_stream:
                if on_delta:
                    on_delta(text)

    def _stream_openai(self, prompt, images, on_delta):
        content = []
        for img in (images or []):
            content.append({"type": "input_image",
                            "image_url": f"data:image/png;base64,{img}"})
        content.append({"type": "input_text", "text": prompt})

        with self.client.responses.stream(
            model=self.model,
            instructions=self.system_prompt,
            input=[{"role": "user", "content": content}],
            max_output_tokens=self.max_tokens + _RESERVA_RAZONAMIENTO,
        ) as stream:
            for ev in stream:
                if ev.type == "response.output_text.delta" and on_delta:
                    on_delta(ev.delta)
