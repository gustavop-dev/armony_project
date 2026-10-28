"""Captura de audio en Windows via WASAPI.

- Loopback (salida del sistema = lo que dicen los demas en la reunion): se transcribe.
- Microfono (tu voz): solo se usa para el medidor de nivel (verificar que se escucha).

Cada fuente corre en su propio hilo y calcula el nivel RMS (para las barras). El
loopback, ademas, se pasa a 16 kHz mono y se entrega continuo a la transcripcion
en streaming, que decide ella misma donde termina cada turno.
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

TARGET_RATE = 16000     # la transcripcion en streaming trabaja a 16 kHz mono
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


class AudioEngine:
    """Arranca/detiene la captura de loopback y microfono."""

    def __init__(self, on_sys_level, on_mic_level, on_status, on_system_pcm,
                 gain_system=1.0, gain_mic=1.0):
        """on_system_pcm(bloque_f32_16k): audio continuo de la reunion, sin cortar.
            Lo consume la transcripcion en streaming.

        gain_*: ganancia digital aplicada antes de medir nivel y de transcribir.
        """
        self.on_sys_level = on_sys_level
        self.on_mic_level = on_mic_level
        self.on_status = on_status
        self.on_system_pcm = on_system_pcm
        self.gain_system = float(gain_system)
        self.gain_mic = float(gain_mic)

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
        ultimo_chequeo = time.monotonic()
        while self._running:
            # Si cambias de altavoces a auriculares a media reunion, Windows
            # cambia la salida por defecto y este dispositivo se queda mudo. Sin
            # avisar: transcripcion vacia y a saber por que. Se vigila cada par
            # de segundos y se reengancha al nuevo.
            if is_loopback and time.monotonic() - ultimo_chequeo > 2.0:
                ultimo_chequeo = time.monotonic()
                try:
                    ahora = _pick_loopback_device(self._p)
                    if ahora["index"] != device["index"]:
                        self.on_status(f"Salida de audio cambiada a "
                                       f"{ahora['name'][:40]}: reenganchando.")
                        try:
                            stream.stop_stream()
                            stream.close()
                        except Exception:
                            pass
                        return self._capture(ahora, True)
                except Exception:
                    pass
            try:
                data = stream.read(CHUNK, exception_on_overflow=False)
            except Exception:
                break
            arr = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
            if ch > 1:
                arr = arr.reshape(-1, ch).mean(axis=1)

            # Ganancia digital ANTES de medir y de transcribir: asi la barra que ves
            # es exactamente la senal que llega a la transcripcion.
            gain = self.gain_system if is_loopback else self.gain_mic
            if gain != 1.0:
                arr = np.clip(arr * gain, -1.0, 1.0)

            rms = float(np.sqrt(np.mean(arr ** 2))) if arr.size else 0.0
            level = int(min(100, rms * 300))
            if is_loopback:
                self.on_sys_level(level)
                block16 = soxr.resample(arr, rate, TARGET_RATE).astype(np.float32)
                try:
                    self.on_system_pcm(block16)
                except Exception:
                    pass
            else:
                # El micro solo alimenta la barra de nivel (asi ves que esta vivo).
                self.on_mic_level(level)

        try:
            stream.stop_stream()
            stream.close()
        except Exception:
            pass
