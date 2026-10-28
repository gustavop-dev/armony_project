---
name: data-integrity
description: "Rastrea datos huérfanos, duplicados e inconsistentes de ProjectApp (clientes, proyectos, documentos, comunicaciones, contabilidad, propuestas y nombres) con el motor de integridad del Gestor de Proyectos, y los corrige por lotes que el operador aprueba, con registro y deshacer. Usar cuando el operador pide revisar, limpiar, ordenar o fusionar datos de un cliente, proyecto o propuesta, o un barrido completo. Por defecto sólo informa."
argument-hint: "[--client=<id|nombre>|--project=<id|nombre>|--proposal=<id>|--document=<id>|--thread=<id>|--all] [--domain=<lista>] [--rule=<ids>] [--apply] [--undo=<operación>] [--history]"
disable-model-invocation: true
---

# Data integrity — rastreo y corrección de datos de ProjectApp

Revisa los datos REALES de ProjectApp (producción) a través del Gestor de Proyectos y
entrega, en lenguaje llano, qué está mal, por qué y cómo se corrige. Las reglas viven en
el servidor: un catálogo fijo y versionado (`describe_integrity_rules`) que detecta
datos huérfanos, duplicados e inconsistentes en clientes, proyectos, documentos,
comunicaciones, contabilidad, propuestas y nombres. Esta skill no decide qué es un
error: lee los hallazgos del motor, los explica, pide decisiones y aplica sólo lo
aprobado.

- **Por defecto sólo informa.** `--apply` corrige por lotes que el operador aprueba uno
  por uno; las fusiones van de a una.
- **Todo queda registrado** en el servidor (antes/después, motivo, origen) y se deshace
  con `--undo=<operación>` mientras nadie haya tocado esos datos después.
- **Nunca borra.** Un duplicado se fusiona y el perdedor queda archivado; lo que no
  tiene corrección segura se informa para resolverlo a mano.
- **Sólo se invoca a pedido** (puede llevar a corregir datos de producción).

Referencias de esta skill:

- `references/frontera-seguridad.md`: qué escribe una lectura, qué nunca se toca y el
  respaldo previo.
- `references/catalogo-chequeos.md`: cada chequeo del inventario, con su regla,
  invariante, riesgo y vía.
- `references/verificacion.md`: la verificación independiente.

## Fase 0 · Guardas

1. **Aviso antes de la primera consulta**, con estas palabras: «cada consulta deja una
   línea de auditoría del MCP; no cambia ningún dato».
   - Cada llamada MCP graba una fila `McpRequestLog` en producción.
   - Una herramienta sensible crea además una intención de confirmación que vence a los
     10 minutos.
2. **Conector caído ≠ sin hallazgos.** Si el Gestor de Proyectos no conecta, lo que no se
   pudo medir queda **requiere validación**, con el conector como dato faltante.
3. **Antes del primer lote de correcciones en producción,** dos condiciones:
   - **La referencia de un respaldo verificado de la base y de la media**, que dispara el
     operador. La media entra porque las señales `post_delete` borran el archivo físico de
     una fila borrada. Esa referencia va en el `reason` de cada lote.
   - **La aprobación del lote en la conversación.**

   Sin las dos, sólo se informa.
4. **Canal alternativo de detección, sin MCP:** `manage.py audit_data_integrity` (sólo
   lectura; imprime ids de regla, conteos y `modelo:id`, nunca datos de clientes).
   - Lo corre **el operador** en el VPS, después del deploy.
   - Una sesión nunca corre comandos en un VPS.
   - Con `--coverage` resume el inventario de relaciones: qué regla mira cada relación,
     cuáles están exentas y los huecos conocidos.

## Requisitos (preflight)

1. Buscar con ToolSearch, **por nombre base** (el prefijo del conector cambia entre
   sesiones; nunca usar nombres con prefijo guardados), las herramientas del Gestor de
   Proyectos: `describe_integrity_rules`, `list_integrity_findings`,
   `preview_integrity_fixes`, `apply_integrity_fixes`, `list_integrity_operations`,
   `preview_integrity_operation_undo`, `undo_integrity_operation`, `confirm_action` y
   `cancel_action` (por ejemplo, query `+integrity` y luego `select:` con los nombres
   encontrados).
