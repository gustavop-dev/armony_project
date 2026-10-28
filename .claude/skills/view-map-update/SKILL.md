---
name: view-map-update
description: "Usar cuando se agregó, quitó, renombró o cambió de propósito una página, pestaña, modal o capacidad visible del frontend en un proyecto con Mapa de vistas (`/panel/views`), o cuando el operador pregunta si el mapa quedó desactualizado o pide auditarlo. [[implement]], [[new-feature-checklist]] y [[qa]] la invocan al cerrar un cambio. NO usar para cambios sólo de backend, estilos, refactors internos o tests sin efecto visible, ni para escribir specs E2E o responsivos (eso es [[qa]])."
argument-hint: "[--check|--apply] [--diff|--since[=<ref>]|--all] [<section-id>|<url-prefix>]"
---

# View Map Update — el Mapa de vistas al día

`/panel/views` muestra datos mantenidos a mano; el checker de CI sólo ve su
estructura. Esta skill actualiza todo lo que la vista muestra —y lo que fija ese
contenido en tests, contratos y docs— a partir de lo que cambió. `--check` es la
auditoría read-only (reemplaza a `view-map-audit`, que queda como alias).

## Qué muestra la vista y de dónde sale (layout de projectapp)

| Superficie | Fuente | Guardia |
|---|---|---|
| Lista y Mapa (secciones, grupos, entradas) | `frontend/config/viewCatalog.js` | `check:view-catalog` |
| Explorador (espacios → capacidades → features, relaciones) | `frontend/config/viewCapabilityCatalog.js` | `check:view-catalog` |
| Guía de referencias de propuestas | `proposalViewReferenceGuide` (`viewCatalog.js`) | `frontend/test/config/viewCatalog.test.js` |
| Etiquetas de filtros, badges, íconos de sección | `frontend/constants/viewMapFilterOptions.js`, `frontend/constants/viewBadgeMaps.js` | — |
| Íconos y actores válidos del Explorador | `frontend/components/platform/SidebarIcon.vue`, `actorNames` en `frontend/components/views/ViewExplorerContextPanel.vue` | — |
| Prosa fija | `frontend/pages/panel/views.vue`, `frontend/components/views/ViewOperationalExplorer.vue` | tests del mapa |
| Matriz responsiva derivada | `frontend/e2e/responsive/catalog-scenarios.js`, `frontend/config/responsiveAcceptance.js` | `check:responsive-contract` |

## Cómo invocar este skill

Gating ([[_output-protocol]] §4): (1) flags explícitos → directo, sin menú; sin
flag de modo = `--check`, sin flag de alcance = `--since`. (2) Intención clara
("actualizá el mapa de vistas") → proponer `/view-map-update --apply --since` en
una línea y esperar confirmación. (3) Sin argumentos ni intención → UNA
AskUserQuestion con Q1+Q2 (Codex: lista numerada, regla 8).

> **Invocada por [[implement]], [[new-feature-checklist]] o [[qa]]: NUNCA
> pregunta — hereda el gating del conductor (regla 4 de §4) y usa los flags que
> él pasa.** Nunca en fleet/headless/cron. Una corrida por diff: si la sesión ya
> la corrió sobre el mismo contenido, base y alcance, se cita ese resultado.
> Un nuevo cambio, aunque conserve los mismos nombres de archivo, exige revisión.

**Q1 — Modo** (`multiSelect: false`):

| label | description | preview |
|---|---|---|
| Actualizar (Recommended) | edita catálogo, Explorador, contratos y conteos en el worktree de sesión; no commitea | `/view-map-update --apply --since` |
| Sólo auditar | read-only: hallazgos priorizados + punch list | `/view-map-update --check --since` |

**Q2 — Alcance** (`multiSelect: false`):

| label | description | preview |
|---|---|---|
| Desde el último cambio del catálogo (Recommended) | lo tocado desde el último commit de los catálogos en la base | `--since` |
| Cambios de esta rama | rama de sesión contra su base + lo no commiteado | `--diff` |
| Todo el catálogo | cada entrada y cada nodo del Explorador; costoso | `--all` |

**Qué NO se pregunta:** `--since=<ref>` (se tipea cuando el último commit del
catálogo no dejó todo al día), el filtro `<section-id>|<url-prefix>` (acota
cualquier alcance) y el modo de una invocación encadenada.

## Reglas

- El catálogo sigue al código, nunca al revés.
- `--apply` escribe sólo en un worktree de sesión (`~/webapps/.wt/…`); nunca
  commitea ni pushea.
