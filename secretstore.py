"""Cifrado de las claves guardadas, atado a tu cuenta de Windows.

Las API keys viven en config.json. En texto plano las lee cualquier cosa que
llegue a tu disco: un script, un programa curioso o algo peor. Windows trae DPAPI
justo para esto: cifra con una clave derivada de tu cuenta de usuario, asi que el
archivo solo se puede descifrar desde tu sesion, en este equipo, y no hay que
inventarse ninguna contraseña maestra.

No protege de todo (algo que corra COMO TU puede descifrarlo igual), pero
convierte "roba el archivo y ya tienes las claves" en "hay que ejecutar codigo en
su sesion", que es un liston bastante mas alto.

Los valores cifrados se guardan con el prefijo 'dpapi:' para poder distinguirlos
de los que aun estan en claro y migrarlos sin que el usuario haga nada.
"""
import base64
import ctypes
from ctypes import wintypes

PREFIJO = "dpapi:"

_CRYPTPROTECT_UI_FORBIDDEN = 0x01


class _BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(datos):
    buf = ctypes.create_string_buffer(datos, len(datos))
    return _BLOB(len(datos), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def _leer(blob):
    datos = ctypes.string_at(blob.pbData, blob.cbData)
    ctypes.windll.kernel32.LocalFree(blob.pbData)
    return datos


def proteger(texto):
    """Cifra un valor. Si algo falla, devuelve el texto tal cual (nunca se pierde)."""
    if not texto or texto.startswith(PREFIJO):
        return texto
    try:
        entrada, _buf = _blob(texto.encode("utf-8"))
        salida = _BLOB()
        ok = ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(entrada), None, None, None, None,
            _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(salida))
        if not ok:
            return texto
        return PREFIJO + base64.b64encode(_leer(salida)).decode("ascii")
    except Exception:
        return texto


def revelar(texto):
    """Descifra un valor protegido. Los que no lo esten se devuelven igual."""
    if not texto or not texto.startswith(PREFIJO):
        return texto
    try:
        crudo = base64.b64decode(texto[len(PREFIJO):])
        entrada, _buf = _blob(crudo)
        salida = _BLOB()
        ok = ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(entrada), None, None, None, None,
            _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(salida))
        if not ok:
            # Otra cuenta u otro equipo: la clave no sirve aqui. Mejor vacia que
            # un churro ilegible que acabaria mandandose a la API.
            return ""
        return _leer(salida).decode("utf-8")
    except Exception:
        return ""


def esta_protegido(texto):
    return bool(texto) and texto.startswith(PREFIJO)
