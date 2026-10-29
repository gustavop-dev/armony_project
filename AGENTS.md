<!-- Edit shared project guidance in CLAUDE.md; edit only codex-specific here. -->
<!-- fleet-base:begin v=2 -->
# AGENTS.md — Armony (`armony_project`)

Codex descubre estas instrucciones desde la raiz del repo. Las skills viven en `.agents/skills/`, los agentes especializados en `.codex/agents/`, y modelo, sandbox y aprobaciones se heredan de `~/.codex/config.toml`.

Esta seccion es la **base comun del fleet** y se sincroniza desde
`vps-ops-toolkit/workflows/.claude/base/CLAUDE.md.tmpl`. No editar manualmente:
los cambios se pierden en el proximo sync. Para customizar este proyecto, usar
el bloque `project-shared` mas abajo.

## Convencion de lenguaje

- Codigo, identificadores y nombres de variable: **ingles**.
- Mensajes de commit: **ingles** (Conventional Commits).
- Docs operativos, skills y reportes: **espanol** (terminos tecnicos en ingles donde son de uso corriente).
- Mensajes de error visibles al usuario final: idioma del proyecto.

<!-- progress-estimate-protocol:begin -->
## Avance teórico en cada respuesta

Rige para Claude Code y Codex en cualquier repo o directorio: toda respuesta al
operador termina con una línea que estima cuánto va de la tarea en curso.

`📊 Avance ▰▰▰▰▰▰▱▱▱▱ 60 % (antes 45 %) — falta: tests del parser y PR`

- **Barra de 10 bloques:** un `▰` por cada 10 % completo (se trunca: 95 % muestra
  nueve) y `▱` para el resto; después, el número exacto.
- **100 % = la tarea cerrada como la pidió el operador**, con su definición de
  terminado (repo de proyecto: PR abierto + CI verde; `vps-ops-toolkit`: commit
  pusheado y propagado). Un número por tarea; con varios frentes, uno global.
  Si el alcance cambia, se re-ancla y se dice.
- **Estimación, no métrica:** sale del trabajo que falta (pasos y su peso), no del
  tiempo transcurrido. No se guarda en memoria, ledgers ni reportes, ni se vuelve
  objetivo.
- **Puede bajar o saltar.** Trabajo nuevo (un test rojo, un bloqueo, más alcance)
  la baja y `falta:` dice por qué; un salto grande se reporta tal cual.
  `(antes N %)` sólo cuando cambió desde la respuesta anterior.
- **100 % sólo con el cierre verificado.** Una pregunta contestada en un turno
  cierra en 100 %; esperar una decisión del operador no mueve el número — el
  bloqueo va en `falta:`.
- **Dónde va:** última línea. Si una skill fija su última línea (un veredicto,
  `Report path:`), va justo antes de esa. Nunca dentro de un texto para copiar
  (correo, WhatsApp, commit, body de PR, documento), en la respuesta de un
  subagente a quien lo lanzó, ni en una salida que lee un programa (headless,
  JSON, bloques `STATUS:`).
<!-- progress-estimate-protocol:end -->

<!-- session-start-protocol:begin -->
## Session Start Protocol

Al inicio de **cada sesión y antes de editar archivos**, ubicate: el hook te dice DÓNDE arrancaste y esta sección qué se hace ahí. Razón: N sesiones en paralelo comparten el clon principal, que es el checkout del servicio/deploy — editarlo o "sincronizarlo" con stash/rebase pisa el trabajo de los demás.

**Flujo:**
1. Un hook `SessionStart` (definido en `~/.codex/hooks.json`) ejecuta `git fetch + git status` read-only y te inyecta `[session-start] <repo> @ <rama> | behind=N ahead=M dirty=D | tree=main-clone|worktree:<slug>`.
2. **Arrancaste en el clon principal (`~/webapps/<repo>`)** → NO invoques `$git-sync`, digan lo que digan `behind`/`dirty`. Acá sólo hacés lectura y `git fetch` (lista canónica completa en la sección 1 del protocolo siguiente). `dirty>0` es trabajo de otra sesión: reportalo como anomalía y no lo toques (ni stash, ni reset, ni checkout — el hook guard lo bloquea igual). Para modificar archivos, creá tu worktree de sesión desde `origin/<BASE>` (sección 5 del bloque siguiente) y ENTRÁ en él.
3. **Arrancaste en / entraste a tu worktree (`~/webapps/.wt/<repo>/<slug>`)** → `behind>0` contra su upstream ⇒ invocá `$git-sync` (absorbe la base movida con merge, nunca con rebase). `dirty>0` es tu propio trabajo en curso; `ahead>0` se resuelve con el commit+push normal.
4. **Sesión de sólo lectura** (revisar, diagnosticar, responder) → quedate en el clon principal; no hace falta worktree.

**Importante:** Nunca uses `git pull --force`, `git reset --hard` ni stash automático; en el clon principal de un repo del fleet, ni siquiera `$git-sync` — ahí sólo lectura + `fetch` (lista canónica en la sección 1). La rama de deploy del clon principal la mueve el operador/deploy, no una sesión.
<!-- session-start-protocol:end -->

<!-- git-branch-protocol:begin -->
## Reglas de trabajo con Git: ramas, worktrees y commits (protocolo por sesión)

**Nunca hagas commits directamente sobre `main`/`master`, sobre una rama release, ni sobre la rama de OTRA sesión, y nunca mergees: el merge no es de la sesión.**

