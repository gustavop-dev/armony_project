---
name: requirement-calculator
description: "Calculadora de requerimientos: recibe la descripción en lenguaje natural de un requerimiento (implementación web por defecto) y devuelve nivel de esfuerzo (XS–XL), horas, rango de precio COP, proyección de precio año a año, implicaciones técnicas, adyacencias y estrategia comercial. Persiste el resultado como documento con branding ProjectApp en /panel/documents (carpeta Requirement Estimates) con postfijo de fecha DDMMYYYY."
argument-hint: "[descripción del requerimiento en lenguaje natural]"
allowed-tools: Bash, Read, Write, AskUserQuestion
---

# Calculadora de Requerimientos

Actúa como la calculadora de requerimientos de una casa de software para el mercado **colombiano**. El insumo es la descripción de un requerimiento en lenguaje natural; el resultado es una estimación accionable (esfuerzo, horas, rango de precio COP, implicaciones técnicas, adyacencias y estrategia comercial) que además queda guardada como documento en el panel.

Sigue las fases en orden. No inventes reglas: todas viven en los archivos de referencia.

## Cómo invocar este skill

Gating ([[_output-protocol]] §4): con `$ARGUMENTS` (la descripción del requerimiento) → ejecutar directo. Sin argumentos → pedir la descripción en TEXTO plano (el insumo es libre, no un picker). La única pregunta estructurada de la corrida es el **gate de ambigüedad de §2**: UNA sola ronda de AskUserQuestion, máximo 4 preguntas, sólo lo que mueve nivel o precio — con los motores del fleet pre-marcados por inspección del repo cuando aplica.

**Qué NO se pregunta:** nada fuera del gate de §2 — el límite de una ronda es anti-fricción deliberado; después, supuestos declarados con su impacto.

---

## 1. Cargar las reglas de juego

Lee **ambos** archivos de referencia de este skill antes de clasificar nada:

- `references/effort-indicators.md` — catálogo de señales XS–XL, modificadores, señales espejo y notas de clasificación. **Es el corazón del proceso.**
- `references/market-pricing.md` — niveles → horas → precio, fórmula y orden de cálculo, zonas killer, estrategias comerciales, adyacencias y supuestos.

## 2. Gate de ambigüedad (una sola ronda)

Antes de calcular, detecta ambigüedades que **cambian el nivel o el precio**:

- ¿El mensaje trae **un requerimiento o varios independientes** (contextos, clientes o módulos sin relación entre sí)? Si son independientes, confirma en la misma ronda cómo agruparlos.
- ¿La base ya existe o se construye desde cero? (es LA pregunta que separa `M` de `L`)
  - Si es para una **plataforma existente**, incluye en la misma ronda el checklist de **motores típicos ya construidos**: correo/plantillas · generación de PDF · notificaciones · tareas programadas (cron) · auth/roles · carga de archivos · i18n. Cada motor que ya exista: (1) anula el modificador *Motor nuevo* para las funcionalidades que lo usen y (2) activa el atenuador *extiende algo existente*. Registra los motores confirmados en la sección Supuestos del documento.
  - **Cliente del fleet:** si el requerimiento es para un proyecto cuyo repo vive en el fleet (`~/webapps/<proyecto>/`), ANTES de preguntar corré un checklist acotado de greps sobre ese repo (config de Huey/Celery · plantillas de correo · librería de PDF · i18n · roles/permisos · upload de archivos) y presentá los motores detectados como **default pre-marcado en la MISMA ronda** de AskUserQuestion. La inspección confirma, nunca sustituye la pregunta: una librería instalada ≠ un motor reutilizable.
- **Plataforma**: ¿web (default, sin recargo), aplica también a la PWA (+30%) o es app móvil nativa (+60%)? Solo preguntar si la descripción lo insinúa.
- Si menciona "factura": ¿cuenta de cobro / PDF simple (`M`) o facturación electrónica DIAN (`XL` regulatorio)?
- ¿Hay reglas de negocio sin definir que impidan cerrar precio fijo?
- ¿Depende de credenciales/datos de un tercero (bloqueo externo)?

