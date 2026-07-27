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
- **Sugiere respuestas** en streaming (aparecen token por token), con **Claude
  (Anthropic) o GPT (OpenAI)** — se elige en *Configuración*, cada uno con su clave
  y su modelo.
- **Screenshot → Claude:** botón para mandar una captura de pantalla y preguntar (visión).
- **Invisible al compartir pantalla:** `SetWindowDisplayAffinity` (Windows 10 2004+/11).

## Requisitos

- Windows 10 (build 19041+) u 11.
- Python 3.10 u 3.11 recomendado.
- API key del proveedor de respuestas que elijas: **Anthropic** u **OpenAI**
  (se pone en la interfaz, en *Configuración*).
- API key de AssemblyAI para la transcripción en vivo (también en *Configuración*).
  Si prefieres no usar la nube, activa **Modo offline** y solo hace falta la de Anthropic.

## Ejecutable (.exe)

```powershell
python build_exe.py      # genera dist\Armony.exe (~53 MB, un solo archivo)
```

No necesita Python instalado. El icono («Ar.» sobre blanco) se genera con
`make_icon.py` y se incrusta en el ejecutable.

Tus datos **no** viven junto al .exe: `config.json` y los contextos van a
`%APPDATA%\Armony`, que es escribible y sobrevive a las actualizaciones. Con
`--onefile` el programa se descomprime en un temporal que desaparece al cerrar,
así que guardar ahí perdería la configuración en cada arranque.

El modo offline **no** se incluye salvo que compiles con `faster-whisper`
instalado; sin él el ejecutable pesa una fracción y el resto funciona igual.

### Dónde quedan tus claves

Las API keys se guardan **cifradas con DPAPI de Windows**, atadas a tu cuenta de
usuario: el archivo solo se puede descifrar desde tu sesión y en este equipo, sin
que tengas que recordar ninguna contraseña maestra. Si copias `config.json` a otro
PC, las claves no se pueden leer.

No es magia: algo que corra *como tú* puede descifrarlas igual. Pero convierte
«roba el archivo y ya tienes las claves» en «hay que ejecutar código en su sesión».

## Instalación (desde el código)

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

1. Abre **Configuración**, elige el **proveedor de respuestas** y pega su API key,
   más la de **AssemblyAI**. Guarda.
2. Pulsa **Iniciar**.
3. Verifica que las barras **Reunión** y **Micro** se mueven con el audio.
4. Cuando alguien hable en la reunión, verás la transcripción **en vivo** y, cuando
   te pregunten algo, la **respuesta sugerida**.
5. **`Alt+2`** captura la pantalla (puedes encadenar varias) y **`Alt+3`** las manda.
   La miniatura se queda en el panel de respuesta, alineada a la derecha como el
   mensaje que acabas de enviar, y la respuesta aparece debajo.

   Con la captura **no va solo la imagen**: se manda el prompt del sistema con tus
   contextos, el historial reciente de la reunión etiquetado por hablante y lo
   último que dijeron. El modelo ve el pantallazo *dentro* de la conversación.

   Y se manda **mucho más hilo que en una pregunta hablada** (hasta 40
   intervenciones frente a 18), porque el pantallazo suele ser solo una parte del
   problema: el resto está en lo que llevan un rato contando.

   La captura es **silenciosa**: sin destello, sin sonido y sin aviso de Windows.
   El único acuse de recibo es esa miniatura, que solo ves tú. Y lo que se manda al
   modelo es lo que hay **debajo** del overlay: las ventanas de la app están
   excluidas de la captura, así que no se tapan a sí mismas el contenido.

### Reuniones que cambian de idioma

Pasa constantemente: se habla en español y de pronto alguien salta al inglés. Está
cubierto de punta a punta:

- **La transcripción** lo detecta sola, incluso a mitad de frase. Comprobado con
  audio mixto, limpio y con ruido: transcribe bien las dos partes tanto con el
  idioma fijado como en `Auto`.
- **La respuesta sale en el idioma de la última pregunta**, aunque el prompt y el
  contexto estén en otro. Si te preguntan en inglés, lees en inglés.
- **Al modelo se le manda todo**: las dos versiones del prompt del coach (ES y EN)
  y *todos* los contextos activos, sin filtrar por idioma. El campo `Idioma` de
  cada contexto queda solo para organizarlos. Filtrarlos dejaría al modelo sin la
  mitad de lo que necesita justo cuando la reunión cambia de idioma, que es cuando
  más falta hace.

