"""Motor de Meeting Coach: audio -> transcripcion -> modelo de respuestas (streaming).

Sin dependencias de interfaz: expone senales Qt y no sabe como se dibuja nada.

La transcripcion va en la nube (AssemblyAI): el audio de la reunion viaja
continuo y el texto vuelve palabra a palabra mientras la persona habla. El fin
de turno lo decide el propio modelo.

Tu micro va en un segundo stream: no dispara respuestas, pero dice cuando ya
contestaste (hilo.py), y con eso lo que anada el entrevistador mientras lees o
contestas queda como contexto en vez de abrir otra respuesta encima.
"""
import logging
import os
import time
import queue
import threading
from collections import deque

from PySide6 import QtCore

import followup
import hilo
import intent
from metrics import E2E, LLM_CALENTAMIENTO, STT_LATENCIA, metricas

log = logging.getLogger("armony.engine")

# Palabra con la que el modelo avisa de que no le han preguntado nada. Nunca
# llega a pintarse: se usa solo para decidir que no hay nada que sugerir.
SENTINEL = "NO_RESPONSE"

# La memoria de la reunion vive en la conversacion del coach (llm.Coach): todo
# lo que se oye se le va anotando y viaja, solo lo nuevo, en cada respuesta.
# Antes se mandaba una ventana con las ultimas ~18 intervenciones reconstruida
# en cada pregunta: se olvidaba lo anterior y nunca aprovechaba la cache.

