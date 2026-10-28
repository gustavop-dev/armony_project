# Estimate: Vástago Conteo Diario Fase 1.5 — 02072026

> **ProjectApp · Calculadora de Requerimientos** — estimación por funcionalidad para implementación web, precios en COP sin IVA.

## 1. Resumen

Reemplazar el conteo de inventario actual de Vástago (por Ítem, que genera ajustes) por un **Conteo Diario de validación** por Grupo + Bodega: el usuario digita su conteo físico, el sistema lo compara contra el stock (con alertas Mín/Máx y seguimiento de traslados a 5 días), deja constancia en PDF firmable, guarda histórico consultable y envía un correo consolidado de auditoría a las 23:00. Es una épica de 12 tickets (CD-01…CD-12) sobre plataforma existente (Fase 1.5).

## 2. Descomposición por funcionalidad

| Funcionalidad | Nivel | Señal aplicada (cita literal) | Modificadores | Horas | Precio COP |
|---|---|---|---|---|---|
| CD-01 Modelo y persistencia del Conteo (encabezado día+sucursal + líneas Grupo+Bodega) | M | «CRUD de una entidad con extras acotados — validaciones, permisos básicos, búsqueda» | Modelo de datos +15% · Tests exigidos +15% | 31–44 | $530K–$750K |
| CD-02 Mín/Máx por Grupo+Sucursal (relación + pantalla de gestión SuperAdmin/Auditor) | M | «Configurar / parametrizar una regla de negocio antes fija en el código — UI para administrarla» | Pantalla nueva +20% · Modelo de datos +10% · Pruebas multi-rol +15% · Tests +15% | 38–54 | $620K–$880K |
| CD-03 Tabla principal por Grupo+Bodega (endpoint de filas: stock + traslados 5 días + alertas de color) | M | Familia espejo *Inventario / stock*: «campo de stock + alerta de mínimos sobre lo existente» | Tests +15% (atenuador *extiende algo existente* ya reflejado: la pantalla de conteo existe y se adapta) | 35–48 | $570K–$790K |
| CD-04 Detalle de Traslados (endpoint + modal con prefijos, Ítem y totales) | M | «Mostrar historial ya registrado — si los logs ya se guardan y solo hay que exponerlos» | Pantalla nueva (modal) +15% · Tests +15% | 26–36 | $440K–$620K |
| CD-05 Validación y estados (fila/lote, Válido/Inválido/Pendiente, Guardar bloqueado) | M | «Máquina de estados / cambios de estado — transiciones y reglas sobre un registro» | Tests +15% | 30–44 | $480K–$750K |
| CD-06 Observación sugerida automática + editable | M | *sin señal — por analogía* (cercanas: «Campos calculados / derivados» y «Autoguardado / borradores») | Tests +10% | 20–29 | $350K–$480K |
| CD-07 Borrador con vencimiento a 1 hora y reinicio en blanco | M | «Autoguardado / borradores (drafts).» | Tarea programada (Huey) +8–16 h · Tests +15% | 29–46 | $480K–$750K |
| CD-08 PDF del Conteo Diario (formato, datos de empresa, firma, descarga) | M | «Generación de reportes / archivos (Excel, PDF) — desde básicos hasta parametrizables» | Tests +15% · *Motor nuevo anulado*: el motor de PDF de reportes se cotiza en FA-EMP-01 (reporte 3) | 28–39 | $480K–$660K |
| CD-09 Histórico consultable y descargable por fecha | M | «Generación de reportes / archivos… incluye exportación simple desde una vista existente» | Pruebas multi-rol +15% · Tests +10% | 20–30 | $350K–$480K |
| CD-10 Correo diario consolidado 23:00 a Auditor/SuperAdmin | M | «Notificaciones por evento (in-app o correo)… Periódica o resumen (digest) → suma *Tarea programada*» | Tarea programada (Huey) +8–16 h · Tests +15% · *Motor nuevo anulado*: motor de correo con marca = FA-MAIL (reporte 3) | 29–46 | $480K–$750K |
| CD-11 Retiro de "generar ajustes" (endpoint, botón, pruebas, archivado del conteo viejo) | S | *sin señal — por analogía* (retiro controlado de un comportamiento ya entregado) | Tests +15% | 12–18 | $220K–$310K |
| CD-12 Cierre transversal (Manual/Ayuda, indicadores del dashboard, menú) | M | «Campos calculados / derivados — totales… que se recalculan» (reapuntar indicadores) + atenuador *extiende algo existente* | Tests +10% | 20–29 | $350K–$480K |

