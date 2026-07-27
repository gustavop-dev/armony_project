"""Motor de Meeting Coach: audio -> transcripcion -> Claude (streaming).

Sin dependencias de interfaz: expone senales Qt y no sabe como se dibuja nada.

Hay dos caminos de transcripcion, y cambian bastante el comportamiento:

  En la nube (por defecto, AssemblyAI): el audio de la reunion viaja continuo y
  el texto vuelve palabra a palabra mientras la persona habla. El fin de turno
  lo decide el propio modelo.

  Offline (Whisper local): se corta el audio en frases por silencio y cada una
  se transcribe entera. No hay texto en vivo y se nota mas retardo, pero no sale
  nada del equipo y funciona sin internet.
"""
import os
import re
import time
import queue
import threading
from collections import deque

import numpy as np
from PySide6 import QtCore

import intent
from metrics import E2E, LLM_CALENTAMIENTO, STT_LATENCIA, metricas

# Palabra con la que el modelo avisa de que no le han preguntado nada. Nunca
# llega a pintarse: se usa solo para decidir que no hay nada que sugerir.
SENTINEL = "NO_RESPONSE"

# Cuanta reunion se recuerda y cuanta se manda en cada respuesta.
#
# Una pregunta hablada se responde con lo justo: manda la latencia y lo que
# acaban de decir explica casi siempre lo que preguntan. Una captura es otra
# cosa: el pantallazo suele ser solo una PARTE del problema, y el resto esta en
# lo que llevan un rato contando. Ahi compensa mandar el hilo largo, que ademas
# se paga una vez y no en cada frase.
# Ojo al contar: cada turno respondido deja DOS entradas (lo que dijeron y lo
# que se sugirio), asi que estos numeros son entradas, no turnos. Se doblaron al
# empezar a guardar las sugerencias para que el hilo real siguiera siendo el
# mismo que antes.
MEMORIA = 120             # entradas en memoria (~60 turnos)
CONTEXTO_VOZ = 36         # las que acompañan a una pregunta hablada (~18 turnos)
CONTEXTO_CAPTURA = 80     # las que acompañan a un pantallazo (~40 turnos)
LIMITE_CHARS_CAPTURA = 8000   # tope por si alguien se explaya de verdad

# De cada sugerencia se guarda un resumen corto, no la respuesta entera: sirve
# para que no te repita lo mismo, no para reconstruirla.
RESUMEN_SUGERENCIA = 240


def _resumen(texto, limite=RESUMEN_SUGERENCIA):
    """Version corta de una sugerencia, para guardarla como contexto.

    Fuera los bloques de codigo y los encabezados: ocupan muchisimo y no son lo
    que tu dirias en voz alta, que es lo unico que hace falta recordar.
    """
    sin_codigo = re.sub(r"```.*?```", " [código] ", texto or "", flags=re.S)
    sin_titulos = re.sub(r"^#+ .*$", "", sin_codigo, flags=re.M)
    limpio = " ".join(sin_titulos.split())
    return limpio[:limite] + ("…" if len(limpio) > limite else "")


def _prompt_bilingue(cfg):
    """Junta las dos versiones del prompt del coach, la española y la inglesa.

    Son las mismas instrucciones escritas en cada idioma, y se mandan las dos a
    proposito: asi el modelo tiene sus reglas en el idioma que toque cuando la
    reunion cambia de uno a otro, sin tener que reiniciar nada.
    """
    es = (cfg.get("system_prompt_es") or "").strip()
    en = (cfg.get("system_prompt_en") or "").strip()
    if es and en:
        return (f"{es}\n\n---\n\n(The same instructions in English; follow "
                f"whichever matches the language being spoken.)\n\n{en}")
    return es or en or (cfg.get("system_prompt") or "")


