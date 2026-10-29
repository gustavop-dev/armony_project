# Meeting Coach

Asistente de reuniones para **practicar y entrenar** cómo responder en vivo. Escucha el
audio de la reunión (salida del sistema) y tu micrófono, transcribe en vivo y te sugiere
con un modelo de OpenAI qué podrías responder — todo en una ventana que **tú ves pero que es invisible
al compartir pantalla** (privacidad total).

> Proyecto personal. Úsalo de forma responsable y solo donde tengas permiso para hacerlo.

## Qué hace

- **Escucha dos fuentes** con medidores en vivo para verificar que ambas se oyen:
  - *Reunión (sistema):* lo que dicen los demás (WASAPI loopback). Es lo que se transcribe.
  - *Micrófono:* tu voz (solo medidor de verificación).
- **Transcribe en vivo** con AssemblyAI (Universal Streaming): el texto aparece palabra a
  palabra mientras la otra persona habla, y es el propio modelo quien detecta cuándo
  terminó de hablar.
- **Sugiere respuestas** en streaming (aparecen token por token) con **GPT (OpenAI)**,
  GPT-6.1 sol para todo; solo cambia cuánto razona (poco al hablar, más con capturas).
- **Screenshot → GPT:** botón para mandar una captura de pantalla y preguntar (visión).
- **Invisible al compartir pantalla:** `SetWindowDisplayAffinity` (Windows 10 2004+/11).

## Requisitos

- Windows 10 (build 19041+) u 11.
- Python 3.10 u 3.11 recomendado.
- API key de **OpenAI** (se pone en la interfaz, en *Configuración*).
- API key de AssemblyAI para la transcripción en vivo (también en *Configuración*).

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

Es una herramienta de desarrollo, sin interruptor en Configuración: pon
`"test_mode": true` en `config.json` y pulsa *Iniciar*. No requiere la API key de OpenAI ni genera respuestas: solo
captura audio y transcribe **ambas** fuentes, etiquetadas, para verificar el montaje:

- `[REUNION] ...` → audio del sistema (pon un vídeo hablado)
- `[MICRO]   ...` → tu micrófono (habla)

Si ambas líneas aparecen con texto correcto, la captura y la transcripción funcionan.
La barra de estado muestra los milisegundos que tardó cada transcripción.
Desmárcalo y añade la API key para las sugerencias reales.

> En operación normal solo se transcribe el audio del sistema (lo que dicen los demás);
> tu micrófono es únicamente un medidor de nivel.

1. Abre **Configuración** y pega tus API keys de **OpenAI** y **AssemblyAI** (y, si
   la tienes, la de **TypeSafe**). Guarda.
2. Pulsa **Iniciar**.
3. Verifica que las barras **Reunión** y **Micro** se mueven con el audio.
4. Cuando alguien hable en la reunión, verás la transcripción **en vivo** y, cuando
   te pregunten algo, la **respuesta sugerida**.
5. **`Bloq Mayús+S`** captura la pantalla (puedes encadenar varias) y **`Bloq Mayús+D`** las manda.
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
- **Al modelo se le manda todo**: el agente en uso (el Coach lleva sus instrucciones
  en ES y EN) y *todos* los contextos activos, sin filtrar por idioma. El campo `Idioma` de
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
en voz alta. **Cuando hay código de por medio, cambia la estructura entera** y se
levanta el límite de brevedad:

| Sección | Qué trae |
|---|---|
| **Enfoque** | Cómo interpreta el problema y qué estrategia va a seguir, antes de escribir nada |
| **Solución** | El código completo y ejecutable, con **un comentario en cada línea** |
| **Cómo funciona** | Por qué funciona: el invariante, el orden, los casos borde |
| **Coste** | Tiempo y espacio en O(), y por qué sale eso |

En los dos casos, siempre en primera persona: lo que se lee es lo que tú dirías.

Ojo con los tokens: una solución comentada línea a línea ocupa mucho más que una
respuesta hablada. Por eso las capturas tienen su propio límite, 4000 (el de voz es
1000); con 1200 la respuesta se quedaba a medias.

### Atajos

