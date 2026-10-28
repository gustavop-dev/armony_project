# Esfuerzo, Precio y Reglas de Mercado — Calculadora de Requerimientos (v1.7)

> Complemento de `effort-indicators.md`. Traduce el nivel de esfuerzo a horas y precio COP, y define las reglas comerciales del mercado colombiano.

## Premisas base

- **Implementación web por defecto.** La calculadora está calibrada para web. La plataforma solo entra como modificador excluyente: web = sin recargo · PWA = `+30%` · app móvil nativa (iOS/Android + tiendas) = `+60%` (aplicado al final, `×1,6` sobre el resultado ya modificado).
- **Desarrollo desde cero (greenfield)** salvo que la descripción declare que se extiende algo existente.
- **Cliente PYME colombiano.** Precios en **COP, más IVA**: el valor cotizado **no incluye IVA** y se presenta siempre con la marca `+ IVA` (p. ej. `$7.000.000 + IVA`). IVA colombiano vigente: **19%**. Nunca cotizar un valor con IVA incluido sin declararlo, ni omitir la marca en las tablas de inversión.
- **Tarifa de venta blended de referencia: ≈ $16.500 COP/hora** (≈ US$4,8 a TRM ≈ $3.443/USD). *Recalibrada el 18/08/2026:* **+10%** por directriz del dueño sobre la tarifa del 04/08/2026 (≈ $15.000/h — que venía de un −20% sobre los ≈ $18.750/h del 02/07/2026, a su vez resultado de dividir ÷4 la calibración de mercado desarrollado, ≈ $75.000/h).
- **Killer: $20.000.000 COP** — una propuesta (la **suma** de los requerimientos, no un ítem suelto) por encima de ese techo tiende a ser rechazada. Obligatorio fragmentar.
- **Granularidad:** se estima funcionalidad por funcionalidad; el proyecto es la suma.
- **Vigencia de la estimación: 30 días.** Todo estimate declara "precios válidos por 30 días desde su fecha"; pasado el plazo se re-emite en vez de honrarse (la tarifa y el catálogo evolucionan — la recalibración ÷4 cambió todos los precios en un solo día).
- **Calibrada exclusivamente para cliente PYME colombiano (COP + IVA).** Cliente extranjero / cotización en USD: **fuera de alcance** — no usar esta tarifa ni el semáforo. Referencia histórica: la tabla previa a las recalibraciones (02/07/2026 ÷4 · 04/08/2026 −20%) aproximaba un mercado desarrollado; en ese caso, cotización manual del dueño.

### Qué incluye y qué no (por defecto)

- **Incluye:** análisis, desarrollo, pruebas básicas, despliegue inicial y garantía corta de estabilización.
- **No incluye:** infraestructura/hosting recurrente, licencias de terceros, soporte continuo, capacitación extensa ni migración de datos legados — salvo mención explícita en el alcance.

## Niveles: esfuerzo → horas → precio

| Nivel | Pts | Perfil típico | Horas | Precio COP | ≈ USD |
|---|---|---|---|---|---|
| **XS** | 1 | Cambio de configuración, un campo, validación básica, enlace simple. | 2–7 | $35K – $114K | $10–33 |
| **S** | 2 | Ajuste de UI/plantilla, modal, correo básico, contador simple. | 7–20 | $114K – $334K | $33–97 |
| **M** | 3 | CRUD estándar con extras, generación de archivos, permisos, lógica condicional. A menudo se apoya en algo existente. | 20–50 | $334K – $774K | $97–225 |
| **L** | 5 | **Un feature completo desde cero**: backend + frontend robustos (a veces + una integración, que lo lleva al techo del rango). | 55–90 | $880K – $1,5M | $256–447 |
| **XL** | 8 | **Referencia de magnitud, NO cotizable como ítem.** Exige descomposición obligatoria en 2+ filas `S`/`M`/`L` (cada una suele ser un L). El rango solo sirve para dimensionar la conversación. | 90–200 | $1,5M – $3,3M | $447–958 |

**Fuente de verdad:** la **columna de precio** manda (es la calibración comercial del dueño frente al mercado); las horas son indicativas. Los pequeños desfases entre horas × tarifa y el rango de precio, y el colchón de horas entre `M` (50) y `L` (55), son deliberados: margen pre-modificador. Los puntos (Pts) son un *shorthand* de magnitud, no entran en fórmulas.

## Orden de cálculo

