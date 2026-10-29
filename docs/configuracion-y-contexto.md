# Meeting Coach — Configuración y Sistema de Contexto

Documento de referencia para diseño. Dos partes:
1. Detalle completo de los ajustes actuales de configuración.
2. Especificación del sistema de contexto (a implementar).

---

# Parte 1 — Ajustes de configuración (estado actual)

Todos los ajustes viven en `config.json` y se editan desde el diálogo de
Configuración (⚙ en la barra superior). Están agrupados en 5 secciones visibles
más un ajuste interno todavía no expuesto.

La columna **Clave** es el nombre técnico en `config.json` (útil para diseño y
desarrollo).

## 🔌 Conexión

| Clave (`config.json`) | Etiqueta UI | Tipo | Valores / Rango | Default | Qué hace |
|---|---|---|---|---|---|
| `openai_api_key` | API key de OpenAI | Texto (oculto) | `sk-proj-...` | *(vacío)* | Credencial del modelo de respuestas. Sin ella no arranca la reunión (salvo Modo prueba). |
| `openai_model` | *(no visible)* | Fijo | `gpt-6.1-sol` | `gpt-6.1-sol` | Un único modelo para voz y capturas: la caché de prompt es por modelo. |
| `openai_effort_voice` | Razonamiento · preguntas habladas | Desplegable | `low`, `medium`, `high` | `low` | Cuánto razona en las preguntas habladas. Manda la latencia. |
| `openai_effort_vision` | Razonamiento · capturas de pantalla | Desplegable | `low`, `medium`, `high` | `medium` | Cuánto razona con capturas, donde suele haber código. |
| `language` | Idioma | Desplegable | `es`, `en`, `auto` | `es` | Idioma del reconocimiento de voz. `auto` = detección automática. |

## 🪟 Overlay

| Clave | Etiqueta UI | Tipo | Rango | Default | Qué hace |
|---|---|---|---|---|---|
| `invisible_on_share` | Invisible al compartir pantalla | Casilla | on/off | `on` | Excluye el overlay de cualquier captura o compartición de pantalla. |
| `test_mode` | Modo prueba | Casilla | on/off | `off` | Arranca sin API key: solo audio + transcripción, sin generar respuestas. |
| `window_opacity` | Opacidad | Numérico | 0.15 – 1.0 (paso 0.05) | `0.65` | Transparencia de las ventanas del overlay. Bajo = se ve más el fondo. |

## 🎙️ Sensibilidad de audio

| Clave | Etiqueta UI | Tipo | Rango | Default | Qué hace |
|---|---|---|---|---|---|
| `gain_system` | Ganancia reunión (x) | Numérico | 0.5 – 10.0 (paso 0.5) | `1.0` | Amplifica el audio del sistema antes de medir nivel y transcribir. |
| `gain_mic` | Ganancia micrófono (x) | Numérico | 0.5 – 10.0 (paso 0.5) | `1.0` | Amplifica tu micro. Ojo: amplifica también el ruido de fondo. |
| `listen_mic` | Escuchar mi micrófono | Casilla | on/off | `on` | Transcribe tu voz en un segundo stream (~0,45 USD/h). Nunca genera respuestas: sirve para saber que ya contestaste y no ponerte otra respuesta encima. Pensado para usar con auriculares. |

## ✂️ Detección de frases

| Clave | Etiqueta UI | Tipo | Rango | Default | Qué hace |
|---|---|---|---|---|---|
| `silence_hang` | Pausa de fin de turno (s) | Numérico | 0.3 – 2.0 (paso 0.1) | `0.7` | Pausa que se espera tras un turno cerrado antes de responder; agrupa las frases seguidas de una misma intervención. Bajo = reacciona antes pero puede responder a media intervención. |

## 🧠 Coach

| Clave | Etiqueta UI | Tipo | Default | Qué hace |
|---|---|---|---|---|
| `system_prompt` | Prompt del coach | Texto multilínea | *(persona base en español)* | Define **cómo** se comporta la IA: tono, formato, reglas. No define *qué sabe* (para eso está el sistema de contexto). |

## ⚙️ Interno (aún no expuesto en la UI)

| Clave | Tipo | Default | Qué hace |
|---|---|---|---|
| `max_tokens` | Numérico | `400` | Longitud máxima de la respuesta de la IA. |

## Notas de comportamiento

- Cambiar **Modelo** o **Dispositivo STT** requiere Detener e Iniciar la reunión
  de nuevo (se cargan al arrancar).
