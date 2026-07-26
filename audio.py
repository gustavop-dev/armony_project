"""Captura de audio en Windows via WASAPI.

- Loopback (salida del sistema = lo que dicen los demas en la reunion): se transcribe.
- Microfono (tu voz): solo se usa para el medidor de nivel (verificar que se escucha).

Cada fuente corre en su propio hilo, calcula el nivel RMS (para las barras) y, en el caso
del loopback, segmenta el audio en "frases" por silencio para mandarlas al transcriptor.
"""
import time
import threading
import numpy as np
import soxr

try:
    import pyaudiowpatch as pyaudio
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "Falta PyAudioWPatch. Instala con: pip install PyAudioWPatch"
    ) from e

TARGET_RATE = 16000     # Whisper trabaja a 16 kHz mono
CHUNK = 1024            # frames por lectura


def _pick_loopback_device(p):
    """Encuentra el dispositivo de loopback WASAPI de los parlantes por defecto."""
    wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
    default_out = p.get_device_info_by_index(wasapi["defaultOutputDevice"])
    if default_out.get("isLoopbackDevice"):
        return default_out
    for lb in p.get_loopback_device_info_generator():
        if default_out["name"] in lb["name"]:
            return lb
    # ultimo recurso: el primer loopback disponible
    for lb in p.get_loopback_device_info_generator():
        return lb
    raise RuntimeError("No se encontro un dispositivo de loopback WASAPI.")


def _pick_input_device(p):
    """Microfono por defecto."""
    try:
        return p.get_default_input_device_info()
    except Exception:
        wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
        return p.get_device_info_by_index(wasapi["defaultInputDevice"])


class _Segmenter:
    """Detecta 'frases' por energia + silencio sobre audio 16k mono float32."""

    def __init__(self, on_utterance,
                 speech_thresh=0.012, silence_hang=0.6,
                 min_speech=0.4, max_utt=14.0, preroll=0.3):
        self.on_utterance = on_utterance
        self.speech_thresh = speech_thresh
        self.silence_hang = silence_hang
        self.min_speech = min_speech
        self.max_utt = max_utt
        self.preroll_samples = int(preroll * TARGET_RATE)

        self._in_speech = False
        self._buf = []
        self._speech_samples = 0
        self._silence_samples = 0
        self._preroll = np.zeros(0, dtype=np.float32)

    def process(self, block):
        rms = float(np.sqrt(np.mean(block ** 2))) if block.size else 0.0
        is_speech = rms > self.speech_thresh

        if not self._in_speech:
            # mantener un pequeno pre-roll para no cortar el inicio de la frase
            self._preroll = np.concatenate([self._preroll, block])[-self.preroll_samples:]
            if is_speech:
                self._in_speech = True
                self._buf = [self._preroll.copy()]
                self._speech_samples = block.size
                self._silence_samples = 0
                self._preroll = np.zeros(0, dtype=np.float32)
            return

        # ya estamos dentro de una frase
        self._buf.append(block)
        if is_speech:
            self._speech_samples += block.size
            self._silence_samples = 0
        else:
            self._silence_samples += block.size

        total = sum(b.size for b in self._buf)
        end_by_silence = self._silence_samples >= self.silence_hang * TARGET_RATE
        end_by_length = total >= self.max_utt * TARGET_RATE

        if end_by_silence or end_by_length:
            if self._speech_samples >= self.min_speech * TARGET_RATE:
                utt = np.concatenate(self._buf).astype(np.float32)
                # "silence" = la persona termino y cedio el turno -> toca responder.
                # "maxlen"  = monologo largo cortado por seguridad -> solo transcribir.
                reason = "silence" if end_by_silence else "maxlen"
                try:
                    self.on_utterance(utt, reason)
                except Exception:
                    pass
            self._reset()

    def _reset(self):
        self._in_speech = False
        self._buf = []
        self._speech_samples = 0
        self._silence_samples = 0
        self._preroll = np.zeros(0, dtype=np.float32)