class CoachEngine(QtCore.QObject):
    sysLevel = QtCore.Signal(int)
    micLevel = QtCore.Signal(int)
    sttLatency = QtCore.Signal(int)       # ms que tardo la ultima transcripcion
    e2eLatency = QtCore.Signal(int)       # ms de la pregunta a la primera palabra
    transcript = QtCore.Signal(str, str)  # (fuente, texto): fuente = 'system' | 'mic'
    partial = QtCore.Signal(str)          # texto provisional, se repinta en vivo
    noAnswer = QtCore.Signal(str)         # no habra sugerencia, y por que
    respStart = QtCore.Signal()
    respDelta = QtCore.Signal(str)
    respDone = QtCore.Signal()
    status = QtCore.Signal(str)
    error = QtCore.Signal(str)

    def __init__(self):
        super().__init__()
        self._running = False
        self._queue = queue.Queue()
        # Se guarda bastante mas de lo que se manda en cada respuesta: asi una
        # captura puede llevarse el hilo largo de la conversacion (ver _contexto).
        self._history = deque(maxlen=MEMORIA)
        self._audio = None
        self._transcriber = None
        self._stt = None
        self._coach = None
        self._worker = None
        self._stop_event = None
        self._test_mode = False
        self._offline = False
        self._auto_normalize = True
        self._transcribe_mic = True
        self._language = "es"
        self._last_question = ""      # ultima a la que SI se respondio
        self._last_heard = ""         # ultimo turno oido, se respondiera o no
        self._t_pregunta = 0.0        # cuando se cerro la pregunta (para el e2e)
        self._registro = []           # acta de la reunion, para repasarla luego

        # Agrupacion de turnos (solo en la nube). AssemblyAI cierra un turno por
        # cada frase, asi que un "¿Como vais? ¿Llegamos el viernes?" llega en dos
        # trozos. Responder a cada uno seria atropellado: se acumulan y solo se
        # llama a Claude cuando pasa _turn_gap sin que nadie hable.
        self._turn_lock = threading.Lock()
        self._turn_parts = []
        self._turn_timer = None
        self._turn_gap = 0.7

    def start(self, cfg, test_mode=False):
        """test_mode: solo audio + transcripcion (sin API key, sin llamar a Claude)."""
        if self._running:
            return
        # Cola NUEVA en cada arranque: nada de la sesion anterior puede colarse.
        # (Antes quedaban frases viejas y el centinela None, que mataba al worker.)
        self._queue = queue.Queue()
        self._stop_event = threading.Event()
        self._history.clear()
        self._last_question = ""
        self._last_heard = ""
        self._language = cfg.get("language", "es")
        self._running = True
        self._test_mode = test_mode
        self._offline = bool(cfg.get("offline_mode", False))
        self._auto_normalize = bool(cfg.get("auto_normalize", True))
        self._transcribe_mic = bool(cfg.get("transcribe_mic", True))
        self._turn_gap = float(cfg.get("silence_hang", 0.7))
        self._turn_parts = []
        self._t_pregunta = 0.0
        self._registro = []

        metricas.iniciar()
        p = "openai" if cfg.get("llm_provider") == "openai" else "anthropic"
        metricas.nota(f"proveedor: {p}")
        if not self._offline:
            metricas.nota(f"transcripcion: {cfg.get('assemblyai_model')}")
            metricas.nota(f"voz: {cfg.get(f'{p}_model_voice')} · "
                          f"capturas: {cfg.get(f'{p}_model_vision')}")
        else:
            metricas.nota(f"transcripcion: whisper {cfg.get('whisper_size')} "
                          f"({cfg.get('whisper_device')})")
        # La inicializacion (cargar modelo) puede tardar: hazla en un hilo.
        threading.Thread(target=self._init_and_run, args=(cfg,), daemon=True).start()

    def _init_and_run(self, cfg):
        # Importes tardios para que la ventana abra rapido.
        from llm import Coach
        from audio import AudioEngine

        if self._offline:
            from transcribe import Transcriber
            try:
                self.status.emit(
                    "Cargando modelo de transcripcion (primera vez descarga)...")
                self._transcriber = Transcriber(
                    size=cfg["whisper_size"],
                    device=cfg["whisper_device"],
                    language=cfg["language"],
                )
                self.status.emit(f"Whisper listo en {self._transcriber.device.upper()}.")
            except Exception as e:
                self.error.emit(f"No se pudo cargar Whisper: {e}")
                self._running = False
                return
        else:
            from stt_stream import StreamingSTT
            if not cfg.get("assemblyai_api_key"):
                self.error.emit(
                    "Falta la API key de AssemblyAI. Ponla en Ajustes, o activa "
                    "el modo offline para transcribir con Whisper local.")
                self._running = False
                return
            self._stt = StreamingSTT(
                api_key=cfg["assemblyai_api_key"],
                on_partial=self._on_stt_partial,
                on_final=self._on_stt_final,
                on_status=lambda m: self._running and self.status.emit(m),
                on_error=lambda m: self._running and self.error.emit(m),
                language=cfg.get("language", "es"),
                model=cfg.get("assemblyai_model", "universal-3-5-pro"),
                end_of_turn_threshold=cfg.get("end_of_turn_threshold", 0.4),
            )
            self._stt.start()
            self.status.emit("Conectando la transcripcion en vivo...")

        if not self._test_mode:
            try:
                # Se le da TODO: los dos prompts del coach y todos los contextos
                # activos, sin filtrar por idioma. En una reunion real se cambia
                # de idioma a media frase, y si el prompt o el contexto vinieran
                # filtrados por el idioma configurado, justo al cambiar se
                # quedaria sin la mitad de lo que necesita. Se congela AQUI para
                # no romper el cache a media llamada.
                import contexts as ctx_mod
                sys_prompt = _prompt_bilingue(cfg)
                extra = ctx_mod.active_text("auto")     # 'auto' = todos
                if extra:
                    sys_prompt += "\n\n# Contexto de esta reunion\n" + extra
                # Cada proveedor trae su clave y sus dos modelos: uno para las
                # preguntas habladas y otro, mas capaz, para las capturas.
                p = "openai" if cfg.get("llm_provider") == "openai" else "anthropic"
                self._coach = Coach(
                    api_key=cfg[f"{p}_api_key"],
                    system_prompt=sys_prompt,
                    provider=p,
                    model_voice=cfg[f"{p}_model_voice"],
                    tokens_voice=int(cfg[f"{p}_tokens_voice"]),
                    model_vision=cfg[f"{p}_model_vision"],
                    tokens_vision=int(cfg[f"{p}_tokens_vision"]),
                )
            except Exception as e:
                self.error.emit(f"No se pudo iniciar Claude: {e}")
                self._running = False
                return

            # Calentar la conexion mientras te acomodas: la primera peticion
            # paga DNS, TLS y el procesado inicial del prompt con tus contextos.
            # Va en su hilo para no retrasar el arranque de la reunion.
            threading.Thread(target=self._calentar, daemon=True).start()

        # El worker recibe SU cola y SU senal de parada. Asi un worker rezagado de una
        # sesion anterior no puede consumir eventos de la sesion nueva.
        self._worker = threading.Thread(
            target=self._process_loop,
            args=(self._queue, self._stop_event),
            daemon=True,
        )
        self._worker.start()

        self._audio = AudioEngine(
            # Envolvemos los emit: si ya se detuvo, no tocar la UI (Qt puede estar
            # destruyendo los widgets y emitir ahi provoca un segfault al cerrar).
            on_sys_level=lambda v: self._running and self.sysLevel.emit(v),
            on_mic_level=lambda v: self._running and self.micLevel.emit(v),
            on_utterance=self._on_utterance,
            on_status=lambda m: self._running and self.status.emit(m),
            # Transcribir el micro en Modo prueba, o si el usuario lo activo para
            # tener acta completa y dar contexto a Claude de lo que ya respondio.
            # En la nube solo se transcribe la reunion: un unico stream. Tu micro
            # sigue midiendo nivel (la barra) pero no se manda a transcribir.
            capture_mic_utterances=self._offline and (self._test_mode
                                                      or self._transcribe_mic),
            on_system_pcm=None if self._offline else self._stt.feed,
            segment_system=self._offline,
            gain_system=cfg.get("gain_system", 1.0),
            gain_mic=cfg.get("gain_mic", 1.0),
            speech_threshold=cfg.get("speech_threshold", 0.012),
            silence_hang=cfg.get("silence_hang", 0.7),
            max_utterance=cfg.get("max_utterance", 8.0),
            mic_echo_gate=cfg.get("mic_echo_gate", True),
        )
        self._audio.start()
        if self._test_mode and self._offline:
            self.status.emit(
                "MODO PRUEBA: transcribe reunion y microfono. No se llama a Claude.")
        elif self._test_mode:
            self.status.emit(
                "MODO PRUEBA: transcribe la reunion en vivo. No se llama a Claude.")
        else:
            self.status.emit("Escuchando la reunion. Habla y aparecera la sugerencia.")

    # ---------------------------------------------- transcripcion en la nube
    # Estos tres metodos los llama el hilo del WebSocket: nada de trabajo pesado
    # aqui dentro, solo emitir senales y dejar la respuesta al worker.
    def _on_stt_partial(self, texto):
        # Se muestra lo ya cerrado de esta intervencion mas lo que se esta
        # diciendo: el texto crece de corrido en vez de saltar en cada frase.
        if not self._running:
            return
        with self._turn_lock:
            previo = " ".join(self._turn_parts)
        self.partial.emit((previo + " " + texto).strip())

    def _on_stt_final(self, texto, latencia_ms):
        if not self._running:
            return
        # Aqui y no en el cliente de streaming: asi tambien cuenta el modo
        # offline, que mide la latencia por su cuenta.
        metricas.medir(STT_LATENCIA, latencia_ms)
        self.sttLatency.emit(latencia_ms)
        if self._test_mode:
            self.transcript.emit("system", texto)
            self.status.emit(f"Transcrito en {latencia_ms} ms (reunion).")
            return
        # Si la frase ya trae la pregunta, no se espera la pausa: se responde en
        # cuanto se sabe que hay algo que responder.
        hay_pregunta = intent.parece_pregunta(texto, self._language)
        with self._turn_lock:
            self._turn_parts.append(texto)
            acumulado = " ".join(self._turn_parts)
            if self._turn_timer is not None:
                self._turn_timer.cancel()
                self._turn_timer = None
            if not hay_pregunta:
                self._turn_timer = threading.Timer(self._turn_gap, self._flush_turn)
                self._turn_timer.daemon = True
                self._turn_timer.start()
        self.partial.emit(acumulado)
        if hay_pregunta:
            self._flush_turn()

    def _flush_turn(self):
        """Cierra la intervencion y decide si merece respuesta.

        Puerta 1: si no parece pregunta ni peticion, no se molesta a Claude. El
        texto NO se pierde: queda en el historial y sera contexto de la proxima
        respuesta. Y si la transcripcion se comio los signos y aqui no se vio la
        pregunta, queda el atajo de responder ahora.
        """
        with self._turn_lock:
            texto = " ".join(self._turn_parts).strip()
            self._turn_parts = []
            self._turn_timer = None
        if not texto or not self._running:
            return
        self._history.append(("Ellos", texto))
        self._registro.append(("Ellos", texto))
        self.transcript.emit("system", texto)
        self._last_heard = texto
        metricas.contar("intervenciones")
        if intent.parece_pregunta(texto, self._language):
            metricas.contar("con_pregunta")
            # Marca de tiempo para medir lo unico que notas de verdad: cuanto
            # tardas en tener algo que decir desde que te preguntan.
            self._t_pregunta = time.monotonic()
            self._queue.put({"type": "respond", "text": texto, "auto": True})
        else:
            metricas.contar("solo_contexto")
            self.status.emit("Sin pregunta todavia: guardado como contexto.")
            self.noAnswer.emit("no_question")

    def answer_now(self):
        """Responde a lo ultimo que dijeron aunque no pareciera una pregunta.

        Es la red de seguridad de la puerta 1: si preguntaron y la transcripcion
        no puso los signos, esto lo arregla sin esperar a nada.
        """
        if not self._running or self._test_mode:
            return
        with self._turn_lock:
            pendiente = " ".join(self._turn_parts).strip()
            self._turn_parts = []
            if self._turn_timer is not None:
                self._turn_timer.cancel()
                self._turn_timer = None
        texto = pendiente or self._last_heard
        if not texto:
            self.status.emit("Aun no hay nada que responder.")
            return
        if pendiente:
            # Estaban hablando ahora mismo: se cierra el turno aqui.
            self._history.append(("Ellos", texto))
            self.transcript.emit("system", texto)
            self._last_heard = texto
        self._queue.put({"type": "respond", "text": texto, "auto": False})

    def _cancel_turn_timer(self):
        with self._turn_lock:
            if self._turn_timer is not None:
                self._turn_timer.cancel()
                self._turn_timer = None
            self._turn_parts = []

    def _on_utterance(self, audio, source="system", reason="silence"):
        # Mantener la cola corta: si hay atraso, quedarse con lo mas reciente.
        while self._queue.qsize() > 2:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        self._queue.put({"type": "utterance", "audio": audio,
                         "source": source, "reason": reason})

    @staticmethod
    def _normalize(audio):
        """Lleva la frase a un nivel optimo para Whisper.

        Resuelve el audio flojo mucho mejor que la ganancia fija: se adapta a cada
        frase, no puede quedarse corta ni saturar.
        """
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        if peak < 1e-4:          # silencio: no amplificar ruido de fondo
            return audio
        return np.clip(audio * (0.95 / peak), -1.0, 1.0).astype(np.float32)

    def request_screenshots(self, images):
        """Envia una o varias capturas juntas (util si el enunciado no cabe en una)."""
        if self._running and images:
            self._queue.put({"type": "screenshot", "images": list(images)})

    def regenerate(self, note=""):
        """Rehace la respuesta a la ultima pregunta, opcionalmente guiada por una nota.

        Alimenta el boton Generate y el atajo Ctrl+Enter del overlay.
        """
        if not self._running or self._test_mode:
            return
        if not self._last_question:
            self.status.emit("Aun no hay ninguna pregunta que responder.")
            return
        self._queue.put({"type": "regen", "note": note or ""})

    def _process_loop(self, q, stop_event):
        while not stop_event.is_set():
            try:
                item = q.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is None or stop_event.is_set():
                break
            try:
                if item["type"] == "utterance":
                    source = item.get("source", "system")
                    reason = item.get("reason", "silence")
                    audio = item["audio"]
                    if self._auto_normalize:
                        audio = self._normalize(audio)
                    t0 = time.time()
                    text = self._transcriber.transcribe(audio)
                    stt_ms = int((time.time() - t0) * 1000)
                    if self._running:
                        self.sttLatency.emit(stt_ms)
                    if not text:
                        continue
                    self.transcript.emit(source, text)
                    if self._test_mode:
                        self.status.emit(f"Transcrito en {stt_ms} ms ({source}, {reason}).")
                        continue

                    # Tu voz: se guarda como contexto (para que Claude no te sugiera
                    # repetir lo que ya dijiste) pero NUNCA dispara una sugerencia.
                    if source == "mic":
                        self._history.append(("Yo", text))
                        continue

                    # En operacion normal solo respondemos a lo que dicen los demas.
                    if source == "system":
                        self._history.append(("Ellos", text))
                        self._last_heard = text
                        if reason == "silence":
                            # Hubo pausa: te cedieron el turno. Aun asi, solo se
                            # responde si pidieron algo (misma puerta 1 que en la
                            # nube); si no, queda de contexto.
                            if intent.parece_pregunta(text, self._language):
                                self._respond(text, images=None,
                                              permitir_silencio=True)
                            else:
                                self.status.emit(
                                    "Sin pregunta todavia: guardado como contexto.")
                                self.noAnswer.emit("no_question")
                        else:
                            # Monologo cortado por longitud: aun esta hablando.
                            # Se guarda como contexto pero no se responde todavia.
                            self.status.emit(
                                "Sigue hablando... (guardado como contexto)")
                elif item["type"] == "respond":
                    # Turno cerrado en la nube: ya se acumulo todo lo que dijeron.
                    # 'auto' distingue lo que dispara el filtro de lo que pides tu
                    # a mano: si lo pides tu, Claude no puede callarse.
                    self._respond(item["text"], images=None,
                                  permitir_silencio=item.get("auto", False))
                elif item["type"] == "screenshot":
                    self.status.emit("Analizando la pantalla...")
                    # Lo ultimo OIDO, no la ultima pregunta respondida: cuando
                    # comparten pantalla lo normal es decir "mira esto", que el
                    # filtro no toma por pregunta. Con _last_question se le
                    # emparejaba la captura a algo dicho hace rato, o a nada.
                    self._respond(self._last_heard or self._last_question
                                  or "(ver la pantalla)",
                                  images=item["images"])
                elif item["type"] == "regen":
                    self._respond(self._last_question, images=None,
                                  note=item.get("note", ""))
            except Exception as e:
                self.error.emit(str(e))

    def _calentar(self):
        coach = self._coach
        if coach is None:
            return
        ms = coach.calentar()
        if ms is not None:
            metricas.medir(LLM_CALENTAMIENTO, ms)
            if self._running:
                self.status.emit(f"Modelo listo ({ms / 1000:.1f} s de calentamiento).")

    def _contexto(self, con_captura, latest=None):
        """Transcripcion reciente, etiquetada por hablante.

        Con captura se manda mucho mas hilo: el pantallazo suele ser una parte
        del problema y el resto esta en lo que llevan rato contando. Se recorta
        por el final, que es lo que mas pesa en lo que estan preguntando ahora.
        """
        previas = list(self._history)
        # Lo que se responde ahora va aparte, en 'latest': si estuviera tambien
        # aqui, el modelo lo veria dos veces.
        if previas and latest is not None and previas[-1][1] == latest:
            previas = previas[:-1]
        cuantas = CONTEXTO_CAPTURA if con_captura else CONTEXTO_VOZ
        lineas = [f"{quien}: {texto}" for quien, texto in previas[-cuantas:]]
        if con_captura:
            recortado, total = [], 0
            for linea in reversed(lineas):
                if total + len(linea) > LIMITE_CHARS_CAPTURA:
                    break
                recortado.append(linea)
                total += len(linea)
            lineas = list(reversed(recortado))
        return "\n".join(lineas)

    def _respond(self, latest, images=None, note="", permitir_silencio=False):
        # Contexto etiquetado por hablante: Claude ve quien dijo cada cosa y sabe
        # que respondiste tu, evitando sugerirte que repitas.
        self._last_question = latest
        context = self._contexto(bool(images), latest)

        # Puerta 2: la respuesta puede empezar por el centinela, asi que no se
        # pinta nada hasta tener letras suficientes para descartarlo. Son once
        # caracteres: ni se nota, y evita que el panel parpadee con una respuesta
        # que va a desaparecer.
        estado = {"buffer": "", "abierto": False, "callado": False, "todo": ""}

        def abrir():
            estado["abierto"] = True
            if self._t_pregunta:
                ms = (time.monotonic() - self._t_pregunta) * 1000
                metricas.medir(E2E, ms)
                self._t_pregunta = 0.0
                self.e2eLatency.emit(int(ms))
            self.respStart.emit()
            self.respDelta.emit(estado["buffer"])

        def on_delta(txt):
            if estado["callado"]:
                return
            estado["todo"] += txt
            if estado["abierto"]:
                self.respDelta.emit(txt)
                return
            estado["buffer"] += txt
            limpio = estado["buffer"].lstrip()
            if len(limpio) < len(SENTINEL):
                return                      # todavia no se sabe que es
            if limpio.startswith(SENTINEL):
                estado["callado"] = True
                return
            abrir()

        def on_done():
            if estado["callado"]:
                self.status.emit("Sin pregunta todavia: guardado como contexto.")
                self.noAnswer.emit("model_declined")
                return
            if not estado["abierto"]:
                if not estado["buffer"].strip():
                    return                  # respuesta vacia: no hay nada que pintar
                abrir()                     # respuesta mas corta que el centinela
            # La sugerencia entregada pasa a ser contexto. No se transcribe tu
            # voz (seria un segundo stream), pero lo normal es que hayas dicho
            # algo parecido a esto, y con ello el modelo deja de repetirse y
            # puede continuar en vez de volver a empezar.
            resumen = _resumen(estado["todo"])
            if resumen:
                self._history.append(("Yo (sugerido)", resumen))
            # En el acta va la sugerencia ENTERA, con su codigo: es lo que luego
            # quieres releer para ver si la respuesta te sirvio de verdad.
            self._registro.append(("Sugerido", estado["todo"]))
            self.respDone.emit()

        self._coach.stream_response(
            context_text=context,
            latest=latest,
            images=images,
            note=note,
            on_delta=on_delta,
            on_done=on_done,
            on_error=self.error.emit,
            allow_silence=permitir_silencio,
        )

    def stop(self):
        """Para la sesion dejandolo TODO limpio para el siguiente arranque.

        El orden importa:
        1. Marcar parada (los emit dejan de tocar la UI).
        2. Parar el audio: deja de producir frases nuevas.
        3. Despertar y esperar al worker.
        4. Vaciar la cola: ni frases viejas ni centinelas pueden sobrevivir
           (era el bug: al reiniciar, el None mataba al worker nuevo y despues
           reaparecia la transcripcion de la sesion anterior).
        """
        if not self._running:
            return
        self._running = False
        if self._stop_event is not None:
            self._stop_event.set()

        # Primero el audio: deja de alimentar al transcriptor. Despues el stream,
        # que ademas cierra la conexion (se factura por tiempo conectado).
        if self._audio:
            self._audio.stop()
            self._audio = None

        self._cancel_turn_timer()
        if self._stt is not None:
            self._stt.stop()
            self._stt = None

        q = self._queue
        q.put(None)                      # desbloquea al worker si esta esperando
        if self._worker is not None:
            self._worker.join(timeout=3.0)
            self._worker = None

        while True:                      # vaciar restos
            try:
                q.get_nowait()
            except queue.Empty:
                break

        # Informe de la sesion: sirve para saber que tramo hay que mejorar.
        try:
            import config as cfg_mod
            ruta = metricas.guardar(cfg_mod.data_dir())
            self._guardar_acta(cfg_mod.data_dir())
            if ruta:
                self.status.emit(f"Métricas de la sesión guardadas en {ruta}")
        except Exception:
            pass

    def _guardar_acta(self, carpeta):
        """Deja la conversacion en un .md para poder repasarla despues.

        Sin esto, al terminar la reunion no queda ni rastro de lo que se dijo ni
        de lo que se sugirio, y no hay forma de revisar si las respuestas
        sirvieron o de afinar el prompt con casos reales.
        """
        if not self._registro:
            return
        try:
            destino = os.path.join(carpeta, "sesiones")
            os.makedirs(destino, exist_ok=True)
            ruta = os.path.join(destino,
                                f"sesion-{time.strftime('%Y%m%d-%H%M%S')}.md")
            with open(ruta, "w", encoding="utf-8") as f:
                f.write(f"# Reunion del {time.strftime('%d/%m/%Y %H:%M')}\n\n")
                for quien, texto in self._registro:
                    if quien == "Sugerido":
                        f.write(f"### Sugerido\n\n{texto.strip()}\n\n")
                    else:
                        f.write(f"**{quien}:** {texto.strip()}\n\n")
            return ruta
        except OSError:
            return None