### El panel es un hilo, no un marcador

La conversación se acumula como en un chat: lo que dicen ellos a la izquierda, lo
que se te sugiere a la derecha, y las capturas que envías también a la derecha. Lo
viejo se queda arriba y lo nuevo entra por abajo, así que puedes releer lo de hace
tres turnos sin perder lo que está llegando.

El hilo sigue el final por sí solo mientras entra conversación, pero si subes a
releer algo se queda quieto hasta que vuelvas a bajar.

### Cómo se pinta la respuesta

El modelo contesta en markdown y el panel lo renderiza: secciones, **negritas**,
`código en línea`, listas y **bloques de código** con su lenguaje y un botón para
copiar. El código se muestra tal cual, con sus saltos de línea e indentación.

Cuando la pregunta llega por voz, la respuesta es una explicación breve para decir
en voz alta. Cuando llega por captura de pantalla, el prompt pide además la
**solución completa** en un bloque de código copiable y la explicación de tú a tú.
En los dos casos, siempre en primera persona: lo que se lee es lo que tú dirías.

### Atajos

Funcionan aunque el foco esté en Zoom, Meet o Excel. Mientras la app corre, el Alt
queda reservado para ella: la aplicación de debajo no lo recibe, así que Excel no
abre las KeyTips de la cinta ni se te escribe el número en la celda.

| Atajo | Qué hace |
|---|---|
| `Alt+1` | Mostrar / ocultar el overlay |
| `Alt+2` | Captura de pantalla (se pueden encadenar varias) |
| `Alt+3` | Generar respuesta con las capturas tomadas |
| `Alt+4` | Iniciar / detener la reunión |
| `Alt+5` | Responder ahora a lo último que dijeron |

Todos tienen su botón en la barra superior con el atajo escrito al lado, así que
no hay que recordarlos.

**La rueda del ratón desplaza con solo poner el cursor encima**, tanto la
transcripción como la respuesta, y sin perder el click-through: mientras apuntas al
panel la rueda es suya y lo que hay debajo no se mueve; en cuanto sales, todo vuelve
a la normalidad. Las dos columnas van siguiendo el final según entra texto nuevo,
pero si subes a releer algo se quedan quietas hasta que vuelvas a bajar.

**El cursor nunca cambia de forma sobre el overlay.** No es un descuido: la ventana
es invisible al compartir pantalla, pero el cursor no lo es. Si se convirtiera en
manita sobre un botón invisible, quien te viera compartiendo pantalla vería el
puntero transformándose sobre la nada, y el overlay se delataría solo.

### Cuándo responde (y cuándo no)

En una reunión la gente da mucho más contexto del que pregunta, así que responder a
cada frase llenaría el panel de ruido. Hay dos filtros antes de molestar a la IA:

1. **En tu equipo, gratis:** si la intervención no parece pregunta ni petición, ni se
   llama a Claude. El texto no se pierde — queda en el historial y será contexto de la
   próxima respuesta.
