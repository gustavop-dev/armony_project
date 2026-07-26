# Meeting Coach

Asistente de reuniones para **practicar y entrenar** cómo responder en vivo. Escucha el
audio de la reunión (salida del sistema) y tu micrófono, transcribe en vivo y te sugiere
con Claude qué podrías responder — todo en una ventana que **tú ves pero que es invisible
al compartir pantalla** (privacidad total).

> Proyecto personal. Úsalo de forma responsable y solo donde tengas permiso para hacerlo.

## Qué hace

- **Escucha dos fuentes** con medidores en vivo para verificar que ambas se oyen:
  - *Reunión (sistema):* lo que dicen los demás (WASAPI loopback). Es lo que se transcribe.
  - *Micrófono:* tu voz (solo medidor de verificación).
- **Transcribe en vivo** con AssemblyAI (Universal Streaming): el texto aparece palabra a
  palabra mientras la otra persona habla, y es el propio modelo quien detecta cuándo
  terminó de hablar.
- **Modo offline** opcional: transcribe en este equipo con `faster-whisper`, sin enviar
  audio a la nube. Más lento y sin texto en vivo, pero funciona sin internet.
- **Sugiere respuestas** con Claude en streaming (aparecen token por token).
- **Screenshot → Claude:** botón para mandar una captura de pantalla y preguntar (visión).
- **Invisible al compartir pantalla:** `SetWindowDisplayAffinity` (Windows 10 2004+/11).

## Requisitos

- Windows 10 (build 19041+) u 11.
- Python 3.10 u 3.11 recomendado.
- API key de Anthropic (se pone en la interfaz, en *Configuración*).
- API key de AssemblyAI para la transcripción en vivo (también en *Configuración*).
  Si prefieres no usar la nube, activa **Modo offline** y solo hace falta la de Anthropic.

## Instalación

```powershell
cd C:\Users\elcer\meeting-coach
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Uso

```powershell
python app.py
```

### Modo prueba (sin API key)

Marca **Modo prueba** y pulsa *Iniciar*. No requiere API key ni llama a Claude: solo
captura audio y transcribe **ambas** fuentes, etiquetadas, para verificar el montaje:

- `[REUNION] ...` → audio del sistema (pon un vídeo hablado)
- `[MICRO]   ...` → tu micrófono (habla)

Si ambas líneas aparecen con texto correcto, la captura y la transcripción funcionan.
La barra de estado muestra los milisegundos que tardó cada transcripción.
Desmárcalo y añade la API key para las sugerencias reales.

> En operación normal solo se transcribe el audio del sistema (lo que dicen los demás);
> tu micrófono es únicamente un medidor de nivel.

1. Abre **Configuración** y pega tu **API key de Anthropic**. Guarda.
2. Pulsa **Iniciar** (la primera vez descarga el modelo Whisper).
3. Verifica que las barras **Reunión** y **Micro** se mueven con el audio.
4. Cuando alguien hable en la reunión, verás la transcripción y la **respuesta sugerida**.
5. Botón **Captura pantalla + preguntar** para preguntas visuales.

## GPU NVIDIA (importante)

`faster-whisper` necesita las librerías de CUDA 12 y cuDNN 9. Si no están, la carga del
modelo funciona pero la inferencia falla con
`Library cublas64_12.dll is not found or cannot be loaded`. Solución:

```powershell
pip install nvidia-cublas-cu12 nvidia-cudnn-cu12
```

En Windows esas DLLs quedan dentro de `site-packages/nvidia/*/bin`, una ruta que
CTranslate2 no busca sola. `cuda_setup.py` las registra automáticamente al arrancar
(`transcribe.py` lo importa antes de cargar el modelo). No hay que hacer nada más.

## Rendimiento / latencia

**En vivo (AssemblyAI, por defecto).** El texto va apareciendo mientras la persona habla,
así que no se espera a que termine la frase. Medido con audio real del sistema: **76–84 ms**
desde la última palabra hasta el texto final. A eso se le suma la pausa de fin de turno
(ajuste *Pausa de fin de turno*, 0.7 s por defecto) y ~0.5 s del primer token de Claude
Haiku. Coste aproximado: **$0.45 por hora de reunión** — se factura el tiempo conectado,
no el audio enviado, y la conexión solo existe mientras la reunión está en marcha.

**Modo offline (Whisper local).** Medido en GTX 1660 SUPER (6 GB), frase de 3 s:

| Modelo Whisper | Tiempo STT | Presupuesto total hasta la sugerencia |
|---|---|---|
| `base` (recomendado) | 0.24 s | ~1.35 s ✅ |
| `small` (más preciso) | 0.89 s | ~2.0 s (al límite) |

Desglose: 0.60 s de espera de fin de frase + STT + ~0.5 s del primer token de Claude Haiku.

- **PC de escritorio con GPU NVIDIA:** `Dispositivo STT = cuda`, `Tamaño Whisper = base`.
  Latencia total ~1.35 s.
- **Portátil Ryzen 5 5600H (sin NVIDIA):** corre en **CPU**. Usa `Tamaño Whisper = base`
  y cierra apps pesadas (8 GB de RAM es ajustado). Latencia ~1.5–2.5 s.
- Modelo LLM por defecto: `claude-haiku-4-5` (el más rápido). Cambia a `claude-opus-4-8`
  para más calidad a costa de algo de latencia.

## Notas técnicas

- `audio.py` — captura WASAPI (loopback + micrófono), niveles, flujo continuo para el
  streaming y segmentación por silencio (esta última solo hace falta en modo offline).
- `stt_stream.py` — transcripción en vivo con AssemblyAI (WebSocket, reconexión automática).
- `transcribe.py` — modo offline: `faster-whisper` (CUDA si hay, si no CPU int8).
- `llm.py` — cliente Anthropic con streaming y soporte de imagen (screenshot).
- `overlay.py` — modo invisible a la captura de pantalla.
- `app.py` — interfaz (PySide6) y orquestación.
- `config.py` / `config.json` — ajustes (la API key se guarda localmente).

## Ideas a futuro

- Respuestas por proveedor (Claude/OpenAI) elegible.
- El agente que se conecta a la videollamada y da soporte a clientes.