1. **Nivel base por funcionalidad** — el indicador de esfuerzo más alto que la describe fija XS/S/M/L/XL, **citando la señal literal** del catálogo.
2. **Modificadores** — recorrer la tabla completa marcando cuáles aplican. Fórmula:

   `horas = base × (1 + Σ% aditivos) × factor transversal + horas fijas (cron)`

   Si aplica app móvil nativa: `× 1,6` **al final**, sobre el resultado ya modificado. Anti-doble-conteo: *Pantalla nueva* y *Modelo de datos* nunca sobre un `L`.
3. **Rango, no punto** — el precio siempre se expresa como rango (piso–techo). El piso usa el extremo bajo de horas; el techo, el alto.
4. **Suma y chequeo de killer** — se suman las funcionalidades (verificar que la suma de filas = total y que piso ≤ techo). Si el techo total supera $20M, se activan las reglas de mercado (fases o versiones).

## Zonas de precio (sobre la SUMA de la propuesta)

| Zona | Rango total | Acción |
|---|---|---|
| ✅ **SWEET SPOT** | < $12M | Propuesta única, sin fricción. |
| ⚠️ **FRICCIÓN** | $12M – $20M | Viable, pero conviene ofrecer fases o versionado para bajar el ticket inicial. |
| ⛔ **KILLER** | > $20M | Rechazo probable. Obligatorio fragmentar antes de presentar. |

> **Nota (recalibración 02/07/2026):** los umbrales del semáforo **no** se dividieron con la tarifa. Miden la **disposición de pago absoluta** del cliente colombiano por propuesta (cuánto está dispuesto a firmar), no el costo de producción — por eso permanecen en $12M/$20M aunque los precios por talla bajaran ÷4.

### Estrategia A — Fragmentación por fases

- Cada fase es **desplegable y útil sola** (nunca "medio CRUD").
- Cada fase queda idealmente en **≤ $12–15M** para mantenerse fuera de la zona killer.

### Estrategia B — Versionado (V1 + posteriores)

- **V1** = núcleo operativo que el cliente *necesita* para arrancar.
- Se difiere a V2/V3 lo que *mejora* la operación pero no la bloquea: reportes, notificaciones, filtros guardados, dashboards.
- Las **adyacencias** son las candidatas naturales a versiones posteriores.

## Proyección de precios año a año

Los precios de este catálogo están expresados en pesos del **año de emisión** del estimate. Para proyectar el precio de un requerimiento a años siguientes se aplica el **reajuste anual de ProjectApp** — la misma mecánica de reajuste que ProjectApp usa en sus servicios recurrentes:

```
reajuste anual    = Δ%SMLMV + 12%                              (12% = componente fijo ProjectApp)
precio año N+1    = precio año N × (1 + reajuste anual)
precio año base+k = precio año base × (1 + reajuste anual)^k   (forma cerrada, compuesta)
```

- **Δ%SMLMV** — porcentaje de incremento decretado del Salario Mínimo Legal Mensual Vigente en Colombia. Es un dato verificable año a año; cada estimate **declara el valor usado como supuesto**. Para años cuyo decreto aún no existe se usa el último incremento decretado.
- **Componente fijo: 12%** — definido por ProjectApp. Si el dueño lo cambia, se cambia **aquí** (única fuente); ningún documento lo hardcodea por su cuenta.
- **Reajuste compuesto:** cada año se aplica sobre el precio ya reajustado del año anterior, no sobre el original. La forma cerrada `(1 + reajuste)^k` es la que conviene mostrar cuando el horizonte pasa de dos años.
- **Horizonte: año de emisión + 4 años.** La tabla del estimate lleva **5 filas** — la base sin reajuste y cuatro proyectadas — cada una con su **factor acumulado** respecto del año base, para que el salto sea legible sin rehacer la cuenta.
- **La fórmula se imprime en el documento.** No basta con declarar el supuesto en prosa: el estimate muestra el bloque de fórmula y su instancia con los números del año (`reajuste = X% + 12% = Y%`), porque el reajuste es un argumento comercial y un número sin su derivación no se puede discutir.
- **Ejemplo (datos vigentes, emisión 2026):** el SMLMV 2026 subió **23%** (Decreto 0159 del 19/02/2026), luego el reajuste anual es 23% + 12% = **35%** → factor **1,35** por año. Un requerimiento de $1,0M en 2026 se proyecta en **$1,4M** (2027, ×1,35), **$1,8M** (2028, ×1,82), **$2,5M** (2029, ×2,46) y **$3,3M** (2030, ×3,32).
- **Carácter informativo.** La proyección **no** es una oferta en firme de precios futuros: la vigencia del estimate sigue siendo **30 días**. Solo anticipa el orden de magnitud del reajuste si el mismo alcance se contratara en años posteriores — es un argumento comercial para decidir **hoy**, no una tarifa congelable.