**El modelo es 1 sesión = 1 rama = 1 worktree = 1 PR, y el trabajo se ENTREGA como PR abierto con CI verde (sección 10).** Cada sesión crea SU rama al arrancar trabajo, en SU git worktree, y abre el PR en el primer push con dueño e intención declarados. Está PROHIBIDO reutilizar la rama de otra sesión o acumular trabajo de varias tareas en una rama compartida — eso produce ramas con N dueños, archivos contaminados con hunks ajenos y merges imposibles de ordenar (medido en el fleet el 2026-08-16). El drenaje ordenado de vuelta a la base lo hace `$merge-queue` o el operador a mano: una sesión nunca mergea su propio PR. Antes de cualquier `git commit`, seguí este protocolo:

### 0. (Fleet) Confirmá la coordenada: host + base de integración

Si este repo pertenece al fleet `vps-ops-toolkit` (existe `~/webapps/vps-ops-toolkit/projects.yml`), la **fuente de verdad de dónde se trabaja y sobre qué BASE se corta tu rama** es `projects.yml` validado contra los PRs abiertos:

```bash
# pre-entry: corre en el clon principal, antes de EnterWorktree
OPS=~/webapps/vps-ops-toolkit
RESOLVER="$OPS/scripts/maintenance/resolve-work-coordinate.sh"
# OJO worktrees: el nombre del proyecto sale del git-common-dir (el clon
# principal) — en un worktree, el toplevel es ~/webapps/.wt/<repo>/<slug>.
PROJ=$(basename "$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")")
[[ -x "$RESOLVER" ]] && bash "$RESOLVER" --check "$PROJ"   # imprime vps_work, resolved_branch, pr_state, host_status, matches_yml
```

Si YA estás dentro de tu worktree (Claude, después de `EnterWorktree`) ese bloque compuesto se rechaza: pedí el mismo dato —y el resto de la coordenada— con **un** comando simple, que además resuelve el proyecto solo:

```bash
bash ~/webapps/vps-ops-toolkit/scripts/maintenance/session-worktree.sh status
```

- **`host_status=wrong-host`** → **PARÁ**. El trabajo de este proyecto va en OTRO clon (el `vps_work` que imprime el resolver — p.ej. kore se trabaja en el clon de `vps-projectapp-staging`, no en el de producción). Avisá al operador antes de tocar nada acá.
- **`BASE` de tu rama de sesión**: con `pr_state=single` (repo con release activa) la base es **`resolved_branch`** — tu rama sale DE la release y tu PR apunta A la release (modelo stacked; la release mantiene su propio PR hacia `main`/`master`, gateado por `release_merge`). Con `prod-direct`/`no-pr`, la base es la default (`main`/`master`). **NUNCA hagas checkout de la release ni commitees en ella** — la release sólo recibe trabajo vía PRs de sesión.
- **`matches_yml=no`** (el candidato a release difiere del registrado, p.ej. la release anterior se mergeó y hay otra) → avisá al operador; puede que haya que refrescar `projects.yml` con `bash "$RESOLVER" --apply "$PROJ"` en el toolkit.
- **`branch_deploy_status=yml-stale`** (el clon acá ya está en la rama nueva y el `branch:` de projects.yml quedó viejo) → avisá y refrescá el yml con `bash "$RESOLVER" --fix "$PROJ"` (desde el toolkit). NUNCA hagas checkout de la rama vieja del yml sobre el clon. Si es `unbacked` o `server_status` marca host ajeno → derivar a `migrate-project` / revisión manual, sin auto.
- **Sin toolkit, o el proyecto no está en `projects.yml`** → base = `main`/`master` y seguí con la sección 1.

### 1. Dónde estás parado determina qué hacés

```bash
git rev-parse --show-toplevel
```

- **Bajo `~/webapps/.wt/<repo>/<slug>`** → estás en un worktree de sesión. **TUYA** = la rama la creaste vos en esta sesión, o en un turno anterior de la MISMA sesión; en duda, `session-worktree.sh list` o la línea `Sesión:` del body del PR. Si es TUYA: commiteá (sección 8). Si es de otra sesión: no toques nada — creá el tuyo (sección 2).
- **En el clon principal (`~/webapps/<repo>`)** → **acá no se edita ni se commitea**: es el checkout del servicio/deploy. **Lista canónica de lo permitido acá — la única del protocolo, el resto de las secciones apunta a esta:** `git status/log/diff/fetch`, `git worktree list/add/remove` (operan sobre el registro de worktrees, no sobre el checkout) y `git pull --ff-only` (el único pull que el hook no deniega; igual la rama de deploy la mueve el operador/deploy, no una sesión). Todo lo demás está prohibido: `git checkout`/`switch`, `git commit`/`add`, `git stash`, `git reset`, `git merge`/`rebase`, `git pull` sin `--ff-only` y borrar `node_modules`. Un hook `PreToolUse` deniega esas operaciones —y `Edit`/`Write`— en el clon principal de un repo del fleet; **no** intercepta las escrituras que el shell hace por otras vías (`sed -i`, heredocs, redirecciones) y no corre donde no esté instalado: la regla aplica igual. Creá tu worktree (sección 2) y trabajá allá.
- **Guard del cwd para las herramientas de archivos**: `Read`/`Edit`/`Write` resuelven las rutas contra el cwd de la sesión, y el archivo de instrucciones del repo (`CLAUDE.md`/`AGENTS.md`) se descubre desde ahí — si te quedás en el clon principal editás el clon principal aunque "tengas" un worktree. Por eso, una vez creado, ENTRÁ en él:
  - **Claude Code:** herramienta nativa `EnterWorktree` con `path=$HOME/webapps/.wt/<repo>/<slug>` — funciona con un worktree creado por `git worktree add` y la primera vez pide aprobación porque la ruta está fuera de `.claude/worktrees/`: aceptala. Desde ahí toda ruta relativa y todo comando corren en el worktree. `ExitWorktree` **no** borra un worktree entrado por `path=`; el retiro es `session-worktree.sh remove <slug>` (sección 5).
  - **Codex:** no tiene worktrees nativos — `cd` al worktree y ejecutá TODO comando posterior con ese directorio como workdir; las rutas absolutas apuntan al worktree, nunca a `~/webapps/<repo>`.
  Antes de escribir, confirmá que `git rev-parse --show-toplevel` cae bajo `~/webapps/.wt/`.
