# Estimate: Vástago Inventario Detallado Fase 1.5 — 02072026

> **ProjectApp · Calculadora de Requerimientos** — estimación por funcionalidad para implementación web, precios en COP sin IVA.

## 1. Resumen

Construir el módulo **Inventario Detallado** de Vástago: conteo mensual referencia por referencia con lector de código de barras, comparado contra una "foto" del stock. Incluye prerrequisito de Conteo Diario válido, código alterno único, captura con validación de pertenencia, autoguardado, segundo conteo solo sobre diferencias, dos tableros de estado, histórico por periodo, bloqueo de concurrencia, vigencia de 5 días con autoborrado, y correo mensual consolidado (día 29, 23:00) + reporte en tiempo real. Épica de 14 tickets (ID-01…ID-14) sobre plataforma existente (Fase 1.5); a diferencia del Conteo Diario, aquí el módulo es **enteramente nuevo** (no adapta una pantalla existente).

## 2. Descomposición por funcionalidad

| Funcionalidad | Nivel | Señal aplicada (cita literal) | Modificadores | Horas | Precio COP |
|---|---|---|---|---|---|
| ID-01 Código alterno único y obligatorio en Ítem (constraint + limpieza de catálogo + reporte de duplicados) | M | «Validaciones de negocio complejas — cross-field, contra el backend, con reglas» | Carga inicial / backfill (limpieza del catálogo) +20% · Tests exigidos +15% | 24–35 | $400K–$570K |
| ID-02 Prerrequisito "último Conteo Diario válido" (guard + bloqueo + banner) | M | «Validaciones de negocio complejas — … contra el backend, con reglas» | Tests +15% | 21–28 | $350K–$480K |
| ID-03 Cargar Inventario / "foto" (snapshot + tablero de Captura en Asignado) | M | «Versionado ligero / snapshots» (la "foto" es una captura del estado como base de comparación) | Pantalla nueva +20% · Modelo de datos +15% · Tests +15% | 39–54 | $660K–$880K |
| ID-04 Formulario de captura (código alterno manual/lector, pertenencia al Grupo, agrupar repetidas, Total Contados) | M | «Generación / lectura de códigos QR o de barras — … escanear … sube dentro de `M` o a `L` según el flujo» | Pantalla nueva +20% · Modelo de datos +10% · Tests +15% | 41–55 | $660K–$880K |
| ID-05 Guardar manual + autoguardado silencioso cada 3 min | M | «Autoguardado / borradores (drafts).» | Tests +15% | 21–30 | $350K–$480K |
| ID-06 Finalizar y comparar → resultado (Referencia OK / con Diferencia / Conteo 0) | M | «Validaciones de negocio complejas — cross-field, contra el backend, con reglas» | Pantalla nueva (resultado) +15% · Tests +15% | 34–47 | $570K–$790K |
| ID-07 Segundo conteo (solo diferencias en 0, rechazos, desenlace OK/con Diferencia) | M | «Máquina de estados / cambios de estado — transiciones y reglas sobre un registro» | Tests +15% | 25–37 | $400K–$620K |
| ID-08 Acciones del tablero (Papelera, Rehacer, Borrar Finalizados solo OK, desaparición automática) | M | «Acciones masivas / bulk — seleccionar N registros y aplicar (eliminar, cambiar estado…)» | Tests +15% | 23–32 | $400K–$530K |
| ID-09 Ver Estado del Inventario (tablero de seguimiento del mes, 4 estados propios) | M | «Mostrar historial ya registrado — si los logs ya se guardan y solo hay que exponerlos» | Pantalla nueva +15% · Tests +10% | 20–30 | $350K–$480K |
| ID-10 Vista Finalizado (Periodo mensual + filtros Estado/Periodo + Detalle Lupa) | M | «Combo de listado server-side — paginación + ordenamiento + búsqueda … manteniendo los filtros» | Pantalla nueva +15% · Modelo de datos (Period) +10% · Tests +15% | 28–42 | $480K–$700K |
| ID-11 Bloqueo de concurrencia por Grupo+Bodega (reserva + mensaje al segundo usuario) | M | *sin señal — por analogía* (bloqueo/reserva exclusiva de un registro por usuario) | Concurrencia / atomicidad +30% · Tests +15% | 26–38 | $440K–$620K |
| ID-12 Vigencia 5 días: autoborrado + liberación del bloqueo | M | «Vencimientos / renovaciones con alertas — fechas de expiración … (suma *Tarea programada*)» | Tarea programada (Huey) +8–16 h · Tests +15% | 24–39 | $400K–$660K |
| ID-13 Correo mensual consolidado (día 29, 23:00) + reporte en módulo Reportes | M | «Notificaciones por evento … Periódica o resumen (digest) → suma *Tarea programada*» + «Generación de reportes / archivos … parametrizables» | Pantalla nueva (reporte) +15% · Tarea programada +8–16 h · Tests +15% · *Motor de correo anulado* (FA-MAIL, reporte 3) | 39–60 | $660K–$970K |
| ID-14 Manual/Ayuda: sección de Inventario Detallado | S | «Página estática — términos, ayuda, política, información (sin CMS)» | Tests +10% (indexación en buscador del manual) | 12–18 | $220K–$310K |

