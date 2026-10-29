"""Transcripcion en vivo con AssemblyAI (Universal Streaming v3).

El audio viaja continuo por un WebSocket y las palabras van llegando mientras se
habla, sin esperar a que la persona termine.

Dos tipos de resultado:
    parcial (end_of_turn=false) -> texto provisional, se repinta en vivo
    final   (end_of_turn=true)  -> turno cerrado; AssemblyAI decidio que la
                                   persona termino de hablar

Ese "final" es el que dispara la sugerencia del coach. El fin de turno lo decide
un modelo entrenado para eso y no un umbral de energia, asi que aguanta mucho
mejor las pausas al pensar.

Detalles del protocolo que condicionan el codigo:
  - audio PCM 16 bits mono, sin cabecera, en trozos de 50 a 1000 ms
  - se factura por duracion de la conexion, no por audio enviado -> se conecta
    al empezar la reunion y se cierra al terminarla
  - la sesion caduca a las 3 horas -> hay reconexion automatica
"""
import json
import logging
import queue
import threading
import time
import urllib.parse

import numpy as np

from metrics import STT_CONEXION, metricas

try:
    import websocket          # websocket-client
except ImportError as e:      # pragma: no cover
    raise ImportError(
        "Falta websocket-client. Instala con: pip install websocket-client"
    ) from e

log = logging.getLogger("armony.stt_stream")

ENDPOINT = "wss://streaming.assemblyai.com/v3/ws"
SAMPLE_RATE = 16000
MODEL = "universal-3-5-pro"

# AssemblyAI pide entre 50 y 1000 ms por mensaje. Los bloques que produce
# audio.py son de ~21 ms, asi que se acumulan hasta llegar a 50.
CHUNK_MS = 50
CHUNK_SAMPLES = SAMPLE_RATE * CHUNK_MS // 1000

_RECONNECT_WAIT = (1.0, 2.0, 5.0, 10.0)     # espera entre reintentos


def _language_codes(language):
    """Traduce el ajuste de la app al parametro de la API.

    'auto' se manda sin idioma: el modelo detecta solo y admite cambio de idioma
    a mitad de frase, que es justo lo que pasa en reuniones mixtas.
    """
    if language in ("es", "en"):
        return language
    return None