- La estructura (Fase 2) y los pins globales (Fase 4) valen en todo alcance; el
  alcance acota la semántica (Fase 3). Los ecos en docs (Fase 5) corren en
  `--since`/`--all`, y en `--diff` sólo si la corrida cambió conteos, secciones
  o espacios.
- Sin cambio de capacidad visible no hay edición: estilos, refactors u orden de
  columnas no reescriben textos.
- Cada URL vive en exactamente UN feature y todo feature tiene ≥1 URL: una
  capacidad nueva dentro de una página catalogada amplía `summary`/`value` del
  feature dueño (y `notes` de la entrada). Feature nuevo sólo con URL nueva;
  partir un feature, sólo standalone y con OK del operador.
- Valores válidos: `VIEW_AUDIENCES`/`VIEW_TYPES`, íconos de `SidebarIcon.vue`,
  actores de `actorNames`. Copiar la voz de las entradas hermanas; ningún
  conteo ni métrica inventados.
- Specs E2E/responsivos no se escriben acá: handoff a [[qa]] (capa e2e).
- Nunca se reescriben registros fechados (`tasks/active_context.md`, filas
  «Updated <fecha>» de `tasks/tasks_plan.md`, `docs/audits/`, `docs/reports/`)
  ni `docs/USER_FLOW_MAP.md` (generado).
- Tests: nunca la suite completa; ≤20 tests por batch, ≤3 comandos de test por
  ciclo; E2E no se corre acá.
- Encadenada, ante una duda de criterio: la opción conservadora, listada en
  «Decisiones» del reporte.

## Fase 0 — Preflight

Un comando por llamada; `<…>` va literal (tras `EnterWorktree`, Claude rechaza
sustituciones de comando, expansión de llaves y bucles).

```bash
ls frontend/config/viewCatalog.js frontend/config/viewCapabilityCatalog.js frontend/scripts/check-view-catalog.mjs
git rev-parse --show-toplevel
```

Falta un archivo → `⏭️` (sin mapa) o `🔴` si se renombró. En un worktree de
sesión, consultar su registro:

```bash
bash ~/webapps/vps-ops-toolkit/scripts/maintenance/session-worktree.sh status
```

En una auditoría `--check` desde el clon principal, resolver la base mediante
el proyecto canónico del registry (en projectapp, `projectapp`):

```bash
bash ~/webapps/vps-ops-toolkit/scripts/maintenance/resolve-work-coordinate.sh --check <proyecto>
```

Usar `base=` del worktree, o `resolved_branch=` del resolver para la auditoría;
una coordenada ambigua sin resolución detiene la comparación. `status` fuera
de un worktree retorna `2`: no significa que el mapa esté ausente.
`--apply` fuera de `~/webapps/.wt/` → crear el
worktree y entrar antes de escribir:

```bash
# pre-entry: corre en el clon principal, antes de EnterWorktree
bash ~/webapps/vps-ops-toolkit/scripts/maintenance/session-worktree.sh create chore view-map-refresh
```

## Fase 1 — Alcance

`<base>` es la base resuelta en Fase 0; nunca asumir `main` o `master`.

```bash
git fetch origin <base>
```

`--diff`:

```bash
git diff --name-status --find-renames 'origin/<base>...HEAD' -- frontend
git diff --cached --name-status --find-renames -- frontend
git diff --name-status --find-renames -- frontend
git ls-files --others --exclude-standard -- frontend
```

`--since`: la marca de agua `<W>` es el último commit de los catálogos EN LA
BASE (en tu rama, tu propio commit la movería); `--first-parent` evita que un
merge devuelva un commit lateral. `--since=<ref>` reemplaza `<W>`. Sin marca de
agua, revisar `--all`; si `<W>` no es ancestro de HEAD, detener la comparación y
usar una referencia común o `--all`. Deriva anterior a `<W>` → `--since=<ref>`
o `--all`.

```bash
git log -1 --first-parent --format=%H origin/<base> -- frontend/config/viewCatalog.js frontend/config/viewCapabilityCatalog.js
git merge-base --is-ancestor <W> HEAD
git diff --name-status --find-renames <W> HEAD -- frontend
git diff --cached --name-status --find-renames -- frontend
git diff --name-status --find-renames -- frontend
git ls-files --others --exclude-standard -- frontend
```

`--all`: todas las entradas, una sección por vez (subagentes read-only por
sección si el runtime los tiene; el conductor edita).