# Lo que se le pasa como "ultimo turno" cuando mandas capturas y no hay ninguna
# pregunta hablada esperando. Se dice explicito para que no se ponga a rebuscar
# en la transcripcion algo a lo que responder: lo que importa esta en pantalla.
SIN_PREGUNTA_CAPTURA = ("(no han dicho nada nuevo desde la ultima respuesta: lo "
                        "que hay que resolver esta en las capturas)")


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
    respRevise = QtCore.Signal()          # reescribe en su sitio la ultima sugerencia
    respDelta = QtCore.Signal(str)
    respDone = QtCore.Signal()
    status = QtCore.Signal(str)
    error = QtCore.Signal(str)

    def __init__(self):
        super().__init__()
        self._running = False
        self._queue = queue.Queue()
        # Todo lo oido en la reunion, por quien lo dijo. Lo que viaja al modelo
        # lo lleva su conversacion (llm.Coach.anotar); esto es la copia local.
        self._history = []
        self._audio = None
        self._stt = None
        self._coach = None
        self._worker = None
        self._stop_event = None
        self._test_mode = False
        self._language = "es"
        self._last_question = ""      # ultima a la que SI se respondio
        self._last_heard = ""         # ultimo turno oido, se respondiera o no
        self._heard_respondido = False   # ...y si ese turno ya se contesto
        self._t_pregunta = 0.0        # cuando se cerro la pregunta (para el e2e)
        self._registro = []           # acta de la reunion, para repasarla luego

        # Agrupacion de turnos. AssemblyAI cierra un turno por
        # cada frase, asi que un "¿Como vais? ¿Llegamos el viernes?" llega en dos
        # trozos. Responder a cada uno seria atropellado: se acumulan y solo se
        # llama al modelo cuando pasa _turn_gap sin que nadie hable.
        self._turn_lock = threading.Lock()
        self._turn_parts = []
        self._turn_timer = None
        self._turn_gap = 0.7

        # La pregunta en curso y tu micro (ver hilo.py).
        self._clock = time.monotonic
        self._hilo_lock = threading.Lock()
        self._hilo = None
        self._stt_mic = None
        self._listen_mic = True
        self._recientes_ellos = deque(maxlen=6)   # (instante, texto) para el eco
        self._eco_avisado = False
        # Arbitro de anadidos (Jev). Sin clave, la regla fija de hilo.py.
        self._arbitro = None
        self._arbitrar_en_hilo = True    # las pruebas lo apagan para ir en linea
        self._generando = False

    @property
    def running(self):
        """True while a session is active; False again after a failed start."""
        return self._running

    def _init_failed(self, msg):
        """Start-up failed: mark the session stopped, release the transcription
        streams if they were already opened (billed per connected second), report."""
        # msg is a fixed UI string plus a library exception message; no config
        # values or keys.
        log.error("Engine start-up failed: %s", msg)
        self._running = False
        for nombre in ("_stt", "_stt_mic"):
            stt = getattr(self, nombre)
            if stt is not None:
                stt.stop()
                setattr(self, nombre, None)
        self.error.emit(msg)

    def start(self, cfg, test_mode=False):
        """test_mode: solo audio + transcripcion (sin llamar al modelo de respuestas)."""
        if self._running:
            return
        # Cola NUEVA en cada arranque: nada de la sesion anterior puede colarse.
        # (Antes quedaban frases viejas y el centinela None, que mataba al worker.)
        self._queue = queue.Queue()
        self._stop_event = threading.Event()
        self._history.clear()
        self._last_question = ""
        self._last_heard = ""
        self._heard_respondido = False
        self._language = cfg.get("language", "es")
        self._running = True
        self._test_mode = test_mode
        self._turn_gap = float(cfg.get("silence_hang", 0.7))
        self._turn_parts = []
        self._t_pregunta = 0.0
        self._registro = []
        self._hilo = None
        self._recientes_ellos.clear()
        self._eco_avisado = False
        self._listen_mic = bool(cfg.get("listen_mic", True))

        metricas.iniciar()
        metricas.nota("proveedor: openai")
        metricas.nota(f"transcripcion: {cfg.get('assemblyai_model')}")
        metricas.nota(f"modelo: {cfg.get('openai_model')} · esfuerzo voz "
                      f"{cfg.get('openai_effort_voice')} · capturas "
                      f"{cfg.get('openai_effort_vision')}")
        # La inicializacion (conectar, preparar el coach) puede tardar: en un hilo.
        threading.Thread(target=self._init_and_run, args=(cfg,), daemon=True).start()

    def _init_and_run(self, cfg):
        # Importes tardios para que la ventana abra rapido.
        from llm import Coach
        from audio import AudioEngine
        from stt_stream import StreamingSTT

        if not cfg.get("assemblyai_api_key"):
            self._init_failed("Falta la API key de AssemblyAI. Ponla en Ajustes.")
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
        if self._listen_mic:
            # Segundo stream, el de tu voz: misma clave e idioma, sin estados en
            # la barra (ya los da el de la reunion) y con sus errores marcados.
            self._stt_mic = StreamingSTT(
                api_key=cfg["assemblyai_api_key"],
                on_final=self._on_mic_final,
                on_error=lambda m: self._running and self.error.emit(f"Micro: {m}"),
                language=cfg.get("language", "es"),
                model=cfg.get("assemblyai_model", "universal-3-5-pro"),
                end_of_turn_threshold=cfg.get("end_of_turn_threshold", 0.4),
            )
            self._stt_mic.start()
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
                # Un modelo; las preguntas habladas razonan poco y las
                # capturas mas.
                self._coach = Coach(
                    api_key=cfg["openai_api_key"],
                    system_prompt=sys_prompt,
                    model=cfg["openai_model"],
                    tokens_voice=int(cfg["openai_tokens_voice"]),
                    tokens_vision=int(cfg["openai_tokens_vision"]),
                    effort_voice=cfg.get("openai_effort_voice", "low"),
                    effort_vision=cfg.get("openai_effort_vision", "medium"),
                    # Una clave por reunion: el gasto en cache se ve por sesion.
                    cache_key=f"armony-{time.strftime('%Y%m%d-%H%M%S')}",
                )
            except Exception as e:
                self._init_failed(f"No se pudo iniciar el modelo de respuestas: {e}")
                return

            # Calentar la conexion mientras te acomodas: la primera peticion
            # paga DNS, TLS y el procesado inicial del prompt con tus contextos.
            # Va en su hilo para no retrasar el arranque de la reunion.
            threading.Thread(target=self._calentar, daemon=True).start()

            if cfg.get("typesafe_api_key"):
                try:
                    from typesafe_sdk import RetryPolicy, TypeSafeClient
                    # Sin reintentos y con tope de 1 s: si Jev tarda, el anadido
                    # se queda como contexto, que es lo seguro.
                    self._arbitro = TypeSafeClient(
                        api_key=cfg["typesafe_api_key"], model="jev-1.14.0",
                        timeout=1.0, retry=RetryPolicy(max_retries=0))
                except Exception as e:
                    self.status.emit(f"Arbitro de anadidos desactivado: {e}")

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
            on_status=lambda m: self._running and self.status.emit(m),
            # La reunion y, si esta activado, tu micro: cada uno a su stream.
            on_system_pcm=self._stt.feed,
            on_mic_pcm=self._stt_mic.feed if self._stt_mic is not None else None,
            gain_system=cfg.get("gain_system", 1.0),
            gain_mic=cfg.get("gain_mic", 1.0),
        )
        self._audio.start()
        if self._test_mode:
            self.status.emit(
                "MODO PRUEBA: transcribe la reunion en vivo. No se generan respuestas.")
        else:
            self.status.emit("Escuchando la reunion. Habla y aparecera la sugerencia.")

    # ---------------------------------------------------------- transcripcion
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
        self._recientes_ellos.append((self._clock(), texto))
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

        Puerta 1: si no parece pregunta ni peticion, no se molesta al modelo. El
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
        self._record("Ellos", texto)
        self.transcript.emit("system", texto)
        self._anotar_oido(texto)
        metricas.contar("intervenciones")
        es_pregunta = intent.parece_pregunta(texto, self._language)
        # Puerta 0: si hay una pregunta abierta, lo que anadan se juzga segun en
        # que punto va (hilo.py). Con Jev, el juicio fino (followup.py); sin el,
        # la regla fija: contexto mientras lees o contestas.
        ahora = self._clock()
        with self._hilo_lock:
            actual = self._hilo
            estado = actual.estado(ahora) if actual is not None else None
            datos = None
            if actual is not None and self._arbitro is not None:
                datos = (actual, estado, actual.partes[0], actual.respuesta,
                         list(actual.dijo_tester))
            else:
                accion = hilo.decidir(actual, es_pregunta, ahora)
                if accion == "nueva":
                    self._hilo = hilo.HiloPregunta(texto, ahora)
            if actual is not None and (datos is not None or accion != "nueva"):
                actual.entrevistador(texto, ahora)
        if datos is not None:
            if self._arbitrar_en_hilo:
                threading.Thread(target=self._arbitrar, args=(texto, es_pregunta, datos),
                                 daemon=True).start()
            else:
                self._arbitrar(texto, es_pregunta, datos)
            return
        self._aplicar(accion, texto, es_pregunta)

    def _arbitrar(self, texto, es_pregunta, datos):
        """Jev juzga el anadido (~150 ms) y la regla de followup decide."""
        hilo_actual, estado, pregunta, respuesta, dijo_tester = datos
        try:
            juicio = followup.juzgar(self._arbitro, pregunta, respuesta,
                                     dijo_tester, texto)
            decision = followup.decidir(juicio, estado)
            metricas.medir("jev_ms", juicio.ms)
            metricas.contar(f"jev_{decision}")
        except Exception:
            # Jev no respondio a tiempo: la regla fija, que nunca reescribe.
            metricas.contar("jev_fallos")
            decision = (followup.NUEVA if es_pregunta and estado == hilo.RESPONDIDA
                        else followup.MANTENER)
        if not self._running:
            return
        if decision == followup.NUEVA:
            with self._hilo_lock:
                if self._hilo is not hilo_actual:
                    return               # mientras tanto ya se abrio otra
                self._hilo = hilo.HiloPregunta(texto, self._clock())
            self._aplicar("nueva", texto, es_pregunta)
        elif decision == followup.REVISAR:
            with self._hilo_lock:
                vale = self._hilo is hilo_actual and hilo_actual.revisiones == 0
                if vale:
                    hilo_actual.revisiones += 1
            if not vale:
                self._aplicar("contexto", texto, es_pregunta)
                return
            metricas.contar("revisiones")
            if self._generando and self._coach is not None:
                self._coach.cancelar()   # la respuesta en curso ya no vale
            self.status.emit("Lo que añadieron cambia la respuesta: actualizándola.")
            self._queue.put({"type": "revise", "text": texto})
        else:
            if decision == followup.RETIRAR:
                metricas.contar("preguntas_retiradas")
            self._aplicar("contexto", texto, es_pregunta)

    def _aplicar(self, accion, texto, es_pregunta):
        """Lo que se ve de una decision: responder o dejarlo como contexto."""
        if accion == "nueva":
            metricas.contar("con_pregunta")
            # Marca de tiempo para medir lo unico que notas de verdad: cuanto
            # tardas en tener algo que decir desde que te preguntan.
            self._t_pregunta = time.monotonic()
            self._queue.put({"type": "respond", "text": texto, "auto": True})
        elif es_pregunta:
            metricas.contar("anadidos_contexto")
            self.status.emit("Añadido a la pregunta en curso: guardado como contexto.")
            self.noAnswer.emit("follow_up")
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
            self._record("Ellos", texto)
            self.transcript.emit("system", texto)
            self._anotar_oido(texto)
        # Pedirla a mano manda: es una pregunta nueva aunque hubiera otra abierta.
        with self._hilo_lock:
            self._hilo = hilo.HiloPregunta(texto, self._clock())
        self._queue.put({"type": "respond", "text": texto, "auto": False})

    def _on_mic_final(self, texto, latencia_ms=0):
        """Lo que dijiste tu, por tu micro. Nunca dispara una respuesta: es
        contexto (para no sugerirte repetir lo que ya dijiste) y la senal de que
        la pregunta en curso ya la estas contestando."""
        if not self._running or not texto:
            return
        ahora = self._clock()
        if hilo.es_eco(texto, list(self._recientes_ellos), ahora):
            metricas.contar("eco_micro")
            if not self._eco_avisado:
                self._eco_avisado = True
                self.status.emit("Tu micro capta los altavoces: usa auriculares "
                                 "para que no se confunda tu voz con la reunion.")
            return
        metricas.contar("intervenciones_tuyas")
        self._record("Yo", texto)
        with self._hilo_lock:
            if self._hilo is not None:
                self._hilo.tester(texto, ahora)

    def _record(self, quien, texto):
        """Close a spoken turn. Model context (_history and the coach
        conversation, where it travels with the next answer) and the saved
        transcript (_registro) must always receive the same turns."""
        self._history.append((quien, texto))
        self._registro.append((quien, texto))
        if self._coach is not None:
            self._coach.anotar(quien, texto)

    def _anotar_oido(self, texto):
        """Guarda el ultimo turno oido y lo marca como pendiente de respuesta."""
        self._last_heard = texto
        self._heard_respondido = False

    def _cancel_turn_timer(self):
        with self._turn_lock:
            if self._turn_timer is not None:
                self._turn_timer.cancel()
                self._turn_timer = None
            self._turn_parts = []

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
                if item["type"] == "respond":
                    # Turno cerrado: ya se acumulo todo lo que dijeron.
                    # 'auto' distingue lo que dispara el filtro de lo que pides tu
                    # a mano: si lo pides tu, el modelo no puede callarse.
                    self._respond(item["text"], images=None,
                                  permitir_silencio=item.get("auto", False))
                elif item["type"] == "screenshot":
                    self._responder_capturas(item["images"])
                elif item["type"] == "regen":
                    self._respond(self._last_question, images=None,
                                  note=item.get("note", ""))
                elif item["type"] == "revise":
                    # Anadido que cambia la respuesta: se reescribe en su sitio.
                    self._respond(item["text"], images=None, revision=True)
            except Exception as e:
                log.exception("Worker failed on a %r item",
                              item.get("type") if isinstance(item, dict) else None)
                self.error.emit(str(e))

    def _responder_capturas(self, images):
        """Responde a unas capturas, decidiendo que turno hablado las acompaña.

        Se les empareja lo ultimo OIDO, no la ultima pregunta respondida: al
        compartir pantalla lo normal es decir "mira esto", que el filtro no toma
        por pregunta, y con _last_question se emparejaba con algo de hace rato.

        Pero solo si ese turno sigue sin contestar. Si ya se respondio y despues
        no ha hablado nadie, arrastrarlo hacia que el modelo volviera a contestar
        la misma pregunta hablada en vez de mirar la pantalla.
        """
        self.status.emit("Analizando la pantalla...")
        pendiente = "" if self._heard_respondido else self._last_heard
        self._respond(pendiente or SIN_PREGUNTA_CAPTURA, images=images)

    def _calentar(self):
        coach = self._coach
        if coach is None:
            return
        ms = coach.calentar()
        if ms is not None:
            metricas.medir(LLM_CALENTAMIENTO, ms)
            if self._running:
                self.status.emit(f"Modelo listo ({ms / 1000:.1f} s de calentamiento).")

    def _respond(self, latest, images=None, note="", permitir_silencio=False,
                 revision=False):
        # El contexto ya lo lleva la conversacion del coach (todo lo oido,
        # etiquetado por quien lo dijo, y las sugerencias anteriores).
        if not revision:
            self._last_question = latest
        # Ese turno queda saldado: si luego llegan capturas, no se le vuelven a
        # emparejar (ver la rama de 'screenshot' en el bucle).
        if latest and latest == self._last_heard:
            self._heard_respondido = True

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
            (self.respRevise if revision else self.respStart).emit()
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

        # Una revision que falla deja en pantalla la respuesta anterior, que
        # sigue valiendo: su pregunta no se cierra.
        def sin_respuesta():
            if not revision:
                self._cerrar_hilo()

        def on_error(mensaje):
            if not estado["abierto"]:
                sin_respuesta()             # fallo antes de pintar nada
            self.error.emit(mensaje)

        def on_done():
            if estado["callado"]:
                # No habia pregunta: nada en pantalla, asi que tampoco puede
                # quedar una pregunta abierta bloqueando la siguiente.
                sin_respuesta()
                self.status.emit("Sin pregunta todavia: guardado como contexto.")
                self.noAnswer.emit("model_declined")
                return
            if not estado["abierto"]:
                if not estado["buffer"].strip():
                    sin_respuesta()
                    return                  # respuesta vacia: no hay nada que pintar
                abrir()                     # respuesta mas corta que el centinela
            # La sugerencia ya queda en la conversacion del coach: el modelo la
            # da por dicha y continua desde ahi en vez de repetirse. Y en el
            # hilo, para que el arbitro sepa que se le sugirio.
            with self._hilo_lock:
                if self._hilo is not None:
                    self._hilo.respuesta = estado["todo"]
            # En el acta va la sugerencia ENTERA, con su codigo: es lo que luego
            # quieres releer para ver si la respuesta te sirvio de verdad.
            self._registro.append(("Sugerido (revisada)" if revision else "Sugerido",
                                   estado["todo"]))
            self.respDone.emit()

        self._generando = True
        try:
            self._coach.stream_response(
                latest=latest,
                images=images,
                note=note,
                on_delta=on_delta,
                on_done=on_done,
                on_error=on_error,
                allow_silence=permitir_silencio,
                revision=revision,
            )
        finally:
            self._generando = False

    def _cerrar_hilo(self):
        """La pregunta abierta no llego a tener respuesta en pantalla."""
        with self._hilo_lock:
            self._hilo = None

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
        if self._stt_mic is not None:
            self._stt_mic.stop()
            self._stt_mic = None

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
            log.exception("Saving session metrics or transcript failed")

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
                    if quien.startswith("Sugerido"):
                        f.write(f"### {quien}\n\n{texto.strip()}\n\n")
                    else:
                        f.write(f"**{quien}:** {texto.strip()}\n\n")
            return ruta
        except OSError:
            log.warning("Session transcript not written under %s", carpeta,
                        exc_info=True)
            return None