**Implicaciones técnicas por funcionalidad:**

- **CD-01:** dos modelos nuevos (`DailyCount`/`DailyCountLine`) + migraciones + constraints de unicidad (sucursal+día, encabezado+Grupo+Bodega) + serializers y rutas CRUD.
- **CD-02:** relación nueva Grupo–Sucursal (`GroupBranchThreshold`) + pantalla de gestión gateada por rol; valida `minimo <= maximo`.
- **CD-03:** service nuevo (`daily_count_service`) que compone stock del libro de movimientos + ventana fija de traslados 5 días + umbrales; rework de la pantalla de conteo de por-Ítem a por-Grupo+Bodega.
- **CD-04:** endpoint de detalle + modal; prefijos fijos por tipo de documento (TR/FC/SI/NC/AS/AF); FV/DV/AT solo se reservan (fase Facturación).
- **CD-05:** validación fila/lote contra stock, mensajes en español con nombre dinámico del Grupo, guard de Guardar (400 si hay inválidos).
- **CD-06:** generación del texto sugerido desde traslados + persistencia del texto editado.
- **CD-07:** borrador por usuario+sucursal+día con TTL 1 h; limpieza vía tarea Huey o cálculo perezoso.
- **CD-08:** formato PDF propio (encabezado, logo/NIT/razón social dinámicos, marca "formato de Vástago", firma); fallback si no hay datos de empresa. Consume el motor de FA-EMP-01.
- **CD-09:** consulta por (sucursal, fecha) de solo lectura; reutiliza el PDF de CD-08; Auditor/SuperAdmin ven todas las sucursales.
- **CD-10:** tarea Huey 23:00 que consolida sucursales activas y delega en el motor FA-MAIL con destinatarios híbridos.
- **CD-11:** retiro de endpoint/service/botón de ajustes + reescritura de pruebas + decisión de archivado del histórico por-Ítem.
- **CD-12:** reescritura del manual in-app, reapuntar "Stock bajo" y "Diferencias de conteo" del dashboard al nuevo flujo, ítem de menú.

## 3. Totales

- **Horas:** 318–463 h
- **Precio total:** $5,4M–$7,7M
- **Semáforo:** ✅ Sweet spot (menos de $12M)

> [!TIP]
> La épica completa queda en zona sweet spot: se puede presentar como **una sola propuesta**, sin fricción comercial. La secuencia de la sección 5 queda como orden de entrega recomendado, no como fraccionamiento obligatorio.

## 4. Observaciones