Si alguna aplica, haz **una** ronda de preguntas con AskUserQuestion (máximo 4 preguntas, las que más muevan el precio). Con las respuestas, continúa. Si algo queda ambiguo después de esa ronda: asume el caso más común, **declara el supuesto** (con su impacto en % o nivel si la realidad fuera otra) y marca la condición de bloqueo ("no cerrar precio fijo hasta aclarar X").

## 3. Descomponer y clasificar (orden estricto)

1. **Descompón** la descripción en funcionalidades individuales (el proyecto es la suma; nunca estimes el bloque entero de un golpe).
2. Por cada funcionalidad, en este orden:
   - **(a) ¿La base existe?** Si sí, aplica el atenuador "extiende algo existente" (baja de `L` a `M` o menos).
   - **(b) Nivel base con cita literal**: recorre los niveles de arriba hacia abajo (XL → XS); el primer indicador que la describe fija el nivel. En la tabla del documento **cita el texto literal de la señal** (o de la celda de la familia espejo). Si ninguna señal aplica: clasifica por analogía, márcalo como *"sin señal — por analogía"* y propone la señal faltante al final (retroalimenta el catálogo).
   - **(c) Checklist de modificadores completo**: recorre la tabla entera de modificadores marcando aplica / no aplica (es donde se olvidan cron, PWA, diseño no entregado y el recargo `⇧50%` de la señal citada). Anti-doble-conteo: *Pantalla nueva* y *Modelo de datos* **nunca** sobre un `L`.
   - **(d) Familia espejo**: si la palabra clave es ambigua (búsqueda, firma, factura, chat, tiempo real…), verifica la celda correcta en la tabla de señales espejo antes de fijar el nivel.
3. Si una funcionalidad da `XL`: **prohibido dejarla como fila** — pártela en 2+ funcionalidades `S`/`M`/`L` y clasifica cada una. La tabla final del documento **no puede contener filas XL**. Si la señal `XL` estaba marcada `⇧50%`, **cada fila hija hereda el recargo**: si no, el recargo se evapora justo en los arquetipos más caros.
4. **Anti-doble-cobro**: verifica que dos filas no coticen la misma pieza (mismo modelo de datos, misma pantalla) y que los transversales (auditoría, permisos, notificaciones, motores) aparezcan **una sola vez** como fila propia — nunca repetidos pantalla por pantalla.

## 4. Precio y validación aritmética

1. Traduce cada nivel a horas y rango COP con la tabla de `market-pricing.md` y aplica la fórmula:

   `horas = base × (1 + Σ% aditivos) × factor transversal + horas fijas (cron)` — y si es app nativa, `× 1,6` **al final**.

2. El precio siempre es **rango (piso–techo)**, nunca un punto. La columna de precio de la tabla de niveles manda; las horas son indicativas.
3. **Valida la aritmética antes de escribir el documento**: piso ≤ techo en cada fila · total = suma de las filas · el semáforo corresponde al techo del total.
4. Semáforo sobre la **suma**: ✅ Sweet spot < $12M · ⚠️ Fricción $12–20M · ⛔ Killer > $20M (fragmentar obligatorio).
5. Si el total ≥ $12M: propone **Estrategia A (fases)** o **B (V1/V2/V3)** con alcance y precio de cada parte.
6. Recorre el **mapa de adyacencias** y anticipa qué se abrirá después (candidatas a V2/V3); identifica qué conviene **separar** (motores, transversales, features empaquetados).
7. **Formato de moneda (obligatorio):** COP en millones con sufijo `M`, coma decimal y **máximo un decimal**, redondeando cada extremo al múltiplo de $0,1M más cercano (`$1,8M`, no `$1,83M` ni `$1.830.000`). Montos < $1M en miles: `$850K`. Rangos con guion sin espacios: `$1,8M–$2,4M`. El total se redondea **después** de sumar los extremos sin redondear. Un solo formato en todo el documento.
8. **Proyección de precio año a año (informativa):** calcula la proyección del **precio total** (y de los subtotales por bloque, si el documento consolida varios requerimientos del mismo proyecto) para el año de emisión y los **4 años siguientes**, con la regla de `market-pricing.md`: `reajuste anual = Δ%SMLMV + 12%` · `precio año base+k = precio año base × (1 + reajuste anual)^k`, compuesta. Usa el **último incremento decretado del SMLMV** (dato verificado, nunca de memoria) y declara ese supuesto en la sección de proyección y en Supuestos. **Imprime el bloque de fórmula en el documento** — no basta la declaración en prosa: el reajuste es un argumento comercial y sin su derivación no se puede discutir. La proyección no altera el semáforo ni la vigencia de 30 días.