Mantén **Bloq Mayús** y pulsa la tecla: todo queda junto a la mano izquierda en
reposo. Funcionan aunque el foco esté en Zoom, Meet o Excel, y no chocan con sus
atajos (Zoom usa Alt+A, Alt+S, Alt+Q…). Mientras la app corre, Bloq Mayús ya no
bloquea mayúsculas ni le llega a la aplicación de debajo; **`Shift+Bloq Mayús`** sí
las activa, como siempre.

| Atajo | Respaldo | Qué hace |
|---|---|---|
| `Bloq Mayús+A` | `Alt+5` | Responder ahora a lo último que dijeron |
| `Bloq Mayús+S` | `Alt+2` | Captura de pantalla (se pueden encadenar varias) |
| `Bloq Mayús+D` | `Alt+3` | Generar respuesta con las capturas tomadas |
| `Bloq Mayús+F` | `Alt+6` | Actualizar la solución en pantalla con lo que acaban de decir |
| `Bloq Mayús+Q` | `Alt+1` | Mostrar / ocultar el overlay |
| `Bloq Mayús+Esc` | `Alt+4` | Iniciar / detener la reunión (a propósito, difícil de pulsar sin querer) |

Todos menos `Bloq Mayús+F` tienen su botón en la barra superior con el atajo
escrito al lado (`Caps`); `Bloq Mayús+F` aparece como sugerencia en el panel de la
pantalla cuando aplica. Los `Alt+número` de antes siguen como respaldo, por si
Bloq Mayús está remapeada a otra tecla o Windows no deja instalar el hook.

### Dos paneles: hablado y pantalla

- **Sin pantallazos** hay un solo panel, el de la conversación hablada, en columna
  a la derecha: lo que dice el entrevistador y la sugerencia. Lo que dices tú no se
  pinta; va solo como contexto.
- **La primera captura** abre el panel de la pantalla a la derecha y pasa el hablado
  a la izquierda; el centro (la llamada, el editor) queda libre. Cada tanda de
  capturas se apila con su solución. El panel se cierra con su `×`.
- **Cada panel tiene su conversación con el modelo** (mismo modelo, caché compartida
  del principio): una solución de código larga no retrasa una respuesta hablada.
- **La solución en pantalla no se relanza sola.** Si el entrevistador dice algo que
  va para ella ("hay un error, hazlo así", "¿y qué cambiarías para…?"), Jev lo
  detecta y el panel ofrece `↻ Update with: «…» — Caps+F`. Lo decides tú; al
  aceptarlo, la solución se reescribe en su sitio, marcada como actualizada.

**Para desplazar el hilo basta con poner el cursor encima**, con la rueda del ratón
o con dos dedos en el panel táctil. Sigue el final según entra conversación, pero si
subes a releer algo se queda quieto hasta que vuelvas a bajar.

Con un ratón normal la rueda la intercepta un hook y el click-through se conserva
intacto. El gesto del **panel táctil** no viaja como rueda: Windows se lo entrega a
la ventana que hay bajo el cursor, y una ventana de cristal no cuenta — se lo pasa a
la de abajo. Por eso, **mientras haya conversación que desplazar**, el hilo pasa a
ser zona activa y los clics sobre él dejan de atravesar. Si no hay nada que
desplazar, todo sigue siendo de cristal como siempre.

**El cursor nunca cambia de forma sobre el overlay.** No es un descuido: la ventana
es invisible al compartir pantalla, pero el cursor no lo es. Si se convirtiera en
manita sobre un botón invisible, quien te viera compartiendo pantalla vería el
puntero transformándose sobre la nada, y el overlay se delataría solo.

### Cuándo responde (y cuándo no)

En una reunión la gente da mucho más contexto del que pregunta, así que responder a
cada frase llenaría el panel de ruido. Hay dos filtros antes de molestar a la IA:

1. **En tu equipo, gratis:** si la intervención no parece pregunta ni petición, ni se
   llama al modelo. El texto no se pierde — queda en el historial y será contexto de la
   próxima respuesta.