Candidatos: páginas de `frontend/pages/` agregadas, borradas, renombradas o
modificadas; componentes/composables/stores de las diferencias anteriores,
llevados a su página huésped con un salto (máx. dos). Deduplicar la unión de los
paths y leer su estado final: incluir renombres, bajas, cambios introducidos por
merges y archivos nuevos. Los mensajes de commit no deciden si una capacidad
cambió; un refactor o cambio visual sin efecto en la capacidad sigue excluido.

```bash
rg -l -e <NombreA> -e <NombreB> frontend/pages frontend/components
```

Para una baja o renombre, contrastar también la versión de la base o de `<W>`
con el catálogo para retirar la referencia anterior; no descartar el candidato
porque el archivo ya no existe. Leer el patch de los candidatos con `git diff`
y los archivos nuevos desde disco. La unión evita perder una edición preparada
o sin preparar sobre un archivo que también cambió en la rama.

Lo que importan >5 páginas (`components/base/`, `components/ui/`, composables
genéricos) es infraestructura. Encadenada, el contexto del conductor manda.

## Fase 2 — Estructura (global)

```bash
npm --prefix frontend run check:view-catalog
```

Alta/baja/renombre con los campos de `REQUIRED_VIEW_FIELDS`
(`frontend/config/viewCatalogAudit.js`), `url` = `routeFromPageFile(file)` y un
`group` existente de la sección; cada URL en exactamente un feature; sección
nueva → `sectionIds` de un espacio + ícono. Una página cuyo `<script setup>`
sólo hace `navigateTo(...)` es `viewType: 'redirect'`.

## Fase 3 — Semántica (alcance)

Por candidato, leer la página y sus hijos directos (título, pestañas, modales,
acciones primarias, `definePageMeta`, modos `?mode=`/`?tab=`) y contrastar:
- entrada: `label`, `reference`, `notes`, `group`, `viewType`, `audience`;
- feature dueño: `summary`, `value`, `actors`, `stage`, `icon`; capacidad,
  `relations` y `description` de la sección sólo si cambió el alcance;
- `proposalViewReferenceGuide` si cambiaron páginas o modos de propuesta.

En `--check` cada diferencia es un hallazgo: HIGH (estructura, URL sin
feature), MEDIUM (`viewType`/`audience`/`label`/`reference`), LOW (`notes`,
redacción, sección vs prefijo de URL — heurístico).

## Fase 4 — Contratos acoplados

**Pins globales (todo alcance, aunque no haya altas):** `visualCount`/
`redirectCount` en `frontend/scripts/check-responsive-contract.mjs` (lo valida
`check:responsive-contract`); celdas de la corrida completa en
`frontend/scripts/run-responsive-changed.mjs` = entradas × anchos de
`PANEL_VIEWPORTS` (`frontend/config/responsive.js`), que ningún checker valida;
"N vistas relacionadas" en `frontend/test/components/ViewOperationalExplorer.test.js`.

| Si cambió… | Actualizar |
|---|---|
| URL sin dueño responsivo | prefijo en `responsiveOwnerForView` (`frontend/config/responsiveAcceptance.js`) |
| Redirect | `REDIRECT_DESTINATIONS`, `REDIRECT_FLOW_BY_URL` y, si no es `success`, `REDIRECT_OUTCOME_BY_URL` (`catalog-scenarios.js`) |
| Parámetro dinámico nuevo | placeholder en `resolveCatalogUrl` (`catalog-scenarios.js`) |
| Tipo o audiencia nuevos | etiqueta en `viewMapFilterOptions.js`; badge y barra en `viewBadgeMaps.js` |
| Nodos, orden o `secondary` del Explorador | pins en `viewCapabilityCatalog.test.js`, `ViewOperationalExplorer.test.js`, `frontend/test/composables/useViewMapMode.test.js`, `frontend/e2e/admin/admin-view-map.spec.js` |
| Espacios | prosa de `views.vue` y `ViewOperationalExplorer.vue`; `summary` raíz |
| `viewType` hacia/desde `list`, o verbos de acción en label/group/reference | recalcula `defaultCapabilities` del escenario: anotarlo en el handoff |
| Página visual nueva | su escenario en `frontend/e2e/responsive/<dueño>.spec.js` → **handoff a [[qa]]**, no se escribe acá |

## Fase 5 — Ecos en docs vivos