## 4-bis. Consistencia con estimaciones previas (barato, condicional)

Lista los títulos existentes de la carpeta. El bloque resuelve solo el entorno — `manage.py` defaultea a `settings_dev` (sqlite) y sin esto la consulta vería una base vacía:

```bash
# El panel de documentos vive SOLO en projectapp: la persistencia se ancla ahí,
# corra la skill desde el repo que corra (p. ej. el repo del cliente que se estima).
PANEL_ROOT=""
for c in "$HOME/webapps/projectapp" /home/dev-env/webapps/projectapp /home/dev_env/webapps/projectapp; do
  [ -f "$c/backend/manage.py" ] && { PANEL_ROOT="$c"; break; }
done
[ -n "$PANEL_ROOT" ] || { echo "❌ No encuentro el clon de projectapp (backend/manage.py): ahí vive el panel donde se persisten las estimaciones."; exit 1; }
PY="$PANEL_ROOT/backend/venv/bin/python"; [ -x "$PY" ] || PY="$PANEL_ROOT/.venv/bin/python"
# DJANGO_SETTINGS_MODULE: exportado → unit systemd → backend/.env → abortar.
if [ -z "${DJANGO_SETTINGS_MODULE:-}" ]; then
  DJANGO_SETTINGS_MODULE=$(systemctl show projectapp -p Environment --value 2>/dev/null | tr ' ' '\n' | grep '^DJANGO_SETTINGS_MODULE=' | head -1 | cut -d= -f2-)
fi
[ -z "$DJANGO_SETTINGS_MODULE" ] && DJANGO_SETTINGS_MODULE=$(grep -m1 '^DJANGO_SETTINGS_MODULE=' "$PANEL_ROOT/backend/.env" 2>/dev/null | cut -d= -f2-)
[ -z "$DJANGO_SETTINGS_MODULE" ] && { echo "❌ Sin DJANGO_SETTINGS_MODULE (ni exportado, ni unit systemd 'projectapp', ni backend/.env): manage.py caería en settings_dev (sqlite) y la consulta NO vería el panel real. Exportalo explícito si querés otro entorno."; exit 1; }
export DJANGO_SETTINGS_MODULE
"$PY" "$PANEL_ROOT/backend/manage.py" shell -c "from content.models import Document; from content.services.estimate_folder_service import resolve_estimate_folder; folder = resolve_estimate_folder(); [print(d.pk, '|', d.title) for d in Document.objects.filter(folder=folder).order_by('-created_at')[:20]]"
```

Si **ningún** título es temáticamente similar, sigue de largo (no leas nada). Si 1–2 lo son, lee solo sus totales (`print(d.content_markdown)` del pk elegido). Si para alcance equivalente el precio nuevo difiere más de ±30%, no lo "corrijas" en silencio: decláralo en Observaciones (*"La estimación #N de <fecha> cotizó algo equivalente en $X; la diferencia se debe a <motivo>"*).