**Implicaciones técnicas por funcionalidad:**

- **ID-01:** `unique=True` + obligatoriedad en el código alterno del Ítem, migración con detección de colisiones, reporte de duplicados/vacíos; precondición para la captura y para Code128 (FA-LBL, reporte 3).
- **ID-02:** service que evalúa el último Conteo Diario de la sucursal (depende de la épica CD ya construida) + guard en la vista Pendiente.
- **ID-03:** modelos nuevos `DetailedCount` + `DetailedCountSnapshotLine`, snapshot atómico del stock (solo lectura, no congela la operación), tablero con una fila por Grupo+Bodega.
- **ID-04:** modelo `DetailedCountCaptureLine`, endpoint de captura que resuelve por código alterno, valida pertenencia al Grupo y agrupa repetidas; componente con autofocus, orden LIFO y Total Contados.
- **ID-05:** endpoint `save` idempotente; timer de 3 min en el cliente, sin diálogo (silencioso).
- **ID-06:** comparación captura vs. snapshot, resultado por referencia con Conteo 0 para las no capturadas; **no toca `Movement`** (solo reporta; el ajuste es fase posterior).
- **ID-07:** modo segundo conteo (count_type=2) con lista restringida y rechazos con texto exacto; dos oportunidades y desenlace definitivo.
- **ID-08:** transiciones Papelera/Rehacer/Borrar Finalizados (solo "Finalizado OK") + reglas de desaparición automática del tablero.
- **ID-09:** endpoint de seguimiento con mapeo a los 4 estados propios del tablero Ver Estado (no se unifican con los del tablero de Captura).
- **ID-10:** campo Period mensual, filtros Estado/Periodo, tabla + modal Detalle referencia por referencia; admite varios finalizados del mismo Grupo+Bodega por periodo.
- **ID-11:** `locked_by`/`locked_at` con `select_for_update()`; 409 + mensaje con Grupo/Bodega/Usuario interpolados.
- **ID-12:** tarea Huey que purga cargas con >5 días (todos los estados) y libera el lock; el tablero queda limpio y obliga a recargar.
- **ID-13:** tarea Huey (día 29, 23:00) que arma el consolidado por sucursal y delega en FA-MAIL; el mismo service alimenta el reporte en tiempo real del módulo Reportes.
- **ID-14:** sección nueva del manual in-app (dos tableros, segundo conteo, concurrencia, vigencia) indexada en el buscador.

## 3. Totales

- **Horas:** 377–545 h
- **Precio total:** $6,4M–$9,0M
- **Semáforo:** ✅ Sweet spot (menos de $12M)

> [!TIP]
> La épica completa queda en zona sweet spot: se puede presentar como **una sola propuesta**. La secuencia de la sección 5 queda como orden de entrega recomendado, no como fraccionamiento obligatorio.

## 4. Observaciones