class AudioEngine:
    """Arranca/detiene la captura de loopback y microfono."""

    def __init__(self, on_sys_level, on_mic_level, on_utterance, on_status,
                 capture_mic_utterances=False, gain_system=1.0, gain_mic=1.0,
                 speech_threshold=0.012, silence_hang=0.7, max_utterance=8.0,
                 mic_echo_gate=True, on_system_pcm=None, segment_system=True):
        """on_utterance(audio, source, reason).

        source: 'system' | 'mic'.  reason: 'silence' (fin de turno) | 'maxlen' (corte).
        gain_*: ganancia digital aplicada antes de medir nivel y detectar voz.
        speech_threshold: mas bajo = mas sensible.
        capture_mic_utterances: transcribir tambien el microfono (Modo prueba).

        on_system_pcm(bloque_f32_16k): audio continuo de la reunion, sin cortar.
            Lo usa la transcripcion en streaming, que necesita el flujo entero y
            decide ella misma donde termina cada turno.
        segment_system: cortar la reunion en frases por silencio. Solo hace falta
            en modo offline (Whisper transcribe frases sueltas, no un flujo).
        """
        self.on_sys_level = on_sys_level
        self.on_mic_level = on_mic_level
        self.on_status = on_status
        self.on_system_pcm = on_system_pcm
        self.gain_system = float(gain_system)
        self.gain_mic = float(gain_mic)
        self.speech_threshold = float(speech_threshold)
        self.mic_echo_gate = bool(mic_echo_gate)
        # Instante hasta el que consideramos que los altavoces estan sonando.
        # Mientras tanto, el microfono no se transcribe (seria eco).
        self._sys_active_until = 0.0

        seg_kwargs = dict(speech_thresh=speech_threshold,
                          silence_hang=silence_hang,
                          max_utt=max_utterance)
        self._seg_sys = _Segmenter(
            lambda a, r: on_utterance(a, "system", r), **seg_kwargs) \
            if segment_system else None
        self._seg_mic = _Segmenter(
            lambda a, r: on_utterance(a, "mic", r), **seg_kwargs) \
            if capture_mic_utterances else None

        self._p = None
        self._running = False
        self._threads = []

    def start(self):
        if self._running:
            return
        self._p = pyaudio.PyAudio()
        self._running = True

        try:
            lb = _pick_loopback_device(self._p)
            self._threads.append(threading.Thread(
                target=self._capture, args=(lb, True), daemon=True))
        except Exception as e:
            self.on_status(f"Loopback no disponible: {e}")

        try:
            mic = _pick_input_device(self._p)
            self._threads.append(threading.Thread(
                target=self._capture, args=(mic, False), daemon=True))
        except Exception as e:
            self.on_status(f"Microfono no disponible: {e}")

        for t in self._threads:
            t.start()

    def stop(self):
        """Detiene la captura de forma segura.

        Importante: nunca llamar a PyAudio.terminate() mientras un hilo siga dentro de
        stream.read(); PortAudio provoca un access violation (segfault) y la app se cae
        al cerrarse. Por eso esperamos a que los hilos salgan de verdad.
        """
        self._running = False
        still_alive = []
        for t in self._threads:
            # Con audio sonando el hilo sale en ~0.03 s. Si no hay nada reproduciendose,
            # el loopback de WASAPI se queda bloqueado en read(): no esperamos de mas.
            t.join(timeout=1.5)
            if t.is_alive():
                still_alive.append(t)
        self._threads = []

        if self._p is not None:
            if still_alive:
                # Un hilo sigue bloqueado: soltar la referencia sin terminar PortAudio.
                # Preferimos filtrar el recurso antes que caernos.
                self.on_status("Aviso: un hilo de audio no respondio; no se libero PortAudio.")
                self._p = None
            else:
                try:
                    self._p.terminate()
                except Exception:
                    pass
                self._p = None

    def _capture(self, device, is_loopback):
        rate = int(device["defaultSampleRate"])
        ch = int(device["maxInputChannels"]) or 1
        name = "sistema" if is_loopback else "microfono"
        try:
            stream = self._p.open(
                format=pyaudio.paInt16,
                channels=ch,
                rate=rate,
                input=True,
                input_device_index=device["index"],
                frames_per_buffer=CHUNK,
            )
        except Exception as e:
            self.on_status(f"No se pudo abrir {name}: {e}")
            return

        self.on_status(f"Escuchando {name}: {device['name'][:40]} ({rate} Hz)")
        while self._running:
            try:
                data = stream.read(CHUNK, exception_on_overflow=False)
            except Exception:
                break
            arr = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
            if ch > 1:
                arr = arr.reshape(-1, ch).mean(axis=1)

            # Ganancia digital ANTES de medir y de detectar: asi la barra que ves es
            # exactamente la senal que evalua el detector de voz.
            gain = self.gain_system if is_loopback else self.gain_mic
            if gain != 1.0:
                arr = np.clip(arr * gain, -1.0, 1.0)

            rms = float(np.sqrt(np.mean(arr ** 2))) if arr.size else 0.0
            level = int(min(100, rms * 300))
            if is_loopback:
                self.on_sys_level(level)
                if rms > self.speech_threshold:
                    # Suenan los altavoces: marcar ventana de posible eco en el micro.
                    self._sys_active_until = time.monotonic() + 0.25
                block16 = soxr.resample(arr, rate, TARGET_RATE).astype(np.float32)
                if self.on_system_pcm is not None:
                    # El flujo continuo va al streaming; no se corta nada aqui.
                    try:
                        self.on_system_pcm(block16)
                    except Exception:
                        pass
                if self._seg_sys is not None:
                    self._seg_sys.process(block16)
            else:
                # El nivel se muestra SIEMPRE (asi ves que el micro esta vivo),
                # pero no lo transcribimos si es probable que sea eco.
                self.on_mic_level(level)
                if self._seg_mic is not None:
                    if self.mic_echo_gate and time.monotonic() < self._sys_active_until:
                        continue  # los altavoces estan sonando -> descartar (eco)
                    block16 = soxr.resample(arr, rate, TARGET_RATE).astype(np.float32)
                    self._seg_mic.process(block16)

        try:
            stream.stop_stream()
            stream.close()
        except Exception:
            pass