class StreamingSTT:
    """Cliente de streaming: se le da audio y devuelve texto parcial y final."""

    def __init__(self, api_key, on_partial=None, on_final=None,
                 on_status=None, on_error=None, language="es",
                 model=MODEL, end_of_turn_threshold=0.4):
        self._api_key = api_key
        self._on_partial = on_partial or (lambda t: None)
        self._on_final = on_final or (lambda t, ms: None)
        self._on_status = on_status or (lambda m: None)
        self._on_error = on_error or (lambda m: None)
        self._language = language
        self._model = model
        self._eot_threshold = float(end_of_turn_threshold)

        self._ws = None
        self._send_lock = threading.Lock()
        self._audio_q = queue.Queue(maxsize=200)   # ~10 s; si se llena, se tira lo viejo
        self._pending = np.zeros(0, dtype=np.int16)
        self._running = False
        self._connected = threading.Event()
        self._threads = []
        # Para medir el retardo hace falta saber CUANTO audio se ha mandado y
        # cuando: los tiempos de las palabras que devuelve AssemblyAI van sobre
        # el audio recibido, no sobre el reloj.
        self._audio_ms = 0.0
        self._t_ultimo_envio = 0.0
        self._last_partial = ""

    # -- URL -----------------------------------------------------------------
    def _url(self):
        params = {
            "speech_model": self._model,
            "sample_rate": SAMPLE_RATE,
            "encoding": "pcm_s16le",
            "format_turns": "true",          # puntuacion y mayusculas en los finales
            "end_of_turn_confidence_threshold": self._eot_threshold,
        }
        lang = _language_codes(self._language)
        if lang:
            params["language_codes"] = lang
        return ENDPOINT + "?" + urllib.parse.urlencode(params)

    # -- ciclo de vida -------------------------------------------------------
    def start(self):
        if self._running:
            return
        self._running = True
        t = threading.Thread(target=self._run, name="stt-ws", daemon=True)
        t.start()
        self._threads = [t]

    def stop(self):
        self._running = False
        self._connected.clear()
        ws = self._ws
        if ws is not None:
            try:
                # Terminate cierra el turno en curso y da por acabada la sesion.
                with self._send_lock:
                    ws.send(json.dumps({"type": "Terminate"}))
            except Exception:
                log.debug("Sending Terminate failed", exc_info=True)
            try:
                ws.close()
            except Exception:
                log.debug("Closing the WebSocket failed", exc_info=True)
        for t in self._threads:
            t.join(timeout=2.0)
        self._threads = []
        self._ws = None

    @property
    def connected(self):
        return self._connected.is_set()

    # -- entrada de audio ----------------------------------------------------
    def feed(self, block_f32):
        """Recibe audio mono float32 a 16 kHz (lo que ya produce audio.py).

        Se llama desde el hilo de captura: no puede bloquear ni tardar.
        """
        if not self._running:
            return
        pcm = np.clip(block_f32, -1.0, 1.0)
        pcm = (pcm * 32767.0).astype(np.int16)
        self._pending = np.concatenate([self._pending, pcm])
        while self._pending.size >= CHUNK_SAMPLES:
            trozo = self._pending[:CHUNK_SAMPLES]
            self._pending = self._pending[CHUNK_SAMPLES:]
            try:
                self._audio_q.put_nowait(trozo.tobytes())
            except queue.Full:
                # Preferimos perder lo viejo: en una reunion importa lo ultimo.
                try:
                    self._audio_q.get_nowait()
                    self._audio_q.put_nowait(trozo.tobytes())
                except queue.Empty:
                    pass

    # -- hilos ---------------------------------------------------------------
    def _run(self):
        intento = 0
        while self._running:
            try:
                self._conectar_y_escuchar()
                intento = 0                      # la conexion vivio: contador a cero
            except websocket.WebSocketBadStatusException as e:
                # El servidor rechazo el handshake. Si es de credenciales no tiene
                # sentido reintentar: seguiria fallando igual y llenando la UI de
                # avisos. Se para y se dice que hacer.
                codigo = getattr(e, "status_code", None)
                log.warning("AssemblyAI handshake rejected: status=%s (%s)",
                            codigo, type(e).__name__)
                if codigo in (400, 401, 402, 403):
                    self._running = False
                    self._on_error(
                        "AssemblyAI rechazo la conexion (codigo "
                        f"{codigo}): revisa la API key o el saldo de tu cuenta.")
                    break
                if not self._running:
                    break
                self._on_error(f"Transcripcion en vivo: {e}")
            except Exception as e:
                if not self._running:
                    break
                log.warning("Transcription stream dropped: %s: %s",
                            type(e).__name__, e)
                self._on_error(f"Transcripcion en vivo: {e}")
            if not self._running:
                break
            # Se llega aqui si la sesion cayo (corte de red o las 3 h de limite).
            espera = _RECONNECT_WAIT[min(intento, len(_RECONNECT_WAIT) - 1)]
            intento += 1
            metricas.contar("reconexiones_stt")
            self._on_status(f"Reconectando la transcripcion en {espera:.0f} s...")
            fin = time.monotonic() + espera
            while self._running and time.monotonic() < fin:
                time.sleep(0.1)

    def _conectar_y_escuchar(self):
        t0 = time.monotonic()
        ws = websocket.create_connection(
            self._url(),
            header=[f"Authorization: {self._api_key}"],
            timeout=10,
        )
        metricas.medir(STT_CONEXION, (time.monotonic() - t0) * 1000)
        self._ws = ws
        ws.settimeout(None)
        self._connected.set()
        # Sesion nueva: el reloj de audio del servidor vuelve a cero.
        self._audio_ms = 0.0
        self._t_ultimo_envio = time.monotonic()

        emisor = threading.Thread(target=self._enviar_audio, args=(ws,),
                                  name="stt-send", daemon=True)
        emisor.start()
        try:
            while self._running:
                msg = ws.recv()
                if not msg:
                    break
                if isinstance(msg, bytes):
                    continue
                self._procesar(json.loads(msg))
        finally:
            self._connected.clear()
            try:
                ws.close()
            except Exception:
                log.debug("Closing the WebSocket failed", exc_info=True)
            emisor.join(timeout=1.0)

    def _enviar_audio(self, ws):
        while self._running and self._connected.is_set():
            try:
                datos = self._audio_q.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                with self._send_lock:
                    ws.send_binary(datos)
                self._audio_ms += CHUNK_MS
                self._t_ultimo_envio = time.monotonic()
            except Exception as e:
                # la conexion cayo: el hilo lector lo gestiona. After stop()
                # the socket is closed on purpose: not worth a warning.
                log.log(logging.WARNING if self._running else logging.DEBUG,
                        "Audio send failed after %.0f ms of audio: %s: %s",
                        self._audio_ms, type(e).__name__, e)
                break

    # -- mensajes del servidor ----------------------------------------------
    def _procesar(self, msg):
        tipo = msg.get("type")
        if tipo == "Begin":
            self._on_status("Transcripcion en vivo conectada.")
        elif tipo == "Turn":
            texto = (msg.get("transcript") or "").strip()
            if msg.get("end_of_turn"):
                # Con format_turns el final llega dos veces: primero sin formato
                # y despues puntuado. Nos quedamos con el puntuado.
                if not msg.get("turn_is_formatted", False):
                    return
                self._last_partial = ""
                if texto:
                    metricas.contar("frases_finales")
                    self._on_final(texto, self._latencia_ms(msg))
            elif texto and texto != self._last_partial:
                self._last_partial = texto
                metricas.contar("parciales")
                self._on_partial(texto)
        elif tipo == "Termination":
            self._on_status("Sesion de transcripcion terminada.")
        elif tipo == "Error":
            # El servidor acepta el handshake y solo despues avisa de que la key
            # no vale, asi que el fallo de credenciales se detecta aqui, no al
            # conectar. Reintentar con la misma key no arreglaria nada.
            codigo = msg.get("error_code")
            detalle = msg.get("error") or "error desconocido"
            log.warning("AssemblyAI server error: code=%s detail=%s", codigo, detalle)
            if codigo == 1008 or "api key" in detalle.lower():
                self._running = False
                self._on_error(
                    f"AssemblyAI rechazo la conexion: {detalle}. Revisa la API "
                    "key en Ajustes.")
            else:
                self._on_error(f"Transcripcion en vivo: {detalle}")

    def _latencia_ms(self, msg):
        """Cuanto tardo el texto desde que se dijo la ultima palabra.

        Ojo con el reloj: los tiempos de las palabras van sobre el AUDIO
        recibido, no sobre la hora. Restarlos del reloj desde que se conecto
        contaba como retardo todo el rato en que nadie hablaba -- en una reunion
        de verdad eso son segundos, y por eso salian cifras absurdas.

        Se calcula sobre el audio: del ultimo trozo enviado se sabe la hora, y
        cuanto audio se habia mandado ya; de ahi sale la hora en que se mando el
        audio donde acaba la ultima palabra.
        """
        palabras = msg.get("words") or []
        if not palabras:
            return 0
        fin_ultima = palabras[-1].get("end")
        if fin_ultima is None or not self._t_ultimo_envio:
            return 0
        # audio mandado despues de esa palabra (lo que se dijo tras callarse)
        cola = self._audio_ms - fin_ultima
        desde_el_ultimo_envio = (time.monotonic() - self._t_ultimo_envio) * 1000.0
        return max(0, int(desde_el_ultimo_envio + cola))