- **Post-`EnterWorktree` (Claude): UN comando simple por llamada.** Adentro de un worktree nativo, Claude inspecciona el **string literal** del comando antes de correrlo y rechaza dos familias enteras — se cae el bloque completo, no la línea:
  - **Forma** ("too complex to verify that it stays inside the worktree"): sustitución de comando `$(...)`, expansión de llaves `{a,b}`, un `for`/`while`, o un heredoc cuyo cuerpo tenga sustitución. **Sí** pasan el comando simple, el pipe `|`, las cadenas `&&`/`||` de comandos simples y `gh … -q '<jq>'`.
  - **Destino**: `git -C <el clon principal de este worktree>` y `cd <el clon principal>` (el subshell no ayuda). Leer el clon principal (`ls`, `cat`, `Read`) sí se permite, y `git -C <OTRO repo>` también. `Edit`/`Write` sobre una ruta del clon principal se rechazan: editá la copia del worktree.
  Consecuencia práctica: **no computes valores en bash**. Pedí UN registro con `bash ~/webapps/vps-ops-toolkit/scripts/maintenance/session-worktree.sh status` — imprime `project repo main_clone worktree branch default_branch resolved_branch registered_branch deploy_branch open_pr pr_state_coord release_merge host_status base pr_number pr_state pr_url ci dirty unpushed upstream in_base age_h locked verdict` — leelo y escribí esos valores **literales** en las llamadas siguientes (`gh pr create --base <base>`, `gh pr checks <n>`, …). Los bloques que corren ANTES de entrar (sección 5: crear la rama y el worktree desde el clon principal) no tienen este límite.
- **Regla compartida**: toda skill que escriba en el repo (tests, docs, configs, memoria de metodología, reportes) hereda esto — escribe en el worktree de la sesión y, si no existe, lo crea primero (sección 5). Ninguna skill necesita repetirlo.

### 2. Arrancando trabajo nuevo: SIEMPRE tu propia rama + worktree

No busques ramas abiertas para reutilizar — **cada sesión corta la suya** desde la BASE de la sección 0 (comandos exactos en la sección 5). Una rama de otra sesión nunca se reutiliza, ni "para un cambio chico"; la única excepción es un pedido explícito del operador. Si tu sesión YA tiene su rama/worktree de un turno anterior, seguí usándolos — pero entrá al worktree primero (sección 1): un turno nuevo arranca en el clon principal. Tu trabajo en curso se acumula en TU rama.

### 3. Formato obligatorio del nombre de rama

`<prefijo>/<DDMMYYYY>-<descripcion-corta>`

- **`<prefijo>`** según el tipo de cambio:
  - `feat` — nueva funcionalidad
  - `fix` — corrección de bug
  - `docs` — cambios en documentación
  - `refactor` — refactorización sin cambio funcional
  - `test` — añadir o modificar tests
  - `chore` — mantenimiento (dependencias, configs)
  - `style` — formato/estilo, sin cambio de lógica
  - `perf` — mejoras de rendimiento
  - `ci` — cambios en workflows o pipelines
  - `hotfix` — corrección urgente en producción

- **`<DDMMYYYY>`** debe ser la fecha actual del sistema obtenida con `date +%d%m%Y`. Nunca la asumas ni la inventes.

- **`<descripcion-corta>`** en kebab-case, máximo 5 palabras, en inglés o español según el idioma del proyecto.

### 4. Ejemplos de nombres válidos

- `feat/15052026-login-google-oauth`
- `fix/15052026-typo-readme`
- `refactor/15052026-extract-user-service`
- `docs/15052026-update-deploy-guide`
- `chore/15052026-bump-django-version`

### 5. Comandos exactos a ejecutar