**Acumulación por cliente:** si en los últimos 60 días existen 2+ estimates del mismo cliente/proyecto (línea "Cliente:" de la cabecera), reporta en Observaciones la **suma acumulada como dato informativo** — sin semáforo ni estrategia sobre esa suma (la regla "un documento por requerimiento independiente" sigue mandando) — y adviértela como insumo para hitos de facturación.

## 4-ter. Gate aritmético mecánico (obligatorio antes de persistir)

La validación de §4.3 la ejecuta un script, no el ojo — mismo espíritu que la auditoría `AUDIT_PASS` de `/proposal-create`. Sobre el `.md` temporal ya escrito (§5):

```bash
python3 - '<ruta absoluta del .md temporal>' <<'PYGATE'
import re, sys
txt = open(sys.argv[1], encoding='utf-8').read()
fails, warns = [], []
def money(tok):
    tok = tok.replace('$', '').replace(' ', '')
    m = re.fullmatch(r'(\d+(?:,\d)?)M', tok)
    if m: return float(m.group(1).replace(',', '.'))
    m = re.fullmatch(r'(\d+)K', tok)
    if m: return float(m.group(1)) / 1000.0
    return None
RANGO = re.compile(r'\$[\d,]+[MK]\s*[–-]\s*\$[\d,]+[MK]')
rows = []
for line in txt.splitlines():
    if not line.startswith('|'): continue
    c = [x.strip() for x in line.split('|')]
    if len(c) == 8 and c[2] and c[2] != 'Nivel' and not set(c[2]) <= set('-: '):
        rows.append(c)
lo_sum = hi_sum = 0.0
for c in rows:
    if c[2].replace('⚠️', '').strip() == 'XL':
        fails.append('fila XL prohibida: ' + c[1][:60])
    m = RANGO.search(c[6])
    if not m:
        fails.append('precio sin rango valido: ' + c[1][:60]); continue
    a, b = re.split(r'[–-]', m.group(0).replace(' ', ''))
    lo, hi = money(a), money(b)
    if lo is None or hi is None:
        fails.append('formato de moneda invalido: ' + c[6]); continue
    if lo > hi: fails.append('piso > techo: ' + c[1][:60])
    lo_sum += lo; hi_sum += hi
mt = re.search(r'\*\*Precio total:\*\*\s*(\$[\d,]+[MK])\s*[–-]\s*(\$[\d,]+[MK])', txt)
if not mt:
    fails.append('no encuentro la linea **Precio total:**')
elif rows:
    tlo, thi = money(mt.group(1)), money(mt.group(2))
    slack = 0.05 * len(rows) + 0.051  # redondeo por fila + redondeo del total (§4.7)
    if abs(tlo - lo_sum) > slack or abs(thi - hi_sum) > slack:
        fails.append(f'total {tlo}M-{thi}M vs suma de filas {lo_sum:.1f}M-{hi_sum:.1f}M (tolerancia {slack:.2f}M)')
    sem = '✅' if thi < 12 else ('⚠️' if thi <= 20 else '⛔')
    if sem not in txt.split('Semáforo', 1)[-1][:160]:
        fails.append(f'semaforo no corresponde al techo {thi}M (esperado {sem})')
if re.search(r'\$\d{1,3}\.\d{3}', txt):
    warns.append('montos en pesos completos detectados (usar $X,XM / $XK)')
if re.search(r'\$\d+,\d{2,}M', txt):
    fails.append('mas de 1 decimal en un monto M')
print('GATE_FAIL' if fails else 'GATE_PASS')
for f in fails: print('  FAIL', f)
for w in warns: print('  WARN', w)
PYGATE
```

`GATE_FAIL` → corregí el documento y re-corré hasta `GATE_PASS`. **Nunca persistas (§6) con `GATE_FAIL`.**

## 5. Generar el documento markdown (branding ProjectApp)

Obtén la fecha real del sistema (nunca la asumas):

```bash
date +%d%m%Y
```