2. Si no aparecen: cerrar con `⏸️ data-integrity — el Gestor de Proyectos no expone el
   motor de integridad` y explicar las dos causas posibles: el conector no está
   conectado en esta sesión (o falló al conectar), o el cambio todavía no se desplegó.
   Codex no tiene ese conector configurado: misma salida.
3. Nunca reemplazar el motor leyendo listados de otros Gestores para "detectar a mano":
   las reglas son las del servidor.

## Cómo invocar este skill

Gating (protocolo [[_output-protocol]] §4):

1. Con argumentos explícitos → ejecutar directo, sin menú.
2. Intención clara en la conversación ("revisá los datos de Kore") → proponer el comando
   en texto (`/data-integrity --client=Kore`) y esperar confirmación.
3. Sin argumentos ni intención clara → UNA sola `AskUserQuestion` con estas dos
   preguntas:

| Pregunta | label · description · preview |
|---|---|
| Q1 ¿Qué revisar? | `Un cliente (Recommended)` · busca por nombre, empresa o correo · `/data-integrity --client=<nombre>` |
| | `Un proyecto` · busca por nombre · `/data-integrity --project=<nombre>` |
| | `Una propuesta` · pide el número · `/data-integrity --proposal=<id>` |
| | `Barrido completo` · toda la base, más lento · `/data-integrity --all` |
| Q2 ¿Qué hacer? | `Sólo informar (Recommended)` · no escribe nada · sin `--apply` |
| | `Informar y corregir` · escribe en producción, pide aprobación por lote · `--apply` |

Si Q1 pide un nombre que el operador no escribió, pedirlo en texto una única vez.

**Qué NO se pregunta:** `--undo=<operación>` (se tipea a propósito, con su número),
`--history`, y los filtros `--domain`/`--rule` (ajuste fino, se pasan si se quieren).
En Codex, renderizar las mismas filas como lista numerada y esperar la respuesta.

## Flujo

### 1. Alcance

- `--client` / `--project` con número → `scope_kind` + `scope_id`. Con texto →
  `list_integrity_findings` con `query.scope_query`: si devuelve `scope_candidates`,
  mostrar la lista numerada y pedir cuál (o, si no hay ninguno, decirlo y parar).
- `--proposal`, `--document`, `--thread` sólo con número. `--all` → `scope_kind=all`
  (las reglas marcadas "sólo barrido completo" corren únicamente ahí).
- `--domain=clients,projects,documents,communications,accounting,proposals,naming` y
  `--rule=CL1,PJ7` se pasan como `query.domains` / `query.rule_ids`.

### 2. Catálogo y detección

1. `describe_integrity_rules` una vez por corrida: guardar título, gravedad y
   `fixable_kinds` de cada regla para explicar los hallazgos.
2. `list_integrity_findings` con el alcance y los filtros; recorrer `page` hasta
   `pages`. Si hay más de 500 hallazgos, no paginar todo: resumir con `summary` y
   sugerir acotar con `--domain` o `--rule`.

### 3. Informe (el modo por defecto termina acá)

Para cada regla con hallazgos, en este orden (gravedad alta → baja):

- **Qué pasa**, en una o dos frases sin jerga (usar `message` y el título de la regla;
  nunca nombres de campos ni de tablas).