```bash
# pre-entry: corre en el clon principal, antes de EnterWorktree
# 1. Fecha del día (no asumirla) + identidad del repo y la base (sección 0)
TODAY=$(date +%d%m%Y)
REPO=$(basename "$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")")
BASE=<base de integración de la sección 0>       # release si pr_state=single; main/master si no
SLUG=<descripcion-corta>

# 2a. PREFERIDO (elegí 2a O 2b, nunca las dos): el helper resuelve la base, crea
#     el worktree, enlaza los .env gitignoreados del clon principal e imprime
#     worktree= branch= base= pr_base= pr_state= — corré esto desde cualquier cwd
#     dentro del repo; fuera de él, agregá --project=<nombre>
bash "$HOME/webapps/vps-ops-toolkit/scripts/maintenance/session-worktree.sh" create <prefijo> "$SLUG"

# 2b. Manual (sin toolkit), desde el clon principal ~/webapps/<repo>
git fetch origin "$BASE" --quiet
git worktree add "$HOME/webapps/.wt/${REPO}/${SLUG}" -b <prefijo>/${TODAY}-${SLUG} "origin/${BASE}"

# 3. ENTRAR al worktree (sección 1). Claude Code: herramienta nativa, NO un
#    comando bash → EnterWorktree path=$HOME/webapps/.wt/<repo>/<slug>
cd "$HOME/webapps/.wt/${REPO}/${SLUG}"   # sólo Codex — en Claude ya entraste con EnterWorktree

# 4. Guard: confirmar que estás bajo .wt/ ANTES de escribir. En Claude un `cd` de
#    bash NO mueve el cwd de la sesión: el guard sólo vale después de EnterWorktree.
git rev-parse --show-toplevel   # debe caer bajo ~/webapps/.wt/ — si no, frená

# 5. Recién entonces hacer add y commit
git add <archivos>
git commit -m "<mensaje siguiendo conventional commits>"
```

- `npm ci` / instalar dependencias **dentro del worktree** sólo si tu tarea necesita frontend (build/tests). Jamás toques el `node_modules`, los refs o los stashes de otro tree.
- Los `.env` gitignoreados NO viajan con `git worktree add`: el helper los enlaza desde el clon principal; sin helper, `ln -s ~/webapps/<repo>/backend/.env "$HOME/webapps/.wt/${REPO}/${SLUG}/backend/.env"`. Nunca los copies a una ruta versionada.
- `backend/venv` NO se enlaza nunca: corré los tests con `~/webapps/<repo>/backend/venv/bin/python`.
- **Nunca corras `manage.py migrate` (ni ningún comando que escriba la base de datos) desde el worktree**: el `backend/.env` enlazado apunta a la base de PRODUCCIÓN del clon principal. En el worktree sólo `makemigrations`, `makemigrations --check --dry-run`, `sqlmigrate` y los tests con settings de test; las migraciones las aplica el deploy.
- El worktree se retira cuando su PR YA mergeó: lo hace `$all-in-base` al verificar, y los huérfanos los junta el gc del operador (`session-worktree.sh gc --apply`). Si quedás trabado: `bash "$HOME/webapps/vps-ops-toolkit/scripts/maintenance/session-worktree.sh" remove <slug>` — sin `--force`, nunca (el helper no lo tiene, y el hook deniega `git worktree remove --force` sobre cualquier worktree que no sea `queue-*`).

### 6. Inferencia del prefijo

Determina el prefijo a partir del contenido de los cambios:
- Archivos nuevos que añaden features → `feat`
- Cambios que arreglan comportamiento roto → `fix`
- Solo cambios en `*.md`, comentarios o JSDoc → `docs`
- Cambios en `package.json`, `requirements.txt`, configs → `chore`
- Cambios en `.github/workflows/*` → `ci`
- Archivos `*test*` / `*spec*` modificados o añadidos → `test`
- Reorganización sin alterar comportamiento → `refactor`

Si hay ambigüedad, pregunta al usuario una sola vez antes de crear la rama.

### 7. Excepciones

- Lo permitido en el clon principal es exactamente la lista canónica de la sección 1; no hay excepciones además de esa lista.
- Si el usuario explícitamente pide quedarse en el clon principal para revisar algo sin commitear, respeta esa intención: es una sesión de sólo lectura y no habilita `checkout` ni edición.
- Dentro de TU rama de sesión, los cambios de tu tarea se acumulan como commits sucesivos — no abras una segunda rama por "sub-cambio" de la MISMA tarea. Trabajo NUEVO no relacionado en la misma sesión: preguntale al operador si va como commit en tu rama o como rama de sesión nueva.
- **Convención: 1 sesión = 1 rama = 1 worktree = 1 PR; N PRs de sesión abiertos en paralelo son estado normal.** El límite duro es de RELEASES: máximo 1 PR de release (base=default) por repo, identificado por `branch_working` en projects.yml.
- Sincronizar tu rama: `$git-sync` **desde tu worktree** (en el clon principal no se sincroniza nada — Session Start Protocol) — una rama pusheada con PR se sincroniza contra su propio upstream y absorbe la base movida con `git merge origin/<base>`, **nunca** con rebase (el force push está denegado en el fleet).

### 8. Mensajes de commit

Sigue Conventional Commits, con el mismo prefijo de la rama cuando aplique:

```
feat: add Google OAuth login flow
fix: correct typo in deployment README
refactor: extract user validation into service
```

### 9. PR al primer push (con dueño declarado) + reporte de la URL

En el **primer `git push -u origin <rama>`** de tu rama de sesión, abrí el PR ahí mismo — no lo dejes para después: el PR es lo que le da a tu rama dueño visible, intención declarada y CI corriendo desde temprano.

Un comando por llamada, y con la BASE **literal** (post-`EnterWorktree` no hay `$(...)` que la calcule; sale del `base=` de `session-worktree.sh status` o del `pr_base=` que imprimió `create`):

```bash
git push -u origin <rama>
```
```bash
gh pr create --base <BASE de la sección 0> --fill --body "Sesión: <nombre de tu sesión (el título que le dio el operador), o el slug de la rama si no lo conocés>
Intención: <1 línea: qué entrega esta rama>

<resumen breve de los cambios>"
```