2. **El modelo:** lo que pasa el primer filtro puede seguir sin ser una pregunta ("y bueno,
   qué te digo…"). En ese caso el modelo se calla y no se pinta nada.

Si preguntaron y la transcripción se comió los signos, **`Bloq Mayús+A`** fuerza la respuesta.
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

## Rendimiento / latencia

**En vivo (AssemblyAI, por defecto).** El texto va apareciendo mientras la persona habla,
así que no se espera a que termine la frase. Medido con audio real del sistema: **76–84 ms**
desde la última palabra hasta el texto final. A eso se le suma la pausa de fin de turno
(0,7 s, fija) y el primer token del modelo de voz. Coste aproximado: **$0.45 por hora de reunión** — se factura el tiempo conectado,
no el audio enviado, y la conexión solo existe mientras la reunión está en marcha.

### Un modelo, dos niveles de razonamiento

Todo va con **GPT-6.1 sol**: un solo modelo para que la caché de prompt no se pierda al
pasar de una pregunta hablada a una captura. Lo único que cambia entre los dos usos
es **cuánto razona**:

| Uso | Qué manda | Razonamiento |
|---|---|---|
| **Preguntas habladas** | La latencia: la respuesta tiene que estar antes de que el silencio se note | `low` |
| **Capturas de pantalla** | La capacidad: suele haber código que resolver, y unos segundos de más no se notan porque estás leyendo | `medium` |

Cada uno con su **longitud máxima**, al tope: 1000 tokens las habladas y 4000 las
capturas. Es solo un techo —la longitud la marca el prompt y solo se paga lo que se
escribe—, y uno justo dejaba el código cortado a medias.

Nada de esto se configura: modelo, razonamiento, longitud, detección de turnos y
audio ya están decididos y medidos, y van fijos en el código (`config.FIJAS`). En
*Configuración* quedan tus claves (OpenAI, AssemblyAI y, opcional, TypeSafe), el
idioma, la opacidad, tus agentes y tus contextos.

Tiempos de GPT medidos desde este equipo (mediana de 5 llamadas, hasta la primera
palabra en pantalla): `gpt-5.4-mini` 0,7 s · `gpt-5.6-terra` 0,8 s ·
`gpt-5.6-luna` 1,2 s · `gpt-5.6-sol` 1,3 s. De **calidad** no hay medida, así que
las opciones no están ordenadas por «listas».

Ojo con los modelos GPT-5: razonan antes de responder y ese razonamiento gasta del
mismo presupuesto de tokens, así que `llm.py` reserva margen aparte para que el
límite de longitud siga refiriéndose a la respuesta y no llegue vacía.

## Agentes: quién te sopla

Un agente es una personalidad del coach con su system prompt **entero y editable**,
en *Configuración → Agentes*:

- **Instrucciones**: personalidad, tono, longitud, humor. Lo que pongas manda.
- **Reglas de funcionamiento**: cómo funciona la conversación (Ellos / Yo), el
  formato con secciones `##`, el código y las capturas. También se pueden cambiar,
  pero la app depende de ellas: tocarlas puede estropear cómo se pinta la respuesta.

Vienen cuatro de ejemplo: **Coach** (el de siempre), **Directo**, **Grok**
(ingenioso e irreverente, sin pasarse en una reunión) y **Senior técnico**. Uno
nuevo empieza como copia del Coach, para ver lo que ya hay y decidir qué cambiar;
*Restaurar* devuelve cada parte al texto de su agente de ejemplo. Se guardan como
`agents/<id>.json` junto a `config.json`.

El mismo agente responde en los dos paneles. Se elige en Configuración y, en plena
reunión, desde el selector de la cabecera del panel hablado: la conversación sigue
con todo lo hablado y la siguiente respuesta ya sale con el nuevo agente (esa
respuesta pierde una vez la caché, así que tarda un poco más). Los avisos de cada
turno ("responde a esto", "puedes callarte") los pone la app y no son del agente.

## Que suene a ti, no a documentación

El riesgo de un coach así no es que se equivoque: es que te haga sonar a máquina.
Si te sugiere *"y dejar el audit trail"* y el otro pregunta «¿el qué?», quedas
vendido por una palabra que no elegiste.

El prompt lo prohíbe explícitamente: nada de términos técnicos en inglés sueltos,
nada de palabras de manual (*idempotencia*, *trazabilidad*, *observabilidad*), y
una regla de oro — **no usar una palabra que no sabrías defender si te preguntan
qué significa**. Si el término hace falta de verdad, lo aclara en la misma frase
como quien lo explica de paso.

Medido con cuatro preguntas de entrevista, contando términos de jerga:

| | Jerga |
|---|---|
| Prompt anterior | 6 |
| Prompt actual | 1 |

Y el caso concreto, «¿cómo garantizarías atomicidad?»: antes decía *"usaría
restricciones de base de datos e **idempotencia**"*; ahora dice *"lo enviaría con
un proceso que registra que ya lo hizo, **para que un reintento no duplique el
efecto**"*. Lo mismo, dicho como lo diría una persona.

## El acta de cada reunión

Al detener la reunión se guarda la conversación completa en
`%APPDATA%\Armony\sesiones\` como markdown: lo que dijeron y lo que se te sugirió,
con el código incluido. Sirve para repasar después si las respuestas te sirvieron
y para afinar el prompt con casos reales en vez de con ejemplos inventados.

## Medir para poder mejorar

La cadena tiene muchos tramos —audio, transcripción, filtro, modelo, pintado— y
cuando algo va lento hace falta saber *dónde*. Cada tramo se cronometra y, al
detener la reunión, se guarda un informe en `%APPDATA%\Armony\metricas\`
(un `.json` y un `.txt` legible):

```
Reunion de 812.0 s
  proveedor: openai
  transcripcion: universal-3-5-pro
  voz: gpt-5.6-terra · capturas: gpt-5.6-sol

  medida                       n   mediana     p90     min     max
  extremo_a_extremo_ms        14     1389 ms   2010     980    2400
  llm_primera_palabra_ms      14      822 ms   1180     640    1400
  stt_latencia_ms             63      210 ms    340     120     520
  pintado_ms                 210        4 ms      7       2      14
```

El número que importa es **extremo a extremo**: de que terminan de preguntar a que
tienes la primera palabra en pantalla. Los demás sirven para saber a qué tramo
echarle la culpa cuando ese sube. En la cabecera del panel se ven en vivo los dos
principales: la transcripción y el total (⚡).

### El primer arranque

La primera petición al modelo siempre salía cara —resolver DNS, negociar TLS y
procesar por primera vez el prompt con tus contextos— y esa factura la pagaba tu
primera pregunta de la reunión. Ahora, al pulsar **Iniciar**, se manda una petición
mínima en segundo plano para calentar.

Medido con proceso nuevo cada vez, tiempo hasta la primera palabra:

| | 1ª pregunta de la reunión |
|---|---|
| Sin calentar | ~3,4 s |
| Calentando al iniciar | **~1,1 s** |

## Notas técnicas

- `audio.py` — captura WASAPI (loopback + micrófono), niveles y flujo continuo para el
  streaming.
- `stt_stream.py` — transcripción en vivo con AssemblyAI (WebSocket, reconexión automática).
- `intent.py` — decide si una intervención pide respuesta o solo está dando contexto.
- `richtext.py` — convierte el markdown del modelo en bloques (texto, código, listas).
- `metrics.py` — cronometra cada tramo y guarda el informe de la sesión.
- `secretstore.py` — cifra las API keys con DPAPI (atado a tu cuenta de Windows).
- `make_icon.py` — genera el icono «Ar.» en todos los tamaños que pide Windows.
- `llm.py` — cliente del coach con streaming y soporte de imagen (screenshot).
  OpenAI, API Responses.
- `overlay.py` — modo invisible a la captura de pantalla y click-through.
- `wheelscroll.py` — desvía la rueda del ratón al overlay cuando el cursor está
  encima. Hace falta porque el click-through (`WS_EX_TRANSPARENT`) vuelve la
  ventana transparente a *todo* el ratón, rueda incluida.
- `app.py` — interfaz (PySide6) y orquestación.
- `config.py` / `config.json` — ajustes (la API key se guarda localmente).

## Ideas a futuro

- El agente que se conecta a la videollamada y da soporte a clientes.