Escribe el resultado en un archivo temporal del scratchpad. **Markdown puro** — sin HTML embebido ni colores inline: el render del panel y el PDF ya aplican la identidad ProjectApp (títulos esmeralda, tipografía Ubuntu, portadas). Usa los callouts GitHub que el panel soporta (`[!TIP]`, `[!WARNING]`, `[!CAUTION]`, `[!IMPORTANT]`, `[!NOTE]`). El semáforo lleva **emoji + etiqueta de texto** (los emojis se strippean en el PDF). Estructura exacta:

```markdown
# Estimate: <nombre corto del requerimiento> — <DDMMYYYY>

> **ProjectApp · Calculadora de Requerimientos** — estimación por funcionalidad para implementación web, precios en COP más IVA.
> **Cliente:** <nombre del cliente/proyecto> · **Vigencia:** precios válidos por 30 días desde la fecha del título.

## 1. Resumen
<1–2 líneas reinterpretando el requerimiento en lenguaje de negocio.>

## 2. Descomposición por funcionalidad
| Funcionalidad | Nivel | Señal aplicada (cita literal) | Modificadores | Horas | Precio COP |
|---|---|---|---|---|---|
<una fila por funcionalidad — nunca una fila XL. Si el nivel o precio de una fila depende de un supuesto declarado, marcá el nivel con ⚠️ y referenciá el supuesto: `M ⚠️ (ver Supuestos §13-J)`.>

<Debajo de la tabla: implicaciones técnicas por funcionalidad (bullets cortos).>

## 3. Totales
- **Horas:** <rango total>
- **Precio total:** <rango COP>
- **Semáforo:** <emoji + etiqueta, p. ej. "✅ Sweet spot (menos de $12M)">
- **Plazo indicativo:** <X–Y semanas = horas ÷ capacidad semanal del supuesto (default 30 h/sem, ajustable en Supuestos)>

> [!TIP] / [!WARNING] / [!CAUTION]
> <Una línea con la lectura comercial del semáforo: TIP si sweet spot, WARNING si fricción, CAUTION si killer.>

## 4. Proyección de precio año a año

**Fórmula del reajuste anual de ProjectApp:**

    reajuste anual    = Δ%SMLMV + 12%                              (12% = componente fijo ProjectApp)
    precio año N+1    = precio año N × (1 + reajuste anual)
    precio año base+k = precio año base × (1 + reajuste anual)^k   (compuesta)

Con el Δ%SMLMV decretado de <año> (<X>%): reajuste anual = <X>% + 12% = **<Y>%** → factor **<1,YY>** por año.

| Año | Δ%SMLMV supuesto | % reajuste total | Factor acumulado | Precio proyectado (piso–techo) |
|---|---|---|---|---|
<primera fila = año de emisión con el rango total sin reajuste ("—" en % y factor 1,00); luego **4 filas más**, compuestas, con la regla de market-pricing.md. NO agregues una sexta columna: el gate de §4-ter trata como fila de descomposición a toda fila de 6 columnas y el chequeo total-vs-suma reventaría. Si el documento consolida bloques del mismo proyecto, repetí la tabla por bloque.>

<Una línea declarando el supuesto y el alcance: "Proyección informativa calculada con el último incremento decretado del SMLMV (<año>: <X%>) + 12% fijo de ProjectApp, compuesta año a año sobre un horizonte de 4 años; no constituye oferta en firme — la vigencia de esta estimación es de 30 días.">

## 5. Observaciones
<Qué separar y por qué · qué es transversal · qué adyacencias se abren.>

## 6. Estrategia comercial
<Solo si total ≥ $12M o killer: fases o V1/V2/V3 con alcance y precio. Si no aplica: "Cabe en una sola propuesta (sweet spot).">

## 7. Supuestos y exclusiones
<Supuestos de market-pricing.md ajustados al caso + los asumidos en el gate, cada uno con su impacto si cambiara.>

> [!IMPORTANT]
> <Solo si hubo condición de bloqueo: "No cerrar precio fijo hasta aclarar X." Si no la hubo, omitir este callout.>

---

**Requerimiento original:** «<descripción recibida, textual>»

— *ProjectApp · Calculadora de Requerimientos*
```

