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
    """Cliente del coach. Usa un modelo distinto segun de donde venga la pregunta.

    Hablada: manda la latencia, la respuesta tiene que llegar antes de que el
    silencio se note. Con captura de pantalla: manda la capacidad, porque suele
    haber codigo que resolver, y un par de segundos de mas no molestan porque
    estas leyendo.
    """

    def __init__(self, api_key, system_prompt="", provider=ANTHROPIC,
                 model_voice="claude-haiku-4-5", tokens_voice=400,
                 model_vision=None, tokens_vision=None):
        self.provider = (provider or ANTHROPIC).lower()
        self.system_prompt = system_prompt
        self.model_voice = model_voice
        self.tokens_voice = int(tokens_voice)
        # Sin modelo de capturas configurado se usa el mismo que para voz: mejor
        # responder algo que fallar por configuracion incompleta.
        self.model_vision = model_vision or model_voice
        self.tokens_vision = int(tokens_vision or tokens_voice)
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
            # Con capturas la pregunta suele ser tecnica: hace falta la solucion
            # entera, no un resumen hablado. El codigo va en su propio bloque para
            # que el panel lo pinte como codigo y se pueda copiar.
            extra += (
                f"\n\nAdjunto {n_img} captura(s) de mi pantalla. Si contienen el "
                "enunciado o el codigo del que se habla, respondele a eso.\n"
                "Si hay que escribir o corregir codigo:\n"
                "- Da la solucion COMPLETA, lista para usar, dentro de un bloque "
                "cercado con ``` y el lenguaje (por ejemplo ```python).\n"
                "- No cortes el codigo ni pongas '...': tiene que poder copiarse "
                "y ejecutarse.\n"
                "- Despues explicamela hablada, como si yo se la estuviera "
                "explicando a la otra persona de tu a tu: que hace, por que "
                "funciona y su coste si viene al caso. Sin dar clase.")
        prompt = (
            "Contexto reciente de la reunion. 'Ellos' son los demas "
            "participantes; 'Yo' es lo que ya he dicho; y 'Yo (sugerido)' es lo "
            "que me sugeriste antes, que muy probablemente dije con mis palabras "
            "-- dalo por dicho: no lo repitas, continua desde ahi:\n"
            f"{context_text or '(sin contexto previo)'}\n\n"
            f"Lo ultimo que dijeron los demas: \"{latest}\"{extra}\n\n"
            "IDIOMA: responde en el MISMO idioma en que esta lo ultimo que "
            "dijeron, aunque el contexto anterior o estas instrucciones esten en "
            "otro. Si la reunion cambia de idioma a mitad, cambias con ella: lo "
            "que te devuelvo es lo que voy a decir yo en voz alta.\n\n"
            "Dame, en primera persona y listo para decir en voz alta, que deberia "
            "responder yo. SIEMPRE en primera persona, como si yo estuviera "
            "hablando: nunca en tercera persona, ni en tono de documentacion, ni "
            "diciendome lo que 'podrias responder'. IMPORTANTE: no repitas lo que "
            "yo ya dije en el contexto; si ya respondi algo, continua o "
            "complementa.\n\n"
            "FORMATO OBLIGATORIO: divide la respuesta en secciones, cada una con un "
            "encabezado en su propia linea que empiece por '## '. Usa de una a cuatro "
            "secciones con encabezados cortos y propios, elegidos segun la pregunta "
            "(por ejemplo '## Answer', '## Context', '## Example', '## Next step'). "
            "Cada seccion, una o dos frases; los bloques de codigo pueden ser tan "
            "largos como haga falta. Dentro de las secciones puedes usar "
            "**negritas**, `codigo en linea`, listas con '- ' y bloques cercados "
            "con ```lenguaje. Sin texto fuera de las secciones.\n\n"
            "CUANDO HAYAS TENIDO QUE SUPONER ALGO IMPORTANTE para responder "
            "(no sabes su stack, su volumen, que lenguaje quieren, que parte les "
            "preocupa...): responde IGUALMENTE con tu propuesta, di en una linea "
            "que lo estas suponiendo, y AÑADE al final una seccion "
            "'## Necesito saber' con UNA pregunta corta: la que mas cambiaria tu "
            "respuesta. Escribela como yo se la diria a la otra persona, para "
            "poder soltarla en voz alta tal cual.\n"
            "Dos limites: NUNCA respondas solo con la pregunta, porque sin "
            "propuesta no me sirves de nada en mitad de una reunion; y si ya me "
            "dijeron que ese dato no me lo pueden dar, o que justo eso es lo que "
            "tengo que resolver, no vuelvas a preguntarlo: propon y deja claras "
            "tus suposiciones."
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
        modelo, tokens = self.elegir_modelo(images)
        try:
            if self.provider == OPENAI:
                self._stream_openai(prompt, images, on_delta, modelo, tokens)
            else:
                self._stream_anthropic(prompt, images, on_delta, modelo, tokens)
            if on_done:
                on_done()
        except Exception as e:
            if on_error:
                on_error(str(e))

    def elegir_modelo(self, images):
        """(modelo, tokens) segun haya captura de pantalla o no."""
        if images:
            return self.model_vision, self.tokens_vision
        return self.model_voice, self.tokens_voice

    # ---------------------------------------------------------------- backends
    def _stream_anthropic(self, prompt, images, on_delta, modelo, tokens):
        content = []
        for img in (images or []):
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": img},
            })
        content.append({"type": "text", "text": prompt})

        with self.client.messages.stream(
            model=modelo,
            max_tokens=tokens,
            system=self.system_prompt,
            messages=[{"role": "user", "content": content}],
        ) as stream:
            for text in stream.text_stream:
                if on_delta:
                    on_delta(text)

    def _stream_openai(self, prompt, images, on_delta, modelo, tokens):
        content = []
        for img in (images or []):
            content.append({"type": "input_image",
                            "image_url": f"data:image/png;base64,{img}"})
        content.append({"type": "input_text", "text": prompt})

        with self.client.responses.stream(
            model=modelo,
            instructions=self.system_prompt,
            input=[{"role": "user", "content": content}],
            max_output_tokens=tokens + _RESERVA_RAZONAMIENTO,
        ) as stream:
            for ev in stream:
                if ev.type == "response.output_text.delta" and on_delta:
                    on_delta(ev.delta)
