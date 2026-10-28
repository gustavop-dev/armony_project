"""Medidor del camino completo de una reunion.

La cadena tiene muchos tramos —audio, transcripcion, filtro, modelo, pintado— y
cuando algo va lento no basta con notarlo: hay que saber DONDE. Aqui se apuntan
tiempos y cuentas de cada tramo, con un coste practicamente nulo (una lista y un
candado), y al terminar la reunion se guarda un informe.

El numero que de verdad importa es 'extremo a extremo': desde que la persona
termina de preguntar hasta que aparece la primera palabra de la sugerencia. Todo
lo demas sirve para saber a quien echarle la culpa cuando ese sube.
"""
import json
import os
import statistics
import threading
import time
from collections import Counter, defaultdict

# Nombres de las medidas, para no escribirlos a mano y que no se dupliquen.
STT_CONEXION = "stt_conexion_ms"        # abrir el WebSocket de transcripcion
STT_LATENCIA = "stt_latencia_ms"        # ultima palabra -> texto final
LLM_PRIMERA = "llm_primera_palabra_ms"  # peticion -> primer trozo de respuesta
LLM_TOTAL = "llm_total_ms"              # peticion -> respuesta completa
LLM_CALENTAMIENTO = "llm_calentamiento_ms"
E2E = "extremo_a_extremo_ms"            # fin de la pregunta -> primera palabra
PINTADO = "pintado_ms"                  # repintar la burbuja que se escribe


class Metricas:
    def __init__(self):
        self._lock = threading.Lock()
        self._muestras = defaultdict(list)
        self._cuentas = Counter()
        self._t0 = None
        self._notas = []

    # -- registro -----------------------------------------------------------
    def iniciar(self):
        with self._lock:
            self._muestras.clear()
            self._cuentas.clear()
            self._notas = []
            self._t0 = time.monotonic()

    def medir(self, nombre, ms):
        if ms is None:
            return
        with self._lock:
            self._muestras[nombre].append(float(ms))

    def contar(self, nombre, n=1):
        with self._lock:
            self._cuentas[nombre] += n

    def nota(self, texto):
        """Algo que no es un numero pero conviene recordar (modelo, proveedor...)."""
        with self._lock:
            self._notas.append(texto)

    def cronometro(self, nombre):
        """with metricas.cronometro('algo'): ..."""
        return _Cronometro(self, nombre)

    # -- lectura ------------------------------------------------------------
    def resumen(self):
        with self._lock:
            fuera = {"duracion_s": round(time.monotonic() - self._t0, 1)
                     if self._t0 else 0,
                     "cuentas": dict(self._cuentas),
                     "notas": list(self._notas),
                     "medidas": {}}
            for nombre, vals in self._muestras.items():
                if not vals:
                    continue
                ordenados = sorted(vals)
                fuera["medidas"][nombre] = {
                    "n": len(vals),
                    "mediana": round(statistics.median(ordenados)),
                    "p90": round(ordenados[min(len(ordenados) - 1,
                                               int(len(ordenados) * 0.9))]),
                    "min": round(ordenados[0]),
                    "max": round(ordenados[-1]),
                }
            return fuera

    def texto(self):
        """Informe legible, para mirarlo sin abrir un JSON."""
        r = self.resumen()
        lineas = [f"Reunion de {r['duracion_s']} s"]
        for n in r["notas"]:
            lineas.append(f"  {n}")
        if r["medidas"]:
            lineas.append("")
            lineas.append(f"  {'medida':26}{'n':>4}{'mediana':>10}{'p90':>8}"
                          f"{'min':>8}{'max':>8}")
            for nombre, m in sorted(r["medidas"].items()):
                lineas.append(f"  {nombre:26}{m['n']:>4}{m['mediana']:>9} ms"
                              f"{m['p90']:>7}{m['min']:>8}{m['max']:>8}")
        if r["cuentas"]:
            lineas.append("")
            for k, v in sorted(r["cuentas"].items()):
                lineas.append(f"  {k:34}{v:>6}")
        return "\n".join(lineas)

    def guardar(self, carpeta):
        """Deja el informe junto a la configuracion. Devuelve la ruta o None."""
        try:
            destino = os.path.join(carpeta, "metricas")
            os.makedirs(destino, exist_ok=True)
            marca = time.strftime("%Y%m%d-%H%M%S")
            ruta = os.path.join(destino, f"sesion-{marca}.json")
            with open(ruta, "w", encoding="utf-8") as f:
                json.dump(self.resumen(), f, ensure_ascii=False, indent=2)
            with open(ruta.replace(".json", ".txt"), "w", encoding="utf-8") as f:
                f.write(self.texto() + "\n")
            return ruta
        except OSError:
            return None


class _Cronometro:
    def __init__(self, metricas, nombre):
        self.metricas, self.nombre = metricas, nombre

    def __enter__(self):
        self.t0 = time.monotonic()
        return self

    def __exit__(self, *_e):
        self.metricas.medir(self.nombre, (time.monotonic() - self.t0) * 1000)
        return False


# Una sola instancia para toda la app: los tramos estan repartidos por varios
# modulos y pasarla a mano por todos seria mas ruido que valor.
metricas = Metricas()