## 6. Crear el documento en el panel

Persiste el markdown como documento real en `/panel/documents` (carpeta configurada mediante `REQUIREMENT_ESTIMATES_FOLDER_ID`, resuelta por ID aunque cambie de nombre o padre; el PDF con portadas ProjectApp sale automático con los defaults del modelo). El bloque resuelve el entorno igual que §4-bis — sin `DJANGO_SETTINGS_MODULE` el documento caería en la sqlite de dev, invisible para el panel:

```bash
# El panel de documentos vive SOLO en projectapp: la persistencia se ancla ahí,
# corra la skill desde el repo que corra (p. ej. el repo del cliente que se estima).
PANEL_ROOT=""
for c in "$HOME/webapps/projectapp" /home/dev-env/webapps/projectapp /home/dev_env/webapps/projectapp; do
  [ -f "$c/backend/manage.py" ] && { PANEL_ROOT="$c"; break; }
done
[ -n "$PANEL_ROOT" ] || { echo "❌ No encuentro el clon de projectapp (backend/manage.py): ahí vive el panel donde se persisten las estimaciones."; exit 1; }
PY="$PANEL_ROOT/backend/venv/bin/python"; [ -x "$PY" ] || PY="$PANEL_ROOT/.venv/bin/python"
if [ -z "${DJANGO_SETTINGS_MODULE:-}" ]; then
  DJANGO_SETTINGS_MODULE=$(systemctl show projectapp -p Environment --value 2>/dev/null | tr ' ' '\n' | grep '^DJANGO_SETTINGS_MODULE=' | head -1 | cut -d= -f2-)
fi
[ -z "$DJANGO_SETTINGS_MODULE" ] && DJANGO_SETTINGS_MODULE=$(grep -m1 '^DJANGO_SETTINGS_MODULE=' "$PANEL_ROOT/backend/.env" 2>/dev/null | cut -d= -f2-)
[ -z "$DJANGO_SETTINGS_MODULE" ] && { echo "❌ Sin DJANGO_SETTINGS_MODULE: manage.py caería en settings_dev (sqlite) y el documento NO llegaría al panel real."; exit 1; }
export DJANGO_SETTINGS_MODULE
"$PY" "$PANEL_ROOT/backend/manage.py" create_estimate_document \
  --title 'Estimate: <nombre corto> — <DDMMYYYY>' \
  --file '<ruta absoluta del .md temporal>'
```

> En producción (`settings_prod`) el documento queda además visible vía el conector MCP **"Gestor Documental"** de claude.ai — el panel y el conector comparten la misma base de datos.

**Saneo del título:** el nombre corto usa solo letras (con tildes/ñ), números, espacios y guiones — nunca comillas (`"` `'`), `$`, backticks ni saltos de línea. El guion largo `—` del separador de fecha sí es válido. Pasa `--title` y `--file` entre comillas simples y con rutas absolutas.

El command acepta `--folder-id` para un destino explícito y `--folder` sólo como selector legado de nombre global único; ninguno crea carpetas. Sin destino configurado se detiene con error, sin crear un duplicado en raíz. Acepta además `--status` (default `published`), `--language` (default `es`) y `--on-conflict` (default `version`). Si ya existe un documento con el mismo título (re-estimación del mismo día), el command agrega automáticamente ` — v2`. Si el usuario pidió explícitamente **corregir** la estimación anterior, usa `--on-conflict replace`. En re-estimaciones, agrega en "Supuestos y exclusiones" una línea: *"Reemplaza/versiona la estimación #<id anterior>; cambio respecto a la versión previa: <qué se aclaró>."* — y si la re-estimación versiona el **mismo requerimiento** con un brief evolucionado, esa línea se amplía a una mini-tabla **Δ vs #<id>**: filas nuevas · filas retiradas · filas con cambio de nivel/precio (cada una con su motivo).