El body va como texto literal entre comillas dobles, con saltos de línea reales — **nunca** `--body "$(printf …)"`: la sustitución de comando hace que Claude rechace el `gh pr create` entero dentro de un worktree.

- Las líneas `Sesión:` y `Intención:` del body son **contrato**: `$merge-queue` las usa para saber a quién delegarle conflictos y fixes. No las omitas.
- Termina tu respuesta con la URL, etiquetada `PR URL: <url>` (si `gh` no está disponible, la URL "Create a pull request" que imprime el push, y decí que el PR quedó pendiente de abrir).
- Pushes posteriores de la misma rama: reporta la URL del PR existente (`gh pr view --json url -q .url`).
- Si por excepción se commiteó directo a `main`/`master` (sólo posible en proyectos sin esta regla), declara explícitamente: "PR URL: n/a (push directo a `main`)".
- Si hubo cambios en varios proyectos en el mismo turno, entrega una **lista** con un `PR URL:` por proyecto.
- El PR abierto con CI verde ES la entrega de la sesión: no sigue ningún merge tuyo (sección 10).

### 10. Cierre: PR abierto + CI verde, y PARÁ

**Definition of done de la sesión:** árbol limpio + rama pusheada + PR abierto (sección 9) + CI verde en ESE PR. Ahí la sesión SE DETIENE.

1. Commiteá y pusheá lo pendiente (secciones 8-9). Con `gh`: `gh pr checks <n> --watch --fail-fast=false`. `$pr-green` conduce este cierre de punta a punta.
2. CI en rojo → fix loop en TU rama (`$pr-green`): arreglá sólo lo atribuible a tu cambio, commit + push y volvé a esperar. Un gate rojo que no es de tests se reporta, no se "arregla" a ciegas.
3. CI verde → reportá `PR URL: <url>` y `CI: ✅` y **no sigas**: NO `gh pr merge`, NO `$merge-when-green`, NO tocar el clon principal, NO "dejar la base al día". El merge lo hace el orquestador (`$merge-queue`) o el operador a mano. Si la queue te delega por mensaje un conflicto o un check rojo, resolvelo en TU worktree y pusheá — la señal de resuelto es el push, no una respuesta. `$merge-when-green` es herramienta del operador (manual-only).
4. Verificación de cierre: **`$all-in-base --check-only`** responde si tu trabajo está ENTREGADO (PR verde, o ya contenido en la base) sin mutar nada. El flag no es opcional: sin el flag, `$all-in-base` delega en `$pr-green` (commit/push/PR/CI) y toca git; con el flag sólo responde. El retiro del worktree lo hace `$all-in-base` recién cuando el PR YA mergeó; con el PR abierto el worktree queda vivo (la queue puede necesitarlo).
5. `vps-ops-toolkit` es la excepción documentada (flujo trunk: commit directo a `master`, sin PR) — este protocolo no aplica ahí.
<!-- git-branch-protocol:end -->

<!-- e2e-user-flows-protocol:begin -->
## E2E User Flows Check

Cuando termines de implementar un cambio que afecte un **flujo de usuario en el frontend** — por ejemplo:
- Crear o editar un formulario (agregar/quitar campos)
- Nueva ruta, página o vista accesible al usuario
- Cambios en flujos de autenticación, checkout, onboarding, búsqueda, perfil
- Modificaciones al registro de flows E2E (`frontend/e2e/flow-definitions.json`, o los shards por-flow + docs derivados en repos con `flow_definitions_dir`)

…debes invocar la skill `e2e-user-flows-check` como **paso final** antes de reportar la implementación como completa. Esa skill audita la cobertura E2E del flujo modificado y reporta brechas/riesgos.

**Por qué:** los flujos de usuario en frontend cambian las assumptions de los tests E2E. Sin auditoría, un campo eliminado deja tests "verdes" pero inválidos, y un form nuevo queda sin cobertura.

**No aplica para:** correcciones aisladas que no cambian el flujo (typos, refactors internos, estilos puros, dependency bumps), ni cambios solo en backend que no alteren UX.

**Recordatorio automático:** el protocolo de cierre de Codex revisa al cierre del turno si hay cambios uncommitted bajo `frontend/src/`, `frontend/app/`, etc., y te lo inyecta como contexto. El hook es un recordatorio, no bloqueante — la regla aplica igual aunque el hook no dispare. Tras `EnterWorktree` el hook mira el directorio de arranque y puede no ver tus cambios; la regla aplica igual.
<!-- e2e-user-flows-protocol:end -->

## Ecosistemas IA paralelos

Este proyecto tiene dos ecosistemas activos en paralelo: Claude Code (`CLAUDE.md` + `.claude/`) y Codex (`AGENTS.md` + `.agents/skills/` + `.codex/config.toml`).
Ambos comparten el
mismo cuerpo de instrucciones general; el frontmatter y la estructura cambian
por ecosistema. La fuente de verdad es `vps-ops-toolkit/workflows/`.
<!-- fleet-base:end -->

<!-- project-shared:begin source=CLAUDE.md -->
# Armony — project guide

