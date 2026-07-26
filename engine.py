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
import time
import queue
import threading
from collections import deque

import numpy as np
from PySide6 import QtCore


class CoachEngine(QtCore.QObject):
    sysLevel = QtCore.Signal(int)
    micLevel = QtCore.Signal(int)
    sttLatency = QtCore.Signal(int)       # ms que tardo la ultima transcripcion
    transcript = QtCore.Signal(str, str)  # (fuente, texto): fuente = 'system' | 'mic'
    partial = QtCore.Signal(str)          # texto provisional, se repinta en vivo
    respStart = QtCore.Signal()
    respDelta = QtCore.Signal(str)
    respDone = QtCore.Signal()
    status = QtCore.Signal(str)
    error = QtCore.Signal(str)

    def __init__(self):
        super().__init__()
        self._running = False
        self._queue = queue.Queue()
        self._history = deque(maxlen=8)
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
        self._last_question = ""

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
        self._running = True
        self._test_mode = test_mode
        self._offline = bool(cfg.get("offline_mode", False))
        self._auto_normalize = bool(cfg.get("auto_normalize", True))
        self._transcribe_mic = bool(cfg.get("transcribe_mic", True))
        self._turn_gap = float(cfg.get("silence_hang", 0.7))
        self._turn_parts = []
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
                # Opcion B: el idioma de la reunion elige el prompt del coach y
                # filtra los contextos. Se congela AQUI para no romper el cache.
                import contexts as ctx_mod
                lang = cfg.get("language", "es")
                plang = lang if lang in ("es", "en") else "es"   # 'auto' -> es para el prompt
                base = cfg.get(f"system_prompt_{plang}") or cfg.get("system_prompt", "")
                extra = ctx_mod.active_text(lang)
                sys_prompt = base + (
                    "\n\n# Contexto de esta reunion\n" + extra if extra else "")
                self._coach = Coach(
                    api_key=cfg["anthropic_api_key"],
                    model=cfg["llm_model"],
                    system_prompt=sys_prompt,
                    max_tokens=int(cfg.get("max_tokens", 400)),
                )
            except Exception as e:
                self.error.emit(f"No se pudo iniciar Claude: {e}")
                self._running = False
                return

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
        self.sttLatency.emit(latencia_ms)
        if self._test_mode:
            self.transcript.emit("system", texto)
            self.status.emit(f"Transcrito en {latencia_ms} ms (reunion).")
            return
        with self._turn_lock:
            self._turn_parts.append(texto)
            acumulado = " ".join(self._turn_parts)
            if self._turn_timer is not None:
                self._turn_timer.cancel()
            self._turn_timer = threading.Timer(self._turn_gap, self._flush_turn)
            self._turn_timer.daemon = True
            self._turn_timer.start()
        self.partial.emit(acumulado)

    def _flush_turn(self):
        """Se cumplio la pausa: lo dicho hasta aqui es una intervencion completa."""
        with self._turn_lock:
            texto = " ".join(self._turn_parts).strip()
            self._turn_parts = []
            self._turn_timer = None
        if texto and self._running:
            self._history.append(("Ellos", texto))
            self.transcript.emit("system", texto)
            self._queue.put({"type": "respond", "text": texto})

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
                        if reason == "silence":
                            # Hubo pausa: te cedieron el turno -> sugerir respuesta.
                            self._respond(text, images=None)
                        else:
                            # Monologo cortado por longitud: aun esta hablando.
                            # Se guarda como contexto pero no se responde todavia.
                            self.status.emit(
                                "Sigue hablando... (guardado como contexto)")
                elif item["type"] == "respond":
                    # Turno cerrado en la nube: ya se acumulo todo lo que dijeron.
                    self._respond(item["text"], images=None)
                elif item["type"] == "screenshot":
                    self.status.emit("Analizando la pantalla...")
                    self._respond(self._last_question or "(ver la pantalla)",
                                  images=item["images"])
                elif item["type"] == "regen":
                    self._respond(self._last_question, images=None,
                                  note=item.get("note", ""))
            except Exception as e:
                self.error.emit(str(e))

    def _respond(self, latest, images=None, note=""):
        # Contexto etiquetado por hablante: Claude ve quien dijo cada cosa y sabe
        # que respondiste tu, evitando sugerirte que repitas.
        self._last_question = latest
        previas = list(self._history)[:-1] if len(self._history) > 1 else []
        context = "\n".join(f"{quien}: {texto}" for quien, texto in previas)
        self.respStart.emit()
        self._coach.stream_response(
            context_text=context,
            latest=latest,
            images=images,
            note=note,
            on_delta=self.respDelta.emit,
            on_done=self.respDone.emit,
            on_error=self.error.emit,
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