- **Qué se separa y por qué:** el motor de correo con marca (**FA-MAIL**), la matriz de permisos y el renombre del menú (**FA-PERM**), la sucursal única por rol (**FA-USER**) y la simbología Code128 de etiquetas (**FA-LBL-04**) pertenecen al reporte 3 y **no se cotizan aquí** — cobrarlos en ambos sería doble cobro. ID-13 depende de FA-MAIL.
- **Dependencia de la épica Conteo Diario:** ID-02 (el prerrequisito) exige que la épica CD (estimación #23) esté construida — encadena el cronograma de las dos épicas.
- **Bloqueo externo (cronograma, no precio):** la limpieza del catálogo de ID-01 requiere que **el cliente resuelva los códigos alternos duplicados/vacíos**; la migración no puede correr hasta entonces.
- **Exigencia de calidad explícita:** igual que en la épica CD, el reporte enumera cobertura pytest + Jest + Playwright ticket por ticket → modificador *Tests exigidos* en todas las filas (+10–15%).
- **Adyacencias que se abren:** **ajustes desde el Inventario Detallado** (fase posterior ya pactada — la pantalla de resultados se diseña previéndolo) · **RFID** (Fase III, ya anunciada) · exportar/imprimir la vista Finalizado (hoy excluida explícitamente) · timeout corto de liberación del lock (§12-I) · parametrizar los valores hoy fijos (vigencia, intervalo de autoguardado).
- **Consistencia con estimaciones previas:** la épica hermana Conteo Diario (#23, recalibrada el mismo día) quedó en $5,4M–$7,7M con 12 tickets adaptando una pantalla existente; esta épica da $6,4M–$9,0M con 14 tickets y un módulo enteramente nuevo — la diferencia (+15–18%) es proporcional al alcance.

## 5. Estrategia comercial

**Cabe en una sola propuesta (sweet spot).** No se requiere fraccionar. Como **orden de entrega** interno se recomienda la secuencia por dependencias: (1) catálogo y carga (ID-01/02/03), (2) captura y comparación (ID-04/05/06), (3) ciclo completo del tablero (ID-07/08/09/10), (4) robustez y cierre (ID-11/12/13/14 — ID-13 requiere FA-MAIL del reporte 3). Si desde el día uno habrá **varios usuarios contando en la misma sucursal**, adelantar ID-11 (bloqueo de concurrencia) al bloque 2.

## 6. Supuestos y exclusiones

- Precios en COP sin IVA · tarifa blended ≈ $16.500/h (recalibración 18/08/2026) · implementación **web** (sin PWA ni app nativa declaradas; PWA sumaría +30%).
- **Recalibración 18/08/2026 (+10%, market-pricing v1.7):** columnas de precio, totales y tablas de fases reescalados ×1,10 por directriz del dueño; horas, niveles, señales y modificadores sin cambios, y el semáforo no cambia de zona.
- **Reemplaza la estimación #24 del 02/07/2026; cambio respecto a la versión previa:** recalibración de precios al mercado colombiano (**÷4**, ajusta el ÷3,5 provisional). Horas, niveles, señales y modificadores sin cambios.
- **Recalibración 04/08/2026 (−20%, market-pricing v1.6):** columnas de precio y totales reescalados ×0,8 por directriz del dueño; horas, niveles, señales y modificadores sin cambios.
- **Plataforma existente (Fase 1.5):** se reutilizan Huey, auth/roles, filtrado por sucursal, tabla genérica/ReportTable y el exportador existente. El módulo Inventario Detallado en sí es nuevo (de ahí los modificadores de pantalla nueva en 6 filas).
- **Excluidos (se cotizan en el reporte 3):** FA-MAIL (motor de correo con marca y destinatarios híbridos), FA-PERM (matriz de permisos + renombre del menú), FA-USER (sucursal única por rol), FA-LBL-04 (Code128 sobre el código alterno). La épica **Conteo Diario** se cotizó aparte (#23).
- **§12-I Liberación del bloqueo:** se asume que el lock se libera con el **autoborrado a los 5 días** (y con terminar/recargar/papelera). Si el negocio decide un timeout más corto (p. ej. liberar tras N horas de inactividad), es un ajuste menor dentro de ID-12 (≤ +8 h).
- **Ajuste de stock desde el Inventario Detallado:** fuera de alcance (fase posterior). Finalizar **solo reporta**.
- **RFID:** Fase III, fuera de alcance.
- **Limpieza del catálogo (ID-01):** el esfuerzo cotizado cubre la migración, el constraint y el reporte de depuración; la **resolución de negocio** de los duplicados la hace el cliente (bloqueo externo de cronograma).
- Elementos declarados **fijos** (vigencia 5 días, autoguardado 3 min, periodo, estados, filtros, columnas): cotizados como fijos; volverlos configurables sería alcance nuevo (`M` por parametrización).
- No incluye infraestructura recurrente ni licencias. Estimación sujeta a refinamiento tras análisis detallado.

> [!IMPORTANT]
> No cerrar precio fijo hasta: (1) definir la política de **liberación del bloqueo de concurrencia** (§12-I — autoborrado a 5 días vs. timeout corto); (2) confirmar la contratación de **FA-MAIL** (reporte 3), del que depende ID-13; y (3) acordar el plan de **limpieza de códigos alternos** con el cliente, que condiciona el arranque de la captura.

---

**Requerimiento original:** «Vástago — Inventario Detallado · Reporte de funcionalidad refinado — versión 3 (Fase 1.5), TORRIOS SAS, 26/06/2026: conteo mensual referencia por referencia con lector de código de barras contra una "foto" del inventario; prerrequisito de último Conteo Diario válido; código alterno único; captura con validación de pertenencia y agrupación de repetidas; guardar + autoguardado silencioso cada 3 min; finalizar solo reporta (Referencia OK / con Diferencia / Conteo 0); segundo conteo solo sobre diferencias con desenlace definitivo; tableros de Captura y Ver Estado con juegos de estados propios; vista Finalizado con Periodo mensual y Detalle; bloqueo de concurrencia por Grupo+Bodega con mensaje; vigencia de 5 días con autoborrado; correo mensual consolidado día 29 a las 23:00 a Auditor/SuperAdmin + reporte en tiempo real en módulo Reportes; backlog ID-01…ID-14 con dependencias hacia la épica Conteo Diario y FA-MAIL/FA-PERM/FA-USER/FA-LBL del tercer reporte.»

— *ProjectApp · Calculadora de Requerimientos*