```bash
rg -n -e viewCatalog -e viewCapabilityCatalog -e /panel/views -e admin-view-map -e celdas docs/methodology docs/RESPONSIVE_QA_TEST_SCRIPT.md docs/user-flows/_preamble.md
```

Leer ±5 líneas por hit y corregir cada afirmación con número (cifra o palabra)
sobre vistas, secciones, espacios, módulos o celdas —incluida la tabla
Dueño/Vistas del guion responsivo—; preferir redacción sin conteo. Si se tocó
`docs/user-flows/`, regenerar con `npm --prefix frontend run flow:registry`.

## Fase 6 — Validación

```bash
npm --prefix frontend run check:view-catalog
npm --prefix frontend run check:responsive-contract
npm --prefix frontend run flow:registry:check
ls frontend/node_modules/.bin/jest
npm --prefix frontend ci
npm --prefix frontend test -- test/config/viewCatalog.test.js test/config/viewCapabilityCatalog.test.js
npm --prefix frontend test -- test/components/ViewOperationalExplorer.test.js
npm --prefix frontend test -- test/composables/useViewMapMode.test.js
```

`--check`: sólo los dos checkers. `--apply`: checkers siempre;
`flow:registry:check` si tocó `docs/user-flows/`; `npm ci` sólo si falta jest;
batch 1 si cambió un catálogo, batch 2 si cambiaron el total o los nodos,
batch 3 si cambiaron ids u orden de nodos. El E2E del mapa corre en CI.

## Fase 7 — Cierre

Standalone: reporte + menú (commit y PR vía [[pr-green]]). Encadenada: devolver
tabla, «Decisiones» y handoffs; el conductor commitea.

## Errores comunes

| Error | Corrección |
|---|---|
| "check:view-catalog verde ⇒ mapa al día" | el checker no lee semántica: Fase 3 |
| Feature nuevo para una capacidad dentro de una página catalogada | ampliar el feature dueño (URL única) |
| Marca de agua con `git log` sobre tu rama | se mueve con tu propio commit: calcularla en `origin/<base>` |
| Pins sólo revisados cuando hay altas | los pins pueden estar viejos de antes: Fase 4 es global |
| Reescribir textos por un refactor o por estilos | sin capacidad visible nueva no hay edición |
| Escribir el spec responsivo de la página nueva | handoff a [[qa]]; acá sólo datos y conteos |
| Editar `docs/USER_FLOW_MAP.md` o "corregir" historia | `docs/user-flows/` + `flow:registry`; historia intacta |

## Acciones disponibles

Tras el reporte, si la sesión es interactiva y NO hubo flags explícitos
(reglas de gating de [[_output-protocol]] §4), ofrecer vía AskUserQuestion:

| Opción (label) | description (costo/efecto) | preview (comando exacto) |
|---|---|---|
| Aplicar los ajustes (Recommended) | escribe en el worktree de sesión; no commitea | `/view-map-update --apply --since` |
| Revisión completa | cada entrada y nodo del Explorador; costoso | `/view-map-update --check --all` |
| /pr-green | commit + push + PR + CI verde; no mergea | `/pr-green` |

## Output final

Reportar siguiendo [[_output-protocol]]. En `--check`, entre el veredicto y la
tabla va `### Punch list` (HIGH→LOW, una línea `archivo:línea → cambio`).

```markdown
🟡 view-map-update OK con 1 warning(s) — --apply --since <sha>

| Dimensión | Estado | Detalle |
|---|---|---|
| Alcance | ✅ | base/marca `<sha>` · M entradas candidatas, incluidos cambios locales |
| Estructura (Lista/Mapa) | ✅ | check:view-catalog verde · +A −B ~C entradas |
| Semántica de entradas | ✅ | N entradas ajustadas |
| Explorador | ✅ | N features ajustados · cada URL en un feature |
| Contratos acoplados | ✅ | check:responsive-contract verde · pins al día |
| Tests de datos | ✅ | jest N/N en ≤3 comandos (⏭️ en --check) |
| Docs vivos | ✅ | N afirmaciones corregidas · historia intacta |
| Handoffs | ⚠️ | 1 escenario responsivo sin spec → /qa --layers=e2e |

## Next steps
- `/qa --layers=e2e` — cubrir el escenario responsivo de <página>
```

Veredicto: 🟢 todo ✅/⏭️ · 🟡 handoffs, «Decisiones» a revisar o hallazgos de
`--check` · 🔴 checker o test rojo tras editar · 🚫 `--apply` sin worktree ·
⏭️ sin mapa o nada en el alcance.
