"""Transcripcion local con faster-whisper.

Detecta GPU NVIDIA (CUDA) si esta disponible; si no, usa CPU con int8 (mas ligero).
El modelo se descarga la primera vez que se usa.
"""
import logging

from cuda_setup import register_cuda_dlls

# Debe ejecutarse antes de cargar cualquier modelo en GPU (busca cuBLAS/cuDNN de pip).
register_cuda_dlls()

from faster_whisper import WhisperModel  # noqa: E402

log = logging.getLogger("armony.transcribe")


class Transcriber:
    def __init__(self, size="base", device="auto", language="es"):
        self.language = None if language == "auto" else language
        self.model = None
        self._load(size, device)

    def _load(self, size, device):
        if device == "auto":
            # Intentar CUDA (NVIDIA); si falla, caer a CPU.
            try:
                self.model = WhisperModel(size, device="cuda", compute_type="float16")
                self.device = "cuda"
                return
            except Exception as e:
                log.info("Whisper CUDA load failed (%s: %s); using CPU int8",
                         type(e).__name__, e)
            self.model = WhisperModel(size, device="cpu", compute_type="int8")
            self.device = "cpu"
        elif device == "cuda":
            self.model = WhisperModel(size, device="cuda", compute_type="float16")
            self.device = "cuda"
        else:
            self.model = WhisperModel(size, device="cpu", compute_type="int8")
            self.device = "cpu"

    def transcribe(self, audio_f32_16k):
        """audio_f32_16k: numpy float32 mono a 16 kHz. Devuelve texto (str)."""
        segments, _info = self.model.transcribe(
            audio_f32_16k,
            language=self.language,
            beam_size=1,          # rapido
            vad_filter=False,     # ya segmentamos nosotros
        )
        return " ".join(s.text.strip() for s in segments).strip()