## Si el cliente contrapropone

Las Estrategias A/B son **preventivas** (se deciden antes de presentar). Cuando el cliente ya tiene el precio y contrapropone, el orden de respuesta es:

1. **Moverse al piso del rango, a cambio de algo.** El precio siempre se presentó como piso–techo: aceptar el piso es legítimo si se obtiene una contraparte (anticipo mayor, cronograma flexible, testimonio/caso de estudio, cierre esta semana).
2. **Por debajo del piso: recortar alcance, nunca tarifa.** Las candidatas a V2 y las adyacencias detectadas en la estimación SON la lista de recorte ya computada — se retiran filas completas y se re-declara el total. Bajar la tarifa sin recortar enseña que el precio estaba inflado.
3. **Tope de descuento sin recorte: ~10%.** Más allá, se re-emite el estimate con alcance menor (documento nuevo versionado — nunca una cifra negociada por chat sin documento).

## Trabajo recurrente (referencia)

El estimate cotiza **proyectos**; el trabajo recurrente se cotiza aparte con estas reglas:

- **Paquetes de requerimientos prepagados:** cupos XS/S/M, sin estimación de horas por solicitud; catálogo vigente en ProjectApp. Compra única, vigencia configurable (inicial: 12 meses desde el pago), sin intercambio de tallas. L/XL requieren levantamiento y cotización aparte; la garantía no consume cupos.
- **SLA formal: no se ofrece** — con un equipo de este tamaño sería un compromiso ficticio; se acuerdan prioridades y programación para los cupos contratados.
- **Hosting / infraestructura recurrente:** ítem aparte siempre (nunca dentro de la bolsa ni del estimate).

## Adyacencias — mapa "abre la puerta"

Anticiparlas siempre: no para cobrarlas de una, sino para ordenarlas en fases/versiones y no quedar cortos en el análisis.

| Disparador | Abre la puerta a |
|---|---|
| CRUD con tabla / listado | Filtros · ordenamiento · paginación · búsqueda · exportar (Excel/PDF) · acciones masivas · columnas configurables |
| Filtros | Preferencias guardadas · filtros combinados/avanzados · vistas guardadas por usuario |
| Cualquier dato listado | Reportes (PDF/Excel) · dashboards · KPIs · envío programado de reportes |
| Cambios de estado / eventos | Notificaciones in-app · correo · push · bitácora de eventos |
| Acciones de usuario | Trazabilidad / auditoría (quién, cuándo, qué) · historial de cambios |
| Formularios | Validaciones · lógica condicional · carga de archivos · autoguardado |
| Carga de archivos | Procesamiento de imágenes · almacenamiento · previsualización · antivirus |
| Multiusuario | Permisos / roles · control de concurrencia · invitaciones |
| Documentos | Motor de PDF · plantillas · numeración/secuencias · firmas |
| Tiempo / recurrencia | Tareas programadas (Huey) · recordatorios · vencimientos |
| Solicitudes / aprobaciones | Escalamiento · SLA · delegación · reportes de tiempos de respuesta |
| Documentos comerciales | Conversión entre documentos (cotización→orden→factura) · exportación contable · pagos |

## Cuándo decir "sepáralo y constrúyelo aparte"

- **Mezcla un motor reutilizable** (PDF, correo, etiquetas) con una funcionalidad puntual → separar el motor: se cobra una vez y habilita todo lo que venga después.
- **Mezcla una pieza transversal** (notificaciones, auditoría, permisos, búsqueda global) → construirla una sola vez como feature/servicio reutilizable, no repetida pantalla por pantalla.
- **Empaqueta 2+ funcionalidades grandes** (M/L/XL) → separar para poder fasear y mantenerse bajo el techo killer.
- **Es claramente un V2** — mejora la operación pero no bloquea el arranque → marcarla como candidata a versión posterior.

> **Transversalidad y costo:** cuando algo es transversal, su costo no es fijo — escala con el número de puntos donde se integra. Advertirlo en el output: «construir una vez, reutilizar N veces», no estimarlo como una pantalla aislada.

## Supuestos que siempre se declaran

