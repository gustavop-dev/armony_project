"""Registra las DLLs de CUDA (cuBLAS / cuDNN) instaladas via pip.

En Windows, los paquetes nvidia-cublas-cu12 y nvidia-cudnn-cu12 dejan sus DLLs dentro
de site-packages/nvidia/<lib>/bin, una ruta que CTranslate2 no busca por su cuenta.
Sin esto falla con "Library cublas64_12.dll is not found or cannot be loaded".

Importar este modulo ANTES de crear el WhisperModel en GPU.
"""
import os
import sys
import glob

_registered = False


def register_cuda_dlls() -> list:
    """Anade los directorios de DLLs de NVIDIA. Devuelve las rutas registradas."""
    global _registered
    if _registered or not sys.platform.startswith("win"):
        return []

    site_packages = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    added = []
    # Buscar en el site-packages del entorno actual
    for base in {os.path.dirname(p) for p in sys.path if p.endswith("site-packages")} | \
                {p for p in sys.path if p.endswith("site-packages")}:
        pattern = os.path.join(base, "nvidia", "*", "bin")
        for d in glob.glob(pattern):
            if os.path.isdir(d):
                try:
                    os.add_dll_directory(d)
                    # PATH tambien, por si alguna dependencia lo resuelve por ahi
                    os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
                    added.append(d)
                except OSError:
                    pass

    _registered = True
    return added