## Source of truth
- This `CLAUDE.md` is the source of truth. `AGENTS.md` mirrors it for Codex: its `project-shared` block is a literal copy of this section and must stay aligned.
- Skills in `.claude/skills/` and `.agents/skills/` and agents in `.claude/agents/` and `.codex/agents/` were imported from `WeAreProjectApp/projectapp` (commit `3db2eeb`, 2026-10-26). Their rules (output protocol, gating, test quality, verification) apply here; steps bound to Django/Nuxt/VPS are adapted per "Stack adaptations" below.
- Technical reference: `docs/configuracion-y-contexto.md`, `docs/ui-spec.html` and, once created, the Memory Bank (`docs/methodology/` + `tasks/`).

## Documentation rules
- All documentation is **English** and **strictly technical**: it describes code, modules, interfaces, data flow, configuration, commands and observed behavior.
- No product narrative, intended-use claims, opinions or subjective/ambiguous purpose statements. State what the code does and how, with file references (`path:line`) where useful.
- Applies to Markdown docs, the Memory Bank, `CLAUDE.md`/`AGENTS.md` project sections, docstrings and comments in new or modified code, commit messages and PR descriptions.
- This overrides the fleet-base language convention ("docs in Spanish") for this repo. Imported skills keep their original language. Existing Spanish docs (`README.md`, `docs/`, docstrings) are migrated when touched.
- User-facing UI strings are not documentation; they keep the language the UI uses.

## Overview
- Windows-only desktop app (Windows 10 build 19041+ / 11), Python 3.11 + PySide6. Spike that exercises a real-time pipeline for a larger IDE project.
- Pipeline: WASAPI loopback + microphone capture → speech-to-text (AssemblyAI Universal Streaming over WebSocket) → turn aggregation and question detection → streaming completion from OpenAI (Responses API) → rendering in frameless Qt overlay windows. Overlay windows use `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)`, `WS_EX_TRANSPARENT` click-through and `WS_EX_NOACTIVATE`.
- Packaged as a single `dist\Armony.exe` with PyInstaller (`build_exe.py`). No backend, database, web frontend or server deployment.

## Module map
- `app.py` — entry point; `OverlayApp` controller wiring UI widgets to `CoachEngine` signals and global hotkeys.
- `engine.py` — `CoachEngine(QObject)`: session lifecycle, turn aggregation (`threading.Timer`), worker thread + queue, context window assembly, sentinel (`NO_RESPONSE`) filtering, session transcript and metrics persistence.
- `audio.py` — `AudioEngine`: WASAPI loopback and mic capture threads, resampling to 16 kHz (`soxr`), RMS levels, continuous 16 kHz PCM feed to the streaming STT, default-device hot swap.
- `stt_stream.py` — `StreamingSTT`: AssemblyAI v3 WebSocket client, 50 ms PCM chunking, bounded send queue, reconnection backoff, partial/final turn handling, latency estimation.
- `intent.py` — `parece_pregunta(text, lang)`: lexical question/request detector (ES/EN/auto).
- `llm.py` — `Coach`: prompt construction, voice vs. vision model selection, OpenAI Responses streaming, single retry before first token, warm-up request.
- `richtext.py` — model markdown → section/paragraph/list/code blocks; Pygments highlighting; inline HTML.
- `metrics.py` — process-wide `metricas` singleton: timings, counters, notes; JSON + text report per session.
- `config.py` — defaults, `config.json` load/save, legacy key migration; `secretstore.py` encrypts API keys with DPAPI (`dpapi:` prefix).
- `contexts.py` — `contexts/*.md` files with frontmatter (`name`, `active`, `lang`); concatenated into the system prompt at session start.
- `overlay.py`, `wheelscroll.py`, `hotkeys.py` — Win32 via `ctypes`: display affinity / extended styles, `WH_MOUSE_LL` wheel forwarding, `WH_KEYBOARD_LL` Alt+1..5 capture with `RegisterHotKey` fallback.
- `overlay_ui.py`, `settings_window.py`, `theme.py`, `icons.py` — Qt widgets and styling. `settings_dialog.py` is not imported anywhere.
- `build_exe.py`, `make_icon.py` — packaging and icon generation.

## Architecture invariants
- Worker threads (audio, STT, LLM, timers) never touch widgets; they cross to the UI only through Qt signals.
- Transcript text, screenshots and user contexts are passed to the model as delimited data, never as instructions; the prompt notice in `llm.py` (`Coach._prompt`) must be preserved.
- API keys are stored only DPAPI-encrypted in `config.json`; never in the repo, logs, metrics, transcripts or error messages.
- LLM provider SDKs are imported lazily; both providers sit behind the `Coach` interface.
- End-to-end latency (`extremo_a_extremo_ms` in `metrics.py`) is the primary performance metric; pipeline changes are measured with `metrics.py`, not estimated.

## Working rules
- Follow existing project patterns over generic framework advice.
- Existing code mixes Spanish and English identifiers and comments in Spanish. In existing files, follow the file's identifier style; new identifiers, docstrings and comments are in English.
- Keep edits localized in large files (`overlay_ui.py`, `settings_window.py`, `engine.py`).
- Do not read or print `%APPDATA%\Armony\config.json` or `contexts/*.md`: they contain API keys and user data.

