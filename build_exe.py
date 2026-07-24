"""Empaqueta Meeting Coach como aplicacion de escritorio (.exe) con PyInstaller.

Genera dist/MeetingCoach/MeetingCoach.exe : un ejecutable sin consola, con las
fuentes e iconos incluidos. Para el usuario final es una app normal de Windows,
no un script de Python.

Uso:
    .venv\\Scripts\\python.exe build_exe.py

Nota: el paquete pesa bastante (PySide6 + faster-whisper + CTranslate2 + CUDA).
El modelo de Whisper NO se incluye: se descarga la primera vez, como ahora.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SEP = ";" if sys.platform.startswith("win") else ":"


def main():
    # Incluir las carpetas de datos si existen (fuentes, iconos empaquetados).
    add_data = []
    for carpeta in ("assets",):
        ruta = os.path.join(HERE, carpeta)
        if os.path.isdir(ruta):
            add_data += ["--add-data", f"{ruta}{SEP}{carpeta}"]

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "MeetingCoach",
        "--noconsole",              # sin ventana negra de consola
        "--noconfirm",
        "--clean",
        # faster-whisper / ctranslate2 cargan datos y binarios por su cuenta:
        "--collect-all", "faster_whisper",
        "--collect-all", "ctranslate2",
        "--collect-binaries", "nvidia",   # cuBLAS / cuDNN de pip, si estan
        *add_data,
        os.path.join(HERE, "app.py"),
    ]
    print("Ejecutando:", " ".join(cmd))
    subprocess.check_call(cmd, cwd=HERE)
    print("\nListo. El ejecutable esta en: dist\\MeetingCoach\\MeetingCoach.exe")


if __name__ == "__main__":
    main()