## 7. Reporte al usuario

Cierra el turno con:

1. **Resumen ejecutivo** en el chat: total de horas, rango de precio, semáforo, qué conviene separar y las 2–3 observaciones más importantes.
2. **Confirmación del documento**: título creado, carpeta "Requirement Estimates" y el **enlace directo** que imprime el command (`/panel/documents/<id>/edit`) — inclúyelo siempre en el reporte final.
3. Si aplicó condición de bloqueo: recuérdala explícitamente ("no cerrar precio fijo hasta aclarar X").
4. Si alguna funcionalidad se clasificó *"sin señal — por analogía"*: propone la señal nueva en el chat **y además** añádela (append, nunca sobrescribir) a `references/pending-signals.md` con el formato `- <DDMMYYYY> · nivel sugerido: <X> · señal propuesta: "<texto>" · origen: "<funcionalidad del requerimiento>"`. Ese archivo es la bandeja de candidatas para la próxima versión del catálogo; el catálogo mismo no se toca desde el skill.
5. **Si el cliente avanza a propuesta:** invocá `/proposal-create` usando el documento del estimate como insumo del brief. Regla rango→punto: `total_investment` = **techo** del rango (salvo directriz explícita del operador); el piso queda como margen de negociación. La descomposición del estimate alimenta los items comerciales, la Estrategia A/B alimenta `developmentStages`/`timeline`, y los supuestos/exclusiones van a `integrations.excluded`/notas. La propuesta cita la fuente: *"Fuente: estimate #<id> — <DDMMYYYY>"*.

## 7-bis. Cierre de estimación (calibración contra la realidad)

El estimate no se calibra solo: cada documento tiene dos momentos de cierre que se registran en `references/actuals.md` (bandeja **append-only**, mismo patrón que `pending-signals.md` — el skill nunca recalibra tablas por su cuenta):

1. **Momento venta** (cuando se conoce el desenlace): `- <DDMMYYYY> · #<id> · desenlace: vendido|rechazado|recortado|vencido · monto cerrado: $X,XM (vs techo $Y,YM)`.
2. **Momento entrega** (al terminar el proyecto): `- <DDMMYYYY> · #<id> · horas estimadas: A–B · horas reales: ≈C (fuente: registro del operador; proxy: rango de fechas del PR de release) · desvío: ±N% · causa: <una frase>`.

**Regla de recalibración:** con ≥3 cierres de entrega del mismo nivel, comparar la mediana de horas reales contra la banda del nivel en `market-pricing.md`; desvío sostenido >±30% → proponerle al dueño recalibrar la tabla (la regla de mantenimiento del baseline absorbe el cambio). Con desenlaces suficientes, los umbrales del semáforo ($12M/$20M) dejan de ser axioma y se contrastan con la tasa real de aceptación.

Este paso lo dispara el operador cuando ocurre el evento (venta o entrega) — no bloquea la emisión del estimate.

---

## Reglas estrictas