- **Qué se separa y por qué:** los tres motores transversales que esta épica consume **no se cotizan aquí** porque pertenecen al reporte 3 (Funcionalidades adicionales): motor de PDF de reportes + Datos de la Empresa (**FA-EMP-01**, bloquea CD-08/CD-09), motor de correo con identidad de marca y destinatarios híbridos (**FA-MAIL**, bloquea CD-10) y matriz de permisos / sucursal única por rol (**FA-PERM**/**FA-USER**). Se construyen una vez y los reutiliza todo lo demás — cobrarlos aquí sería doble cobro contra el estimado del reporte 3.
- **Exigencia de calidad explícita:** el reporte enumera cobertura pytest + Jest + Playwright ticket por ticket; por eso el modificador *Tests exigidos* aplica en todas las filas (+10–15%). No es opcional: está en el alcance acordado con el cliente.
- **Adyacencias que se abren:** ajustes de inventario en el **Inventario Detallado** (fase posterior ya anunciada) · **Facturación** (los prefijos FV/DV/AT quedan reservados) · paso de **recepción de traslados** (descartado hoy, evaluable a futuro) · más reportes/exportaciones sobre el histórico del conteo · indicadores adicionales del dashboard alimentados por la validación.
- **Consistencia con estimaciones previas:** la estimación #22 (01072026) se emitió con la **calibración anterior** ($5,5M–$9,9M por gestión con alerta de stock); con la tarifa recalibrada, las filas equivalentes de esta tabla (CD-02+CD-03) suman $1,2M–$1,7M — la diferencia es la recalibración de tarifa, no un cambio de criterio.

## 5. Estrategia comercial

**Cabe en una sola propuesta (sweet spot).** No se requiere fraccionar. Como **orden de entrega** interno se recomienda la secuencia por dependencias: (1) núcleo del conteo de validación (CD-01/02/03/05/11), (2) seguimiento y constancia (CD-04/06/08/09 — requiere FA-EMP-01 del reporte 3), (3) operación y auditoría (CD-07/10/12 — requiere FA-MAIL del reporte 3).

## 6. Supuestos y exclusiones

- Precios en COP sin IVA · tarifa blended ≈ $16.500/h (recalibración 18/08/2026) · implementación **web** (el reporte no declara PWA ni app nativa; si aplicara PWA: +30%).
- **Recalibración 18/08/2026 (+10%, market-pricing v1.7):** columnas de precio, totales y tablas de fases reescalados ×1,10 por directriz del dueño; horas, niveles, señales y modificadores sin cambios, y el semáforo no cambia de zona.
- **Reemplaza la estimación #23 del 02/07/2026; cambio respecto a la versión previa:** recalibración de precios al mercado colombiano (**÷4**, ajusta el ÷3,5 provisional). Horas, niveles, señales y modificadores sin cambios.
- **Recalibración 04/08/2026 (−20%, market-pricing v1.6):** columnas de precio y totales reescalados ×0,8 por directriz del dueño; horas, niveles, señales y modificadores sin cambios.
- **Plataforma existente (Fase 1.5):** se reutilizan Huey (tareas), auth/roles, filtrado por sucursal y la librería de PDF de etiquetas — atenuador aplicado; ninguna fila se cotizó como greenfield.
- **Motores excluidos de este estimado** (se cotizan en el reporte 3): FA-EMP-01 (Datos de la Empresa + motor de PDF de reportes), FA-MAIL (correo con marca), FA-PERM/FA-USER (matriz de permisos y sucursal única). Si el reporte 3 no se contratara, esos motores deben sumarse aquí (≈ 2–3 filas M/L adicionales).
- **§13-J Concurrencia del conteo:** el reporte la deja sin definir. Se asume "último que guarda gana" sin bloqueo; si el cliente exige bloqueo por sucursal, CD-05/CD-07 suben +20–40% (modificador *Concurrencia / atomicidad*).
- **§13-K "Configurable por cliente" de Mín/Máx:** se asume que significa *valores propios por cliente* (ya cubierto por CD-02). Si significa *regla/alerta parametrizable como panel por cliente*, CD-02 sube a `L` (+ ≈ $350K–$700K).
- Los documentos FV/DV/AT **no se construyen** (solo se reserva el prefijo); la facturación es fase posterior y, si fuera electrónica DIAN, sería un estimado XL regulatorio aparte.
- No incluye infraestructura recurrente, licencias de terceros ni migración del histórico del conteo por-Ítem (el archivado se decide en CD-11; una migración de datos sería ítem aparte).
- Estimación sujeta a refinamiento tras análisis detallado.

> [!IMPORTANT]
> No cerrar precio fijo hasta aclarar §13-J (comportamiento ante conteos concurrentes de la misma sucursal) y §13-K (alcance real de "configurable por cliente" en Mín/Máx), y hasta confirmar que FA-EMP-01 y FA-MAIL (reporte 3) se contratan — CD-08, CD-09 y CD-10 dependen de ellos.

---

**Requerimiento original:** «Vástago — Conteo Diario · Reporte de funcionalidad refinado — versión 3 (Fase 1.5), TORRIOS SAS, 26/06/2026: conteo diario de validación por Grupo + Bodega (no ajusta inventario), con alertas Mín/Máx por Grupo+Sucursal, seguimiento de traslados a 5 días con detalle por documento prefijado, observación sugerida + editable, validación fila/lote con estados Válido/Inválido/Pendiente, guardado bloqueado hasta validez total, PDF con datos de empresa y firma, histórico por fecha, borrador con vencimiento 1 h, correo diario consolidado 23:00 a Auditor/SuperAdmin, retiro del flujo de ajustes, y backlog CD-01…CD-12 con dependencias hacia FA-EMP-01/FA-MAIL/FA-PERM/FA-USER del tercer reporte.»

— *ProjectApp · Calculadora de Requerimientos*
