# Estimate: Vástago Funcionalidades Adicionales Fase 1.5 — 02072026

> **ProjectApp · Calculadora de Requerimientos** — estimación por funcionalidad para implementación web, precios en COP sin IVA.

## 1. Resumen

Estimación del **resto del alcance de la Fase 1.5** de Vástago (TORRIOS SAS): 11 requerimientos adicionales (bitácora de auditoría, tipos de precio, documento de Remisión/consignación, editor de formatos de etiqueta, matriz de permisos en árbol, motor de correo con marca, Datos de la Empresa + motor de PDF, creación de maestros al vuelo, registro de usuarios y ajustes menores), descompuestos en 27 funcionalidades según el backlog FA-* del reporte.

**Decisión de agrupación:** aunque el reporte trae varios requerimientos, **todos pertenecen al mismo proyecto/propuesta** (Fase 1.5) y tienen dependencias cruzadas — FA-PERM, FA-MAIL, FA-EMP y FA-PRICE son cimientos del resto y de las épicas ya estimadas (#23 Conteo Diario, #24 Inventario Detallado) —, por lo que se consolidan en **un solo documento** con un único total y semáforo.

## 2. Descomposición por funcionalidad

**Históricos / Logs (§5.1)**

| Funcionalidad | Nivel | Señal aplicada (cita literal) | Modificadores | Horas | Precio COP |
|---|---|---|---|---|---|
| FA-LOG-01+02 Bitácora de auditoría: motor (autor + soft-delete 6 meses en todos los modelos) + pantalla de consulta con filtros | L | «Trazabilidad de historial / auditoría / bitácora de eventos — construir el registro de quién hizo qué y cuándo … con su vista de consulta» | Transversal ×1,4 (todos los maestros y documentos) · Tests exigidos +15% | 89–145 | $1,5M–$2,4M |
| FA-LOG-03 Exportar la bitácora por rango de fechas | M | «Generación de reportes / archivos … incluye exportación simple desde una vista existente» | Tests +15% | 16–23 | $260K–$400K |
| FA-LOG-04 Alerta al SuperAdmin por Modificar/Eliminar | M | «Notificaciones por evento (in-app o correo) — detectar el evento, plantilla, envío» | Tests +15% · Motor de correo anulado (lo aporta FA-MAIL-01) | 16–23 | $260K–$400K |

**Maestro de Moneda / tipos de precio (§5.2)**

| Funcionalidad | Nivel | Señal aplicada (cita literal) | Modificadores | Horas | Precio COP |
|---|---|---|---|---|---|
| FA-PRICE-01 Dimensión "tipo de precio" (PVP/PVM/USD) en el Ítem | M | Familia espejo *Precios / descuentos*: «lista de precios por cliente / parametrizar regla fija» (atenuador: el modelo de precios ya existe) | Modelo de datos +10% · Tests +15% | 23–33 | $400K–$530K |
| FA-PRICE-02 Reporte del maestro de precios | M | «Generación de reportes / archivos (Excel, PDF) — desde básicos hasta parametrizables» | Pantalla nueva +15% · Tests +10% | 18–25 | $310K–$400K |

**Documento de Remisión / consignación (§5.3)**

| Funcionalidad | Nivel | Señal aplicada (cita literal) | Modificadores | Horas | Precio COP |
|---|---|---|---|---|---|
| FA-REM-01 Documentos RM y SC: tipos, numeración, movimientos (backend de ambos) | M | «Pipeline de documentos comerciales — … Cada documento suelto es `M`» (2 documentos sobre el motor existente) | Tests +15% (reutiliza `Document`/`MovementService`) | 25–35 | $400K–$570K |
| FA-REM-02 Pantallas de RM y SC + Lista de Documentos (frontend de ambos) | M | Misma familia — mitad frontend de los dos documentos (atenuador: reutiliza `DocumentForm`/grilla existentes) | Tests +15% | 23–32 | $400K–$530K |
| FA-REM-03 Reporte de consignación + filtro tipo de mercancía en Radar/Dashboard | M | «Generación de reportes / archivos — desde básicos hasta parametrizables» | Tests +15% | 23–32 | $400K–$530K |
| FA-REM-04 Vencimiento del Borrador a 2 días (todos los documentos) | M | «Vencimientos / renovaciones con alertas — fechas de expiración … (suma *Tarea programada*)» | Tarea programada (Huey) +8–16 h · Tests +15% | 17–28 | $260K–$480K |

**Formatos de etiqueta (§5.4)**

| Funcionalidad | Nivel | Señal aplicada (cita literal) | Modificadores | Horas | Precio COP |
|---|---|---|---|---|---|
| FA-LBL-01 Renombrar "Descripción" → "Observaciones" en el Ítem | XS | «Cambio de copy — texto, etiqueta, título…» | Tests +10% | 3–6 | $60K–$100K |
| FA-LBL-02 Modelo de formato ampliado (tipografía, campos visibles, 4 dimensiones, predeterminado) | M | «Configurar / parametrizar una regla de negocio antes fija en el código» (el motor de formatos ya existe) | Modelo de datos +10% · Tests +15% | 20–30 | $350K–$480K |
| FA-LBL-03 Pantalla de autogestión de formatos (diseño fijo, check de campos, 5 tipografías, previsualización) | M | «Panel de configuración / parametrización del sistema — … administrables desde la UI» (`L`) **con atenuador** *extiende algo existente* (el motor de formatos ya guarda formatos) → `M` | Pantalla nueva +20% · Tests +15% | 41–57 | $660K–$970K |
| FA-LBL-04 Motor de impresión ampliado (tipografías, mostrar/ocultar campos, PVP opcional, Code128 sobre código alterno) | M | «Documento o correo con maquetación / branding — membretes, tipografías, identidad corporativa» | Tests +15% (el render de etiquetas existe, se amplía) | 28–39 | $480K–$660K |

**Matriz de permisos en árbol (§5.6)**

| Funcionalidad | Nivel | Señal aplicada (cita literal) | Modificadores | Horas | Precio COP |
|---|---|---|---|---|---|
| FA-PERM-01 Matriz jerárquica módulo/submódulo + cascada + módulos gestionados → editables | M | «Panel de administración de usuarios y roles (RBAC granular)» (`L`) **con atenuador** (el panel plano L/E/E ya existe) → `M` | Permisos granulares sobre lo existente +30% · Transversal ×1,4 · Tests +15% | 49–69 | $790K–$1,1M |
| FA-PERM-02 Pantalla de Roles en árbol expandible | M | «Visualización interactiva compleja a medida — … árbol jerárquico editable» (`L`) **con atenuador** (la pantalla de Roles existe) → `M` | Tests +15% | 28–39 | $480K–$660K |
| FA-PERM-03 Menú y botones sensibles a submódulo + renombre "Inventario Detallado" | M | «Permisos / visibilidad por rol — … mostrar u ocultar contenido según rol» | Transversal ×1,4 (toca todas las pantallas) · Tests +15% | 26–35 | $440K–$570K |

**Correo con identidad de marca (§5.7)**

| Funcionalidad | Nivel | Señal aplicada (cita literal) | Modificadores | Horas | Precio COP |
|---|---|---|---|---|---|
| FA-MAIL-01 Motor de correo con plantillas de marca Vástago + registro de envíos | M | Familia espejo *Correo*: «con branding / por evento / plantilla fija» | Motor nuevo (plantillas de correo) +40% · Tests +15% | 31–43 | $530K–$700K |
| FA-MAIL-02 Destinatarios híbridos por evento + pantalla de configuración + enganche de los 3 eventos | M | «Configurar / parametrizar una regla de negocio antes fija en el código — UI para administrarla» | Pantalla nueva +15% · Tests +15% | 29–39 | $480K–$660K |

**Datos de la Empresa (§5.8)**

| Funcionalidad | Nivel | Señal aplicada (cita literal) | Modificadores | Horas | Precio COP |
|---|---|---|---|---|---|
| FA-EMP-01 Datos de la Empresa (logo/NIT/razón social, singleton) + motor de PDF de reportes | M | «Documento o correo con maquetación / branding — membretes … identidad corporativa» | Motor nuevo (PDF de reportes) +50% · Pantalla nueva +15% · Tests +15% | 36–50 | $620K–$840K |

**Creación de maestros al vuelo (§5.9)**

| Funcionalidad | Nivel | Señal aplicada (cita literal) | Modificadores | Horas | Precio COP |
|---|---|---|---|---|---|
| FA-INLINE-01 Componente genérico "crear al vuelo" (modal, inyección, permisos, errores) | M | «Generalizar una operación (crear/editar/eliminar) del caso base a N casos o modelos» | Tests +15% | 28–39 | $480K–$660K |
| FA-INLINE-02 Mini-formularios por maestro (7) + botón "+" en los formularios anfitriones | M | Misma señal — es la parte "a N casos" de la generalización (validaciones por maestro se reutilizan) | Tests +15% | 35–48 | $570K–$790K |

**Registro y administración de usuarios (§5.10 / §6.2)**

| Funcionalidad | Nivel | Señal aplicada (cita literal) | Modificadores | Horas | Precio COP |
|---|---|---|---|---|---|
| FA-USER-01 Sucursal única (sede) + visibilidad por rol (accesibles derivadas) | M | «Permisos / visibilidad por rol» (atenuador: `accessible_branches` ya existe, cambia la regla) | Pruebas multi-rol +15% · Tests +15% | 23–34 | $400K–$570K |
| FA-USER-02 Formulario de creación/edición de usuarios (solo SuperAdmin) | M | «Autenticación … Piezas sueltas sobre auth existente … son `M`» | Pantalla nueva +20% · Tests +15% | 30–41 | $480K–$660K |
| FA-USER-03 Cambio forzado de contraseña en el primer ingreso | M | «… recuperación de contraseña sobre una autenticación que ya existe» (pieza sobre auth existente) | Tests +15% | 16–23 | $260K–$400K |
| FA-USER-04 Retirar selector de sucursal (rol Usuario) + rol en el encabezado | S | Composición de dos XS: «Ocultar / mostrar un elemento existente (por rol o condición simple)» + cambio visual | Tests +15% | 8–14 | $130K–$220K |

**Ajustes menores (§6.1 / §6.2)**

| Funcionalidad | Nivel | Señal aplicada (cita literal) | Modificadores | Horas | Precio COP |
|---|---|---|---|---|---|
| FA-MISC-01 Renombrar "Monto" → "Precio de Venta" | XS | «Cambio de copy — texto, etiqueta, título…» | — | 3–4 | $60K–$70K |
| FA-MISC-02 Acceso a Trazabilidad en el menú + submenús desplegables por perfil | S | «Tabs / acordeón / secciones colapsables — reorganizar una vista existente» (la pantalla de trazabilidad ya existe) | Tests +15% | 12–18 | $220K–$310K |

**Implicaciones técnicas (resumen por bloque):**

- **Logs:** modelo `AuditLog` + campos `created_by/updated_by/deleted_by` en todos los modelos auditados + conversión a soft-delete + tarea Huey de purga a 6 meses + pantalla con filtros/export. Es, junto con permisos, lo más transversal del paquete.
- **Precios:** campo `price_type` con nueva constraint (item, tipo, moneda, fecha) — sin migración de datos (staging).
- **Remisión:** 2 `DocumentType` nuevos (RM/SC) reutilizando el motor de documentos y movimientos; regla transversal de Borrador a 2 días (tarea Huey).
- **Etiquetas:** el motor de formatos se amplía (no se recrea); el editor con previsualización e integración de 5 fuentes es lo más grande del bloque; Code128 pasa de EAN a código alterno (depende de ID-01, #24).
- **Permisos:** catálogo de módulos/submódulos + cascada en la permission class + árbol en la pantalla de Roles + gating de menú/botones en toda la app.
- **Correo:** `EmailTemplate`/`EmailLog`/`EmailRecipient` + render de marca sobre el SMTP existente; los 3 eventos (CD-10, ID-13, FA-LOG-04) se enganchan aquí.
- **Empresa:** `CompanyProfile` singleton + motor de PDF de reportes (hoy solo hay PDF de etiquetas) — cimiento de CD-08/CD-09 (#23).
- **Inline:** componente genérico sobre `ModalPortal` + 7 mini-formularios que reutilizan los CRUD y validaciones existentes.
- **Usuarios:** regla de sede única con visibilidad por rol, CRUD de usuarios en la app, flag `must_change_password`, retiro del selector de sucursal para el rol Usuario.

## 3. Totales

- **Horas:** 696–1004 h
- **Precio total:** $11,7M–$16,6M
- **Semáforo:** ⚠️ Fricción ($12M–$20M)

> [!WARNING]
> El total cae en la banda de fricción: es viable como propuesta única, pero conviene ofrecer las **dos fases** de la sección 5 para bajar el ticket inicial. Los cimientos van primero porque las épicas #23 y #24 dependen de ellos.

## 4. Observaciones

- **Por qué un solo documento:** los 11 requerimientos pertenecen a la misma propuesta (Fase 1.5) y comparten cimientos (FA-PERM, FA-MAIL, FA-EMP, FA-PRICE habilitan al resto y a las épicas #23/#24). No son requerimientos independientes de clientes o contextos distintos; el semáforo se calcula sobre la suma consolidada.
- **Anti-doble-cobro con #23 y #24:** los motores que las épicas "anularon" (correo con marca, PDF de reportes + Datos de Empresa, matriz de permisos, sucursal única) **se cotizan aquí una sola vez** — FA-MAIL, FA-EMP-01, FA-PERM y FA-USER-01. CD-08/09/10 (#23) e ID-13 (#24) los consumen sin recotizarlos.
- **Transversales advertidos:** la bitácora (FA-LOG) y la matriz de permisos (FA-PERM) escalan con el número de pantallas/modelos donde se integran — «construir una vez, reutilizar N veces»; su multiplicador ×1,4 refleja el punto de integración actual, y crecerá si el sistema suma módulos.
- **Dimensión completa de la Fase 1.5 (informativo):** sumando las tres estimaciones del proyecto — #23 ($5,4M–$7,7M) + #24 ($6,4M–$9,0M) + esta ($11,7M–$16,6M) — la fase completa ronda **$23,4M–$33,3M / ~1.400–2.000 h**. Esto exige un plan por fases con hitos de facturación (cada épica y cada fase de este documento caben individualmente fuera de la zona killer).
- **Excluidos (diferidos, sin filas):** galería/vista 360 (fase E-commerce), maestro de Clientes + "Precio de Venta a facturar" y documentos FV/DV/AT (fase Facturación), consecutivo de numeración al migrar (§9-C, órbita Facturación), posicionamiento libre de campos de etiqueta (Nivel A/B, descartado el 27-jun), logo/marca de agua en etiquetas.
- **Adyacencias que se abren:** editor visual de etiquetas (Nivel A/B) · plantillas de correo editables por cliente · más eventos de correo · datos de empresa por sucursal · alertas de bitácora configurables · e-commerce (galería 360).

## 5. Estrategia comercial

Total en banda de fricción: viable en una sola propuesta, pero se recomienda ofrecer **dos fases** (Estrategia A), cada una desplegable y útil sola:

| Fase | Alcance | Horas | Precio COP |
|---|---|---|---|
| **F1 — Cimientos** | FA-PERM-01/02/03, FA-MAIL-01/02, FA-EMP-01, FA-PRICE-01/02 (matriz de permisos en árbol, correo de marca, Datos de Empresa + motor PDF, tipos de precio). Desbloquea CD-08/09/10 (#23) e ID-13 (#24) | 240–333 | $4,1M–$5,5M |
| **F2 — Operación y productividad** | FA-LOG (bitácora + export + alertas), FA-REM (RM/SC + Borrador 2 días), FA-LBL (etiquetas), FA-USER (registro de usuarios), FA-INLINE y FA-MISC | 456–671 | $7,7M–$11,2M |

F1 va primero obligatoriamente (cimientos de las épicas #23/#24 ya cotizadas). Dentro de F2 el orden interno es libre; si se quiere bajar su ticket, los bloques FA-INLINE+FA-MISC (~$970K–$1,5M) son los más fáciles de diferir.

## 6. Supuestos y exclusiones

- Precios en COP sin IVA · tarifa blended ≈ $16.500/h (recalibración 18/08/2026) · implementación **web** (sin PWA/nativa declaradas).
- **Recalibración 18/08/2026 (+10%, market-pricing v1.7):** columnas de precio, totales y tablas de fases reescalados ×1,10 por directriz del dueño; horas, niveles, señales y modificadores sin cambios, y el semáforo no cambia de zona.
- **Reemplaza la estimación #25 del 02/07/2026; cambio respecto a la versión previa:** recalibración de precios al mercado colombiano (**÷4**, ajusta el ÷3,5 provisional). Horas, niveles, señales, modificadores y agrupación sin cambios.
- **Recalibración 04/08/2026 (−20%, market-pricing v1.6):** columnas de precio y totales reescalados ×0,8 por directriz del dueño; horas, niveles, señales y modificadores sin cambios.
- **Plataforma existente (Fase 1.5):** atenuadores aplicados donde la base existe (motor de documentos, motor de formatos de etiqueta, panel de Roles plano, auth, manejo de imágenes, SMTP, tareas Huey). Los dos "motores nuevos" reales (correo con plantillas, PDF de reportes) llevan su modificador *Motor nuevo* aquí, una sola vez.
- **Exigencia de calidad:** cobertura pytest + Jest + Playwright enumerada ticket a ticket en el reporte → modificador *Tests exigidos* (+10–15%) en casi todas las filas.
- **Medidas de las 4 dimensiones de etiqueta** (única pregunta abierta del reporte): pendientes del cliente; bloquean el cierre de FA-LBL-02/03 (cronograma). Se asume que las 4 dimensiones no cambian el esfuerzo (solo son valores del catálogo).
- **Registro de usuarios:** el alcance base está definido; la reunión pendiente afina detalles finos (incluido el renombre del rol "Usuario" → "Gestor", cotizado como parte de FA-USER, es un cambio de etiqueta).
- **Bitácora:** 6 meses de retención, acciones Crear/Modificar/Eliminar, regla fija — cotizada como fija; volverla configurable sería alcance nuevo.
- Diferidos sin cotizar: galería/360, maestro de Clientes y "Precio de Venta a facturar", FV/DV/AT, consecutivos de migración, posicionamiento libre de etiquetas, logo/marca de agua.
- No incluye infraestructura recurrente ni licencias (p. ej. licencias de fuentes tipográficas, si las 5 elegidas lo requirieran — verificar licenciamiento de Helvetica/Futura/Bodoni/Garamond; Bebas Neue es libre).
- Estimación sujeta a refinamiento tras análisis detallado.

> [!IMPORTANT]
> No cerrar precio fijo del **bloque de etiquetas (F6)** hasta recibir las medidas de las 4 dimensiones, ni del **bloque de usuarios (F3)** hasta la reunión de detalle pendiente. Verificar además el **licenciamiento de las tipografías** comerciales antes de comprometer las 5 fuentes.

---

**Requerimiento original:** «Vástago — Funcionalidades adicionales solicitadas · Reporte de alcance versión 3 — Fase 1.5 (cierre), TORRIOS SAS, 26/06/2026: 11 requerimientos — Históricos/Logs (bitácora transversal 6 meses + export + alertas), tipos de precio PVP/PVM/USD + reporte, documento de Remisión RM/SC con Borrador a 2 días transversal, formatos de etiqueta autogestionables (diseño fijo, 4 dimensiones, 5 tipografías, Code128 sobre código alterno), galería/360 (aplazada), matriz de permisos en árbol con cascada, correo con identidad de marca Vástago (3 eventos, destinatarios híbridos), Datos de la Empresa (logo/NIT/razón social) para PDF/reportes, botón "+" de creación de maestros al vuelo, registro y administración de usuarios (sede única + visibilidad por rol + contraseña forzada) y ajustes menores; backlog FA-* de 27 tickets con roadmap de cimientos.»

— *ProjectApp · Calculadora de Requerimientos*