- **Ejemplos**: hasta 5, con los nombres de `subjects[].label`; si hay más, "y N más".
- **Cómo se corrige**, según `fix_kinds`/`fixable_kinds`:
  - corrección del motor (`relink`, `rename`, `reorder`, `sync_copy`, `archive`,
    `merge_clients`, `merge_folders`) → "se corrige con --apply"; si `inputs` tiene
    campos obligatorios, decir qué hay que decidir (destino, nombre nuevo, cliente que
    se conserva);
  - `existing_tool` → nombrar la herramienta de `tool` y su Gestor ("se corrige con
    otra herramienta, con su propia vista previa");
  - `report_only` → "se resuelve a mano" y dónde, si el mensaje lo dice.

Después, una sección **Observaciones** (opcional): anomalías que se noten al leer los
hallazgos y que ninguna regla cubre. Van marcadas como observación, nunca se corrigen
en esta skill y, si se repiten, se sugiere convertirlas en regla del catálogo.

### 4. Corregir (`--apply`)

Sólo si el operador lo pidió con sus palabras o tipeó `--apply`. Producción: cada
escritura pasa por vista previa y confirmación del servidor. Antes del primer lote, la
Fase 0: la referencia del respaldo verificado de base y media y la aprobación del lote
en la conversación.

**Orden de los lotes** (un lote = una regla; máximo 20 hallazgos por lote):

1. Mecánicas y reversibles sin decisión: NM1, reordenar (`reorder`), sincronizar copias
   (`sync_copy`).
2. Las que piden una decisión: re-vincular (`relink`), renombrar (`rename`), archivar
   (`archive`).
3. Fusiones (`merge_clients`, `merge_folders`): **de a una**, nunca en lote.
4. Las de `existing_tool`: de a una y sólo con aprobación individual.

**Por lote:**

1. Mostrar la lista numerada con la evidencia (nombres, valor actual → valor propuesto).
2. Pedir las decisiones que falten (`inputs`): opciones de `inputs[campo].options` en
   `AskUserQuestion` (máx. 4 por pregunta; si hay más, lista numerada en texto) y texto
   libre para nombres, ofreciendo `suggestion` cuando exista.
3. `AskUserQuestion`: `Aplicar el lote` · `Elegir registros` (pedir los números en
   texto) · `Saltar esta regla` · `Detener`.
4. `preview_integrity_fixes` con `scope` y `fixes` (`fingerprint`, `rule_id`,
   `fix_kind` si hay más de uno, `params`). Si `blocked`: mostrar los bloqueos en
   lenguaje llano, sacar del lote lo bloqueado y volver a previsualizar, o saltar.
5. `apply_integrity_fixes` con el mismo `scope` y `fixes`, `expected_impact_hash` de la
   vista previa, `reason` = "Aprobado por el operador: <regla> — <resumen corto> —
   respaldo <referencia>" y un
   `request_id` único por lote (por ejemplo `di-<AAAAMMDD>T<HHMM>-<regla>-<n>`) que se
   **reutiliza** si hay que reintentar ese mismo lote.
6. Responde `confirmation_required`: confirmar con `confirm_action` sólo si
   `impact.impact_hash` es el de la vista previa que el operador aprobó. Si difiere,
   `cancel_action` y volver al paso 4.
7. `STALE_VERSION` o `CONFLICT`: previsualizar una sola vez más y volver a preguntar.
   `CONFIRMATION_EXPIRED` (10 minutos): repetir desde el paso 4.
8. Anotar el `operation_id` del resultado.

**Fusiones** (una por pregunta): mostrar los clientes o carpetas del grupo, pedir cuál
se conserva y cuál se fusiona (ofrecer `suggestion` como Recommended), previsualizar
y mostrar del resultado: datos que se completan, **conflictos** (preguntar por cada
uno: valor del que se conserva o del duplicado, y repetir la vista previa con
`params.resolutions`), conteos por tipo de registro que se mueven, qué pasa con las
carpetas raíz, advertencias y bloqueos. Si un bloqueo sugiere invertir cuál se
conserva, ofrecerlo. Recién con todo resuelto: `AskUserQuestion` `Fusionar ahora` ·
`Cancelar`, y seguir los pasos 5-8.

**Sugerencias `existing_tool`:** mostrar la herramienta y sus argumentos; buscarla por
nombre base; usar primero su propia vista previa si existe y confirmar con el
operador. Quedan con el registro propio de esa herramienta: no se deshacen con
`--undo`, y el informe lo dice.

### 5. Verificar

Volver a correr `list_integrity_findings` con el mismo alcance y las reglas tocadas:
informar resueltos y pendientes, los `operation_id` aplicados y el comando exacto para
deshacer cada uno.

### 6. Verificación independiente (Fase 5)

Lo informado y lo corregido lo revisa un verificador fresco, según
`references/verificacion.md`.

- **Quién es:** un subagente de sólo lectura que no detectó ni corrigió nada.
- **Qué recibe:** sólo las afirmaciones con su fuente: regla, invariante con
  `archivo:línea`, canal, alcance e ids. Nunca datos de clientes.
- **Qué hace:** re-mide por el mismo canal e intenta refutar cada afirmación.
- **Veredictos:**
  - **confirmado**;
  - **requiere validación**, con el dato exacto que falta;
  - **rechazado**, con la razón.
- **Después de una corrección, comprueba tres cosas:**
  - la baja exacta de los ids esperados;
  - cero hallazgos nuevos en los chequeos vecinos;
  - huellas sin cambios en lo no tocado.
- **Sello:** su salida queda fuera del repo, sellada con `sha256sum`.

### `--undo=<operación>`

`preview_integrity_operation_undo` → mostrar qué vuelve a su valor anterior y los
bloqueos (`changed_since`: alguien cambió esos datos después; `already_reverted`;
`guard_changed`) → `AskUserQuestion` `Deshacer` · `Cancelar` →
`undo_integrity_operation` con `expected_impact_hash`, `reason` y `request_id` →
`confirm_action` → verificar como en el paso 5. Un deshacer es todo o nada por
operación.

### `--history`

`list_integrity_operations` (página 1, o `query.rule_id`): tabla con número, fecha,
tipo (corrección / deshacer), reglas, cantidad de cambios, motivo y si ya se deshizo.

## Prohibiciones

- Nunca llamar herramientas `delete_*` ni archivar clientes por fuera de una fusión del
  motor.
- Nunca saltarse `confirm_action` ni confirmar un impacto distinto del aprobado.
- Nunca agrupar fusiones en un lote, ni mezclar reglas en un mismo lote.
- Nunca reintentar con otro `request_id` sin revisar antes `--history`: el primero pudo
  haberse aplicado.
- Nunca copiar datos de clientes al repositorio, a commits ni a archivos locales: el
  registro durable vive en el servidor.
- Nunca correr comandos de base de datos ni `manage.py` desde una sesión, ni en un VPS
  ni desde un worktree contra el `.env` enlazado. El único camino de la sesión es el
  Gestor. `audit_data_integrity` lo tipea el operador.
- Nunca corregir inmutables, filas conservadas (salvo por su adopción), documentos
  emitidos ni lo firmado o aprobado: se informan (`references/frontera-seguridad.md`).
- El actor que queda registrado es el usuario técnico del conector; el `reason` deja
  constancia de que lo aprobó el operador.

## Acciones disponibles

Después del informe en modo sólo-informe, una sola `AskUserQuestion` (gating de §4 del
protocolo; nunca si el operador ya pasó flags):

| label · description · preview |
|---|
| `Corregir lo encontrado` · escribe en producción, aprobando cada lote · `/data-integrity <mismo alcance> --apply` |
| `Ver el registro` · lista las correcciones aplicadas y sus deshacer · `/data-integrity --history` |
| `Barrido completo` · toda la base, sólo informe · `/data-integrity --all` |
| `Deshacer una corrección` · pide el número de operación · `/data-integrity --undo=<operación>` |

## Output final

Sigue [[_output-protocol]]: el detalle por regla (§3 del flujo) va antes; al final:

1. Veredicto: `🟢 data-integrity OK` (sin hallazgos), `🟡 data-integrity — N hallazgos
   en <alcance>` (todo informado o corregido) o `🔴 data-integrity — <error>` si una
   llamada falló; `⏸️` sin conector.
2. Tabla de dimensiones, una fila por dominio con hallazgos (Clientes, Proyectos,
   Documentos, Comunicaciones, Contabilidad, Propuestas, Nombres) más, con `--apply`,
   filas "Corregido" y "Pendiente": ✅ sin hallazgos o corregido, ⚠️ con hallazgos,
   ℹ️ sólo informe, ❌ falló una llamada.
3. `## Next steps` con los comandos exactos (`/data-integrity --client=<id> --apply`,
   `/data-integrity --undo=<operación>`) y los pasos manuales de los `report_only`.