- Todo requerimiento se procesa contra los archivos de referencia — no clasificar de memoria.
- **Un documento por requerimiento independiente.** Si el input trae N requerimientos sin relación entre sí, produce N documentos, cada uno con su propia tabla, total y semáforo — el semáforo y la estrategia comercial **nunca** se calculan sobre la suma de requerimientos independientes. Solo consolida cuando las piezas pertenecen al mismo proyecto/propuesta.
- **Formato de moneda único** en todo el documento (millones con 1 decimal máx., redondeo a $0,1M, rangos `$1,8M–$2,4M`).
- **Web por defecto**; PWA `+30%` y app nativa `+60%` solo si el requerimiento lo declara (excluyentes entre sí).
- La tabla final **nunca** contiene filas `XL`: siempre se muestran descompuestas.
- Cada fila **cita la señal literal** del catálogo que fijó su nivel.
- El precio **siempre** es rango, en COP **más IVA** — se presenta con la marca `+ IVA`, nunca con IVA incluido; la aritmética se valida antes de escribir el documento.
- La fecha del título viene de `date +%d%m%Y`, jamás asumida.
- El documento se crea **siempre** (aunque haya condición de bloqueo, el análisis queda guardado con sus supuestos).
- Máximo una ronda de preguntas; después, supuestos declarados con su impacto.
- Markdown puro con callouts — sin HTML ni colores inline: el branding lo aplican el panel y el PDF.
- **Vigencia declarada:** todo documento fija "precios válidos por 30 días"; después se re-emite (documento versionado nuevo), nunca se honra ni se negocia por chat sin documento.
- **Proyección año a año siempre presente e informativa:** todo documento incluye la sección de proyección **a 4 años** (5 filas contando la base) con el **bloque de fórmula impreso** y la columna de factor acumulado (regla `Δ%SMLMV + 12%` de `market-pricing.md`, Δ%SMLMV declarado como supuesto verificado); la tabla no pasa de 5 columnas (§4-ter) y nunca constituye oferta en firme ni extiende la vigencia de 30 días.
- **Recargo de arquetipo `⇧50%` (interno):** si la señal citada está marcada en el catálogo, el `+50%` entra en el cálculo de horas y precio —**sobre** el nivel, nunca en lugar del nivel, heredado por las filas hijas de un `XL` descompuesto— pero **no se itemiza en el documento**: ni en la columna Modificadores, ni en Supuestos, ni como nota. El precio de la fila ya lo incorpora; el rastro vive en el catálogo, no en el entregable.
- **El gate aritmético (§4-ter) es obligatorio**: nunca persistir con `GATE_FAIL`.
- **Re-estimación del mismo requerimiento ⇒ mini-tabla Δ** vs el estimate anterior (filas nuevas / retiradas / cambiadas, con motivo).

---

## Suite de validación (baseline)

En `validation/` vive el **baseline de calibración** de la skill, producido en la prueba con los tres reportes de Vástago (02072026, calibración ÷4 definitiva):

- `validation/test-results.md` — artefacto de consolidación: tabla resumen de las 3 estimaciones (#23 $4,9M–$7,0M ✅ · #24 $5,8M–$8,2M ✅ · #25 $10,6M–$15,1M ⚠️ — recalibración −20% del 04/08/2026), detalle por requerimiento y QA de la skill (detección de múltiples, anti-doble-cobro, persistencia, señales promovidas, recalibraciones).
- `validation/estimates/*.md` — los 3 markdown fuente de esas estimaciones (documentos #23, #24 y #25 de `/panel/documents`), con filas, señales citadas, modificadores, horas y precios.

> **Nota de entorno:** los IDs #23–#25 y sus URLs `/panel/documents/<id>/edit` pertenecen al panel del **entorno donde corrió la prueba** (la dev machine del operador, 02/07/2026). En el panel de producción esos IDs corresponden a otros documentos; la carpeta destino debe configurarse previamente por ID en cada entorno (§6 resuelve el entorno explícitamente desde el fix del 01/08/2026).

**Regla de mantenimiento:** si cambian las reglas de la skill —tabla de precios/tarifa en `market-pricing.md`, señales o modificadores en `effort-indicators.md`, o el flujo de este SKILL.md— y el cambio **altera los números o la clasificación** del baseline, hay que **actualizar la suite en el mismo cambio**: recalcular las columnas afectadas de los 3 estimates (manteniendo horas/clasificación salvo que el cambio sea de catálogo), refrescar los totales y semáforos de `test-results.md`, y agregar allí una fila de QA que registre el cambio y su fecha. Si el cambio no altera números ni clasificación (p. ej. una señal nueva que el baseline no usa), basta la fila de QA. El baseline es la referencia para detectar regresiones de calibración: mismo input → mismos niveles y precios.