## Stack adaptations (differences from the fleet)
The `fleet-base` block above is imported verbatim. Where it assumes infrastructure this repo lacks, these rules apply:
- **Not in the fleet.** Armony is not in `vps-ops-toolkit/projects.yml`: integration base is `main` (section 0, "no toolkit" branch). No `session-worktree.sh`, `resolve-work-coordinate.sh` or hook guard.
- **Location.** The clone lives at `C:\Users\devgu\armony_project` (WSL: `/mnt/c/Users/devgu/armony_project`), not `~/webapps/<repo>`. Never commit on `main`; each task uses its own `<prefix>/<DDMMYYYY>-<slug>` branch (section 3).
- **Worktrees.** Optional for a single session. Parallel sessions/agents each use their own worktree under `.claude/worktrees/` (gitignored). `.venv` is not present in worktrees: use the main clone's interpreter by absolute path.
- **Delivery without a remote.** No `origin` or CI yet. Definition of done: clean tree + commits on the session branch + tests for the change passing + summary to the operator. The operator decides merges to `main`. Once a remote exists, sections 9-10 apply in full (PR on first push + green CI).
- **No web E2E flows.** The "E2E User Flows Check" block does not apply (no `frontend/`). Equivalent: when a change alters a visible flow (overlay, settings, hotkeys), document manual verification steps on Windows before reporting done.
- **Skills that do not apply** (Django/Nuxt, VPS, ProjectApp clients/proposals): `blog-ai-weekly`, `client-message`, `client-report`, `client-response`, `data-integrity`, `deploy-and-check`, `dev-up`, `dev-down`, `e2e-user-flows-check`, `fake-data-refresh`, `frontend-e2e-test-coverage`, `frontend-unit-test-coverage`, `merge-queue`, `merge-when-green`, `migrate-project`, `platform-delivery-authoring`, `playwright-validation`, `proposal-create`, `requirement-calculator`, `responsive-pass`, `tailscale-connect`, `view-map-audit`, `view-map-update`. Kept for reference; do not invoke here.
- **Adapted skills:** `backend-test-coverage` → pytest tests for the Python modules; `qa-engineer-backend` is the test-writing agent. `security-pass` / `vuln-audit` → secrets, DPAPI, prompt injection, `requirements.txt` dependencies and PyInstaller bundle. `perf-pass` / `perf-scout` → live pipeline latency measured with `metrics.py`.

## Commits and PRs
- Do NOT add `Co-Authored-By: Claude ...` trailers. The repository owner is the sole author.
- Do NOT include "Generated with Claude Code", "🤖 Generated with..." or any similar attribution in commits or PR descriptions.
- English Conventional Commits (`feat:`, `fix:`, `test:`, `chore:`, ...), with a plain summary and a test plan where applicable.

## Commands
From WSL the Windows venv runs through interop (`.venv/Scripts/python.exe`); from PowerShell use `.venv\Scripts\python.exe`.
- Run the app (Windows only, needs audio devices and a desktop): `.venv\Scripts\python.exe app.py`
- Build the exe: `.venv\Scripts\python.exe build_exe.py` → `dist\Armony.exe`
- Install dev dependencies: `.venv/Scripts/python.exe -m pip install -r requirements-dev.txt`
- Run tests (one file or test at a time): `.venv/Scripts/python.exe -m pytest tests/<file>.py -v`
- Coverage for a module: `.venv/Scripts/python.exe -m pytest tests/<file>.py --cov=<module> --cov-report=term-missing`

## Testing constraints
- Never run the full suite: only the files or tests for the change. Max 20 tests per batch and 3 test commands per cycle.
- One behavior per test, no conjunctions in test names, no conditionals in test bodies (parametrize), AAA pattern, hand-verified literal expected values.
- Mock only at system boundaries: OpenAI/AssemblyAI/TypeSafe APIs, WASAPI/PyAudio, Win32 (`ctypes`), clock, and the `%APPDATA%` file system.
- Tests never call paid APIs, open real network connections or read the user's real configuration (`tests/conftest.py` enforces isolation).
- A test that exposes a bug is marked `pytest.mark.xfail(strict=True, reason="[KNOWN-NNN] ...")` and the bug is recorded in `docs/methodology/error-documentation.md`; the fix lands in a separate `fix/...` branch.
- Coverage priority: pure logic without Windows/Qt (`intent.py`, `richtext.py`, `metrics.py`, `config.py`, `contexts.py`, prompt building in `llm.py`), then `engine.py`, `llm.py` and `stt_stream.py` with boundaries mocked.

## Memory Bank
- Core files (created with the `methodology-setup` skill; not yet present): `docs/methodology/product_requirement_docs.md`, `architecture.md`, `technical.md`, `error-documentation.md`, `lessons-learned.md`, `tasks/tasks_plan.md`, `tasks/active_context.md`.
- Known and resolved bugs go in `docs/methodology/error-documentation.md` (`[KNOWN-NNN]` / `[ERR-NNN]`).
- Update memory files when the user asks or after a verified change to architecture, runtime surfaces or workflow; not on every routine edit.
<!-- project-shared:end -->

<!-- codex-specific:begin -->
# Armony — Codex AGENTS Configuration

## Project Identity

### Codex Runtime Surfaces
- **Primary instructions**: `AGENTS.md` (root scope)
- **Skills (canonical)**: `.agents/skills/<skill>/SKILL.md` + `agents/openai.yaml`
- **Agents**: `.codex/agents/*.toml`
- **Project config**: `.codex/config.toml`