Precios en COP **más IVA** (presentados como `+ IVA`; IVA vigente 19%) · implementación web (PWA/nativa solo si se declara, con su recargo) · desarrollo desde cero · tarifa blended ≈ $16.500/h (recalibración 18/08/2026) · **precios válidos por 30 días desde la fecha del documento** · proyección año a año informativa a **4 años** con la regla `Δ%SMLMV + 12%` (declarando el Δ%SMLMV supuesto y mostrando la fórmula) · no incluye infraestructura recurrente, licencias de terceros ni migración de datos legados salvo mención explícita · estimación sujeta a refinamiento tras análisis detallado.

---

## Qué cambió en esta versión (v1.7 — recalibración +10% y proyección a 4 años)

**Directriz del dueño 18/08/2026:** dos cambios.

1. **Precio +10%.** La tarifa blended sube de $15.000/h a **$16.500/h** y los rangos por talla se reescalan ×1,10 (p. ej. `M` pasa de $304K–$704K a **$334K–$774K**; `L`, de $800K–$1,4M a **$880K–$1,5M**). Es el primer ajuste al alza del año, después del ÷4 del 02/07 y del −20% del 04/08.
2. **Proyección a 4 años con la fórmula a la vista.** El horizonte pasa de 2 a **4 años siguientes** (5 filas contando la base), la tabla gana una columna de **factor acumulado**, y el estimate ahora **imprime el bloque de fórmula** y su instancia con los números del año en vez de limitarse a declarar el supuesto en prosa.

**Sin cambios:** horas por nivel, señales, modificadores, la regla de reajuste en sí (`Δ%SMLMV + 12%`, compuesta, informativa) ni los umbrales del semáforo ($12M/$20M — miden disposición de pago absoluta y no se recalibran con la tarifa). La suite `validation/` se reescaló ×1,10 en el mismo cambio; ningún semáforo del baseline cambió de zona.

---

## Qué cambió en la versión anterior (v1.6 — recalibración −20%)

**Directriz del dueño 04/08/2026:** los rangos de precio por talla y la tarifa blended bajan **−20%** (tarifa: $18.750/h → **$15.000/h**; p.ej. `M` pasa de $380K–$880K a $304K–$704K). **Sin cambios** en horas por nivel, señales, modificadores, regla de proyección año a año (Δ%SMLMV + 12%) ni umbrales del semáforo ($12M/$20M — miden disposición de pago absoluta y no se recalibran con la tarifa). La suite `validation/` se reescaló ×0,8 en el mismo cambio (semáforos del baseline sin cambio de zona).

---

## Qué cambió en v1.5 (proyección de precios año a año)

**Directriz del dueño 03/08/2026:** se agregó la regla de **proyección de precios año a año** — `precio año N+1 = precio año N × (1 + (Δ%SMLMV + 12%))`, compuesta, con el Δ%SMLMV declarado como supuesto y carácter informativo (la vigencia de 30 días no cambia). El estimate gana una sección dedicada con la proyección del total a los 2 años siguientes (plantilla §5 del SKILL). **Sin cambios** en tarifa, tallas, horas, señales ni umbrales del semáforo — el baseline conserva sus números.

---

## Qué cambió en v1.4 (reglas comerciales del ciclo de venta)

**Revisión metodológica 01/08/2026 (lente de proceso):** se agregaron las reglas comerciales que faltaban alrededor del estimate — **vigencia de 30 días** (premisa + supuesto declarado) · **guía de contraoferta** (piso a cambio de algo → recorte de alcance, nunca tarifa → tope ~10% → re-emitir) · **trabajo recurrente** (bolsa de horas de referencia; SLA formal declarado no-ofrecido) · **cliente extranjero/USD declarado fuera de alcance**. **Sin cambios** en tarifa, tallas, horas ni umbrales del semáforo.

---

## Qué cambió en v1.3 (recalibración al mercado colombiano)

**Recalibración de precios (02/07/2026, directriz del dueño tras probar la calculadora con los tres reportes de Vástago):** los rangos por talla producían valores justos para un mercado desarrollado (≈ EE.UU.); se dividieron **÷4** para acercarlos a lo que el cliente colombiano efectivamente acepta. La tarifa blended pasó de ≈ $75.000/h a **≈ $18.750/h**. **Sin cambios:** horas por nivel, señales y niveles del catálogo, modificadores, y las zonas del semáforo ($12M/$20M), que miden disposición de pago absoluta y no se recalibran con la tarifa.
