"""Empaqueta Armony como aplicacion de escritorio (.exe) con PyInstaller.

Genera dist/Armony.exe: un unico archivo, sin ventana de consola y con el icono
'Ar.'. Para usarlo no hace falta tener Python instalado.

Uso:
    python build_exe.py

Sobre donde quedan tus datos: el .exe NO guarda nada en su propia carpeta (con
--onefile se descomprime en un temporal que desaparece al cerrar). config.json y
los contextos van a %APPDATA%\\Armony, que persiste entre versiones. Lo gestiona
config.data_dir().
"""
import importlib.util
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SEP = ";" if sys.platform.startswith("win") else ":"


def instalado(modulo):
    try:
        return importlib.util.find_spec(modulo) is not None
    except (ImportError, ValueError):
        return False


def dlls_de_openssl():
    """Localiza libssl/libcrypto cuando el Python base es de conda.

    En un Python normal esas DLL viven en DLLs\\ y PyInstaller las encuentra
    solo. Conda las pone en Library\\bin, donde no mira, y el ejecutable arranca
    perfectamente pero explota en la PRIMERA conexion HTTPS con
    'DLL load failed while importing _ssl'. Como aqui la primera conexion es al
    iniciar la reunion, el fallo aparece justo al pulsar Iniciar.
    """
    candidatos = []
    for raiz in {sys.base_prefix, sys.prefix}:
        for sub in ("Library\\bin", "DLLs", ""):
            carpeta = os.path.join(raiz, sub) if sub else raiz
            if not os.path.isdir(carpeta):
                continue
            for nombre in os.listdir(carpeta):
                bajo = nombre.lower()
                if bajo.endswith(".dll") and ("libssl" in bajo or "libcrypto" in bajo):
                    candidatos.append(os.path.join(carpeta, nombre))
    # sin duplicados, conservando el orden de busqueda
    vistos, salida = set(), []
    for ruta in candidatos:
        clave = os.path.basename(ruta).lower()
        if clave not in vistos:
            vistos.add(clave)
            salida.append(ruta)
    return salida


def main():
    icono = os.path.join(HERE, "assets", "armony.ico")
    if not os.path.exists(icono):
        print("Falta el icono; generandolo...")
        subprocess.check_call([sys.executable, os.path.join(HERE, "make_icon.py")],
                              cwd=HERE)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "Armony",
        "--onefile",                # un solo archivo, comodo de mover
        "--noconsole",              # sin ventana negra detras
        "--noconfirm",
        "--clean",
        "--icon", icono,
        "--add-data", f"{os.path.join(HERE, 'assets')}{SEP}assets",
    ]

    # Pygments carga cada lenguaje por nombre en tiempo de ejecucion, asi que
    # PyInstaller no ve esos imports y el .exe se quedaria sin colorear codigo.
    if instalado("pygments"):
        cmd += ["--collect-all", "pygments"]

    for dll in dlls_de_openssl():
        print(f"OpenSSL: incluyendo {os.path.basename(dll)}")
        cmd += ["--add-binary", f"{dll}{SEP}."]

    # Restos del antiguo modo offline: si siguen instalados en el entorno de
    # compilacion, que no se cuelen en el .exe (pesan cientos de MB).
    cmd += ["--exclude-module", "faster_whisper", "--exclude-module", "ctranslate2",
            "--exclude-module", "torch"]

    cmd.append(os.path.join(HERE, "app.py"))
    print("Ejecutando:", " ".join(cmd))
    subprocess.check_call(cmd, cwd=HERE)

    exe = os.path.join(HERE, "dist", "Armony.exe")
    if os.path.exists(exe):
        print(f"\nListo: {exe}  ({os.path.getsize(exe) / 1_048_576:.0f} MB)")
    else:
        print("\nPyInstaller termino pero no encuentro dist/Armony.exe")


if __name__ == "__main__":
    main()