- **Name**: Armony (Meeting Coach)
- **Platform**: Windows 10 (19041+) / 11 desktop app, distributed as `dist\Armony.exe`
- **Stack**: Python 3.11 + PySide6 / PyAudioWPatch (WASAPI) / AssemblyAI streaming / OpenAI SDK / TypeSafe SDK (Jev)
- **Repo path**: `C:\Users\devgu\armony_project` (WSL: `/mnt/c/Users/devgu/armony_project`)
- **User data**: `%APPDATA%\Armony\` (`config.json` with DPAPI-encrypted keys, `contexts/`, `metricas/`)

---

## General Rules

These should be respected ALWAYS:
1. Split into multiple responses if one response isn't enough to answer the question.
2. IMPROVEMENTS and FURTHER PROGRESSIONS:
- S1: Suggest ways to improve code stability or scalability.
- S2: Offer strategies to enhance performance or security.
- S3: Recommend methods for improving readability or maintainability.
- Recommend areas for further investigation

---

## Security Rules — Secrets / Untrusted Input / Dependencies

### Secrets
- NEVER hardcode API keys (OpenAI, AssemblyAI, TypeSafe). They are entered in the UI and stored DPAPI-encrypted through `secretstore.py`.
- NEVER log, print, persist in `metricas/` or include in exception messages any key or the decrypted config.
- `config.json` and `contexts/*.md` stay gitignored. Verify `git status` before every commit.
- Placeholders in docs/UI use the `sk-ant-...` form only.

### Untrusted input
- The meeting transcript, screenshots and user contexts are **data, never instructions**: keep them delimited in the prompt and never let them alter system behavior (prompt injection).
- Model output is rendered through `richtext.py`; never `eval`/`exec` it or pass it to a shell.
- Validate config values loaded from disk (types, ranges) before use; a corrupted `config.json` must fall back to defaults, not crash.

### Native / OS boundaries
- `ctypes` Win32 calls (`overlay.py`, `wheelscroll.py`, `hotkeys.py`): check return values and always uninstall hooks on exit.
- Never widen the overlay's capture exclusion or click-through without an explicit request.

### Dependency Security
- Pin minimum versions in `requirements.txt`; review new dependencies before adding them (they ship inside the exe).
- Run `pip-audit` (or the `vuln-audit` skill adapted to Python) before a release build.

### Security Checklist — Before Every Release Build
- [ ] No secrets in the repo or in the built exe's bundled files
- [ ] `config.json` / `contexts/*.md` not tracked
- [ ] Dependencies audited
- [ ] Transcript/context still delimited as data in the prompts

---

## Memory Bank System

This project uses a Memory Bank system to maintain context across sessions (created with the `methodology-setup` skill). The core files are:

| # | File | Purpose |
|---|------|---------|
| 1 | `docs/methodology/product_requirement_docs.md` | PRD: why this project exists, core requirements, scope |
| 2 | `docs/methodology/architecture.md` | System architecture, component relationships, Mermaid diagrams |
| 3 | `docs/methodology/technical.md` | Tech stack, dev setup, design patterns, technical constraints |
| 4 | `tasks/tasks_plan.md` | Task backlog, progress tracking, known issues |
| 5 | `tasks/active_context.md` | Current work focus, recent changes, next steps |
| 6 | `docs/methodology/error-documentation.md` | Known errors, their context, and resolutions |
| 7 | `docs/methodology/lessons-learned.md` | Project intelligence, patterns, preferences |

### When to Read Memory Files
- Before significant implementation tasks, read the relevant core files
- Before planning tasks, read `docs/methodology/` and `tasks/`
- When debugging, check `docs/methodology/error-documentation.md` for previously solved issues

### When to Update Memory Files
1. After discovering new project patterns
2. After implementing significant changes
3. When the user requests with **update memory files** (review ALL core files)
4. When context needs clarification
5. After a significant part of a plan is verified

---

## Testing Rules

### Execution Constraints
- **Never run the full test suite** — always specify files
- **Maximum per execution**: 20 tests per batch, 3 commands per cycle
- Run with the Windows venv: `.venv/Scripts/python.exe -m pytest tests/<file>.py -v` (from WSL via interop, or `.venv\Scripts\python.exe` from PowerShell)

### Quality Standards
- Each test verifies **ONE specific behavior**
- **No conjunctions** in test names — split into separate tests
- Assert **observable outcomes** (returned values, emitted signals, written files, built prompts)
- **No conditionals** in test body — use parameterization
- Follow **AAA pattern**: Arrange → Act → Assert
- Mock only at **system boundaries** (LLM/STT APIs, WASAPI, Win32, clock, `%APPDATA%`)

---

# Armony - Codex Compatibility Instructions

This repository's agent configuration is versioned under `CLAUDE.md` and `.claude/`.

For Codex-compatible work in this repo:
- Treat `CLAUDE.md` as the authoritative root project instruction set.
- Treat `.agents/skills/*` as the Codex-facing equivalents of the versioned `.claude/skills/*` workflows.
- Treat `.codex/config.toml` as the Codex runtime defaults for this project.

When both Claude and Codex compatibility files exist:
- Prefer the versioned `.claude/` and `CLAUDE.md` content as the source of truth unless the user explicitly asks to change Codex-only compatibility files.
- Keep `.agents/skills/*` aligned with `.claude/skills/*` and any intentionally converted `.claude/commands/*`.

Operational notes:
- Read the relevant methodology docs in `docs/methodology/` and planning context in `tasks/` when the task needs them.
- Do not delete local compatibility files or extra local skills unless the user explicitly asks.
- In subdirectories, also follow the nearest `AGENTS.md`.
<!-- codex-specific:end -->