- **Opacidad** e **Invisible al compartir** se aplican en caliente.
- El resto de ajustes de audio/frases se aplican al iniciar la siguiente reunión.

---

# Parte 2 — Sistema de Contexto (especificación)

## Concepto

Documentos **markdown con nombre** que la IA lee al **iniciar la reunión** para
personalizar sus respuestas. Se pueden crear **varios** y activar los que apliquen
en cada reunión.

Diferencia clave con el "Prompt del coach":

| | Prompt del coach | Contextos (nuevo) |
|---|---|---|
| Define | **CÓMO** responde (tono, formato, reglas) | **QUÉ sabe** (datos, hechos, conocimiento) |
| Cantidad | Uno | **Varios**, combinables |
| Cambia | Rara vez | Por reunión / cliente / producto |

### Ejemplos de contextos

- **Sobre mí** — tu rol, experiencia, forma de hablar.
- **Producto X** — features, precios, FAQ del producto que das soporte.
- **Cliente Acme** — datos de esa cuenta, historial, tono acordado.
- **Objeciones comunes** — cómo responder a quejas típicas.

En una reunión activas los que apliquen (p. ej. *Sobre mí* + *Producto X* +
*Cliente Acme*) y la IA responde sabiendo todo eso.

## Modelo de datos (propuesta)

Cada contexto = un archivo `.md` en una carpeta `contexts/`, con cabecera de
metadatos (frontmatter YAML):

```markdown
---
name: Producto X
active: true
---

# Producto X
Precios: plan básico $9/mes, pro $29/mes...
Integraciones: Slack, Zapier, API REST...
```

- **Carpeta:** `contexts/*.md` (un archivo por contexto).
- **Metadatos:** `name` (nombre visible) y `active` (si se carga en la próxima reunión).
- **Ventajas:** editables a mano, versionables, portables; encajan con la idea de
  "sistema de contexto en markdown".

## Mecánica de inyección en la IA

Al pulsar **Start meeting**, se concatenan los contextos activos y se anteponen al
system prompt del coach:

```
[Prompt del coach: cómo comportarse]
+
# Contexto de esta reunión
[contenido de "Sobre mí"]
[contenido de "Producto X"]
[contenido de "Cliente Acme"]
```

Esto se envía como `instructions` en la llamada a la API Responses de OpenAI.

**Impacto en la latencia (<2 s):** como el contexto es estable durante toda la
reunión, puede aprovecharse el *prompt caching* de OpenAI (automático a partir de 1.024
tokens de prefijo estable). Cuánto se cachea de verdad se mide y se mejora en
`docs/plan-live-turns-openai.md` (fase 4). El contexto se **congela al iniciar** la reunión para no
romper el caché a media llamada.

## Requisitos de la UI (para diseño)

1. **Lista de contextos** — cada uno con: nombre, interruptor activo/inactivo, y
   acciones (editar, duplicar, borrar). Estilo "lista de perfiles".
2. **Editor** — campo de nombre + área de texto markdown grande. Opcional: vista
   previa del markdown renderizado.
3. **Selección de activos** — casillas por contexto: cuáles se cargan en la próxima
   reunión. Se pueden activar varios a la vez.
4. **Indicador en el overlay** — chip discreto tipo *"3 contexts loaded"* al iniciar,
   para saber que la IA tiene el contexto cargado.
5. **Contador de tokens / aviso** — mostrar cuánto "pesa" cada contexto; si el total
   es muy grande, avisar (afecta costo y algo la latencia de la primera respuesta).
6. **Ubicación** — como se planea añadir más cosas, se recomienda **ventana o sección
   propia "Contexts"**, separada de los ajustes técnicos.

## Casos límite

- **Sin contextos activos** → funciona como ahora (solo el prompt del coach).
- **Contexto vacío** → se ignora.
- **Contexto muy grande** → aviso de tokens; quizá un límite blando por contexto.
- **Editar durante una reunión** → los cambios aplican en la *siguiente* reunión
  (el contexto se congela al iniciar).

## Decisiones abiertas (a definir antes de implementar)

- ¿Los contextos activos se recuerdan entre reuniones, o se eligen cada vez?
- ¿Un contexto puede marcarse como "siempre activo" (p. ej. *Sobre mí*)?
- ¿Agrupar/etiquetar contextos (por cliente, por producto)?
- ¿Import/export de contextos (compartir entre máquinas o con el equipo)?

---

*Documento generado para la fase de diseño de Meeting Coach.*