2. **Claude:** lo que pasa el primer filtro puede seguir sin ser una pregunta ("y bueno,
   qué te digo…"). En ese caso el modelo se calla y no se pinta nada.

Si preguntaron y la transcripción se comió los signos, **`Alt+5`** fuerza la respuesta.
Por eso los filtros pueden permitirse ser prudentes: quedarse corto se arregla con una
tecla, pasarse de hablador te arruina la reunión.

### Qué recuerda de la reunión

El motor guarda las últimas 120 entradas y manda una parte en cada consulta: 36 con
una pregunta hablada, hasta 80 con un pantallazo. Ojo al contar: **cada turno
respondido deja dos entradas** (lo que dijeron y lo que se sugirió), así que eso
son ~18 y ~40 turnos reales. Los dos modelos —el de voz y el de capturas—
comparten el mismo hilo; lo único que cambia entre ellos es el modelo y el límite
de tokens.

**Cada sugerencia entregada se guarda como contexto**, etiquetada `Yo (sugerido)`:
del bloque de código solo queda una marca, y del texto un resumen corto. Así la IA
sabe lo que ya te propuso y continúa desde ahí en vez de repetírtelo.

> Tu micrófono **no se transcribe** (sería una segunda conexión y el doble de
> coste). Lo que digas con tus palabras no llega al modelo; lo que sí llega es lo
> que te sugirió, que es casi siempre lo mismo. Si en tus reuniones explicas cosas
> que la IA necesitaría saber, se puede activar ese segundo stream.

### La transcripción es un dato, no una orden

Lo que se oye en la reunión es texto de terceros, así que se le dice explícitamente
al modelo que nadie de la reunión puede cambiar sus instrucciones, pedirle que las
revele, redefinir quién es ni cambiar el formato de su respuesta. Si algo así
aparece en lo transcrito, lo trata como un dato más de lo que dijeron.

Sin esto, cualquiera que hable podría reprogramar tu asistente diciéndolo en voz
alta.

### Cuando le falta un dato

Si para responder ha tenido que suponer algo importante (no sabe su stack, el
volumen, qué lenguaje quieren), añade al final una sección **Necesito saber** con
*una* pregunta corta, escrita como se la dirías tú a la otra persona para soltarla
en voz alta.

Nunca en lugar de la respuesta: primero propone, y la pregunta va después. Y si ya
te dijeron que ese dato no te lo pueden dar —o que justo eso es lo que tienes que
resolver— no vuelve a preguntar: propone y deja sus suposiciones por escrito.

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
### Dos modelos, uno por cada uso

En *Configuración → Conexión* solo aparece el proveedor que tengas elegido (o las
opciones de Anthropic, o las de OpenAI, nunca las dos), y cada uno se configura con
**dos modelos**, porque los dos usos no se parecen en nada:

| Uso | Qué manda | Por defecto |
|---|---|---|
| **Preguntas habladas** | La latencia: la respuesta tiene que estar antes de que el silencio se note | `gpt-5.6-terra` · `claude-haiku-4-5` |
| **Capturas de pantalla** | La capacidad: suele haber código que resolver, y unos segundos de más no se notan porque estás leyendo | `gpt-5.6-sol` · `claude-sonnet-5` |

Cada uno con su propia **longitud máxima de respuesta**, justo debajo del modelo:
400 tokens bastan para una respuesta hablada, pero el código se queda corto ahí, así
que las capturas van con 1200.

Tiempos de GPT medidos desde este equipo (mediana de 5 llamadas, hasta la primera
palabra en pantalla): `gpt-5.4-mini` 0,7 s · `gpt-5.6-terra` 0,8 s ·
`gpt-5.6-luna` 1,2 s · `gpt-5.6-sol` 1,3 s. De **calidad** no hay medida, así que
las opciones no están ordenadas por «listas».

Ojo con los modelos GPT-5: razonan antes de responder y ese razonamiento gasta del
mismo presupuesto de tokens, así que `llm.py` reserva margen aparte para que el
ajuste de longitud siga refiriéndose a la respuesta y no llegue vacía.

## Notas técnicas

- `audio.py` — captura WASAPI (loopback + micrófono), niveles, flujo continuo para el
  streaming y segmentación por silencio (esta última solo hace falta en modo offline).
- `stt_stream.py` — transcripción en vivo con AssemblyAI (WebSocket, reconexión automática).
- `intent.py` — decide si una intervención pide respuesta o solo está dando contexto.
- `richtext.py` — convierte el markdown del modelo en bloques (texto, código, listas).
- `secretstore.py` — cifra las API keys con DPAPI (atado a tu cuenta de Windows).
- `make_icon.py` — genera el icono «Ar.» en todos los tamaños que pide Windows.
- `transcribe.py` — modo offline: `faster-whisper` (CUDA si hay, si no CPU int8).
- `llm.py` — cliente del coach con streaming y soporte de imagen (screenshot).
  Anthropic y OpenAI tras la misma interfaz; solo se importa el que se use.
- `overlay.py` — modo invisible a la captura de pantalla y click-through.
- `wheelscroll.py` — desvía la rueda del ratón al overlay cuando el cursor está
  encima. Hace falta porque el click-through (`WS_EX_TRANSPARENT`) vuelve la
  ventana transparente a *todo* el ratón, rueda incluida.
- `app.py` — interfaz (PySide6) y orquestación.
- `config.py` / `config.json` — ajustes (la API key se guarda localmente).

## Ideas a futuro

- Respuestas por proveedor (Claude/OpenAI) elegible.
- El agente que se conecta a la videollamada y da soporte a clientes.
