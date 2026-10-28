# Catálogo de chequeos y reglas del motor (catálogo 1.1.0)

Cada fila cruza un chequeo del inventario U7 con la regla del motor que lo detecta.

**Columnas:**
- **Riesgo de corregir:**
  - BAJO: dato derivado, reversible e invisible para el cliente;
  - MEDIO: cambia copias o vistas, reversible con historial;
  - ALTO: dinero, documento emitido, privacidad, borrado o fusión;
  - SÓLO REPORTE: inmutable o evidencia.
- **Vía:** cómo se corrige. «motor» es `--apply`; «herramienta» es la herramienta
  existente que nombra el hallazgo; «a mano» es sólo informe.

**Las rutas** son relativas a `backend/`. Si una línea no coincide, manda el código.

**El inventario de relaciones** dice qué regla mira cada relación hacia proyectos,
clientes, propuestas, documentos, carpetas, hilos, ingresos y hostings, o por qué ninguna
la mira (exenta o hueco conocido). Vive en
`content/services/data_integrity/relation_inventory.py`; su resumen sale con
`manage.py audit_data_integrity --coverage`.

## Clientes

| Chequeo | Regla | Invariante | Riesgo · vía |
|---|---|---|---|
| CLI-01 huérfanos | CL4 v2 | Nada que impida borrar al usuario del cliente: las 6 relaciones de negocio más cada PROTECT (`accounts/services/client_deletion.py`) | ALTO · borrar a mano desde «Huérfanos»; la guarda rechaza con 400 lo que no se puede |
| CLI-02 «huérfanos» con otros registros | CL6 | Sin las 6 relaciones de negocio, pero con bloqueos o rastros SET_NULL (`client_merge_policy.discover_relations`) | SÓLO REPORTE |
| CLI-03 duplicados | CL1, CL2, CL3 | Mismo correo, nombre o empresa con un provisional, o misma cédula | ALTO · motor (fusión de a una) |
| CLI-04 FK de cliente a un admin | CL5, sólo para `Project` | `limit_choices_to={'role': 'client'}` no restringe en la base | Hueco fuera de `Project` |
| CLI-05 dueño de proyecto sin perfil | CL5 | `Project.client` con perfil de rol cliente | MEDIO · a mano |
| CLI-06 archivado con proyectos vivos | — | `archived_at` y proyectos activos | Hueco |
| CLI-07 copias de cliente desfasadas | PR1, sólo propuestas | `accounts/services/proposal_client_service.py` (`sync_snapshot`) | MEDIO · motor |

## Proyectos

| Chequeo | Regla | Invariante | Riesgo · vía |
|---|---|---|---|
| PRY-01 cruce de cliente | AC1, CM1, DC1, DC3, CM5, PR3 y **PJ8** | El proyecto del registro es de su mismo cliente | ALTO · motor donde existe; PJ8 a mano |
| PRY-02 estado distinto | PJ6 | `status` igual a `current_state.system_key` | MEDIO · motor |
| PRY-03/04 sin raíz | PJ5 | Raíz documental y de conversación | BAJO · comandos con plan |
| PRY-05 orden de fases | PJ7 | Fases numeradas de 1 a n | BAJO · motor |
| PRY-06 propuesta, entregable y fases | PR3 | Coinciden | MEDIO · herramienta |
| PRY-07 registros sin proyecto | PJ1, PJ3 | `panel_projects._unlinked_qs` | BAJO-MEDIO · motor o herramienta |
| PRY-08 conservados | PJ2 y **PJ9** | PJ2: un conservado no apunta a un proyecto. PJ9: el índice del borrado lo lista (`content/services/retention_audit.py`, `unlisted`) | ALTO · a mano |
| PRY-09 contenedores vacíos | PJ3 | `retained_containers.preview_discard` | BAJO · herramienta |
| PRY-10 archivos ausentes | — | Archivos contra almacenamiento | Hueco · SÓLO REPORTE |

## Entregas y contratos

| Chequeo | Regla | Invariante | Riesgo · vía |
|---|---|---|---|
| ENT-01 otrosí de otro contrato | — | `amendment.contract == contract` | Hueco · SÓLO REPORTE |
| ENT-02 vínculo de documento sin nivel o con varios | — | `DeliveryDocumentLink` sin restricción de esquema (H5) | Hueco |
| ENT-03 aviso, evidencia o contexto de otro cliente | **PJ8** | El cliente del registro es el del proyecto | SÓLO REPORTE (inmutables) |
| ENT-04 reportes con 0 o 2 padres | — | `accounts/models_issue_reports.py` | Hueco |

## Documentos

| Chequeo | Regla | Invariante | Riesgo · vía |
|---|---|---|---|
| DOC-01 activos bajo archivados | DC6 | Archivar es en cascada | BAJO · herramienta |
| DOC-02 documento y carpeta de distinto cliente | **DC9** | La carpeta organiza y no es dueña (`content/serializers/document.py`, `_inherit_from_folder`) | BAJO · a mano: puede ser intencional |
| DOC-12 documento y carpeta de distinto proyecto | **DC10** | Ídem | BAJO · a mano |
| DOC-03 sin carpeta | **DC11** | Aparece en «Sin carpeta». Los borradores de cuenta de cobro se excluyen: se archivan solos al emitirse o anularse (`generated_document_filing_service.file_collection_account`) | BAJO · a mano |
| DOC-04 dos cuentas vigentes por ingreso | **AC9** | A lo sumo una cuenta no anulada por ingreso (`content/services/collection_account_create_service.py`) | ALTO · anular por su flujo |
| DOC-05 cuenta de otro proyecto o cliente que su ingreso | **AC10** | La liquidación busca la cuenta por el proyecto y el cliente exactos (`content/services/income_settlement_policy.py`). Una cuenta a la que sólo le falta el proyecto del ingreso es de PJ1 | ALTO · borrador: editar; emitida: anular y regenerar |
| DOC-06 número público repetido | **DC12** | Único entre cuentas de cobro (`content/services/collection_account_numbering.py`) | SÓLO REPORTE |
| DOC-07 a DOC-11 | — | Totales, estados, archivos, episodios, plantillas | Huecos |

## Comunicaciones

| Chequeo | Regla | Invariante | Riesgo · vía |
|---|---|---|---|
| COM-01 hilo o carpeta de otro cliente | CM1, CM2 | `content/models/communication.py` (`clean`) | ALTO · motor |
| COM-02 adjunto de otro cliente | **CM6** | `communication_service._validate_documents` | ALTO · SÓLO REPORTE (el mensaje enviado no se reescribe) |
| COM-03 hilos sin mensajes | CM4 (parcial) | — | BAJO · motor |
| COM-04, COM-05 | — | Dirección, estado y ciclos | Huecos |
| COM-06 enlace seguro de otro cliente | CM5 | El cliente del enlace es el del proyecto | ALTO · a mano |

## Contabilidad

| Chequeo | Regla | Invariante | Riesgo · vía |
|---|---|---|---|
| CON-01 reparto entre socios | **AC11** | `content/models/accounting_base.py` (`PartnerSplitMixin.clean`) | MEDIO · editar en Contabilidad |
| CON-02 esperado sobrepagado | **AC12** | `content/services/accounting_settlement_service.py` (`_paid_total`) | ALTO · a mano (liquidación o residuo) |
| CON-03 líquido, esperado y bolsillo | AC2 (parcial) | — | MEDIO |
| CON-04 espejo del bolsillo | **AC13** | `accounting_service._sync_movement`: un ingreso es IN, un gasto es OUT y el monto es el del registro | MEDIO · a mano |
| CON-05, CON-08 | — | Ventanas de hosting y extractos | Huecos |
| CON-06 esperados duplicados | AC3, AC4 | — | ALTO · decide el operador |
| CON-07 totales de hosting | AC5 | La suma de los ciclos | BAJO · motor |
| CON-09 | — | No son errores | — |
| CON-10 `object_id` sin fila viva | — | **Por diseño**: el rastro sobrevive al borrado | Nunca |

## Propuestas

| Chequeo | Regla | Invariante | Riesgo · vía |
|---|---|---|---|
| PRO-01 aceptada sin proyecto | PR4 | Fase o entregable | MEDIO · a mano o herramienta |
| PRO-03 precio histórico incompleto | **PR9** | `BusinessProposal.save` indexa `total_investment`, `discount_percent` y `currency`; `discount_original_for_proposal` indexa `original_investment` sólo con descuento. Sólo la migración 0275 las escribe | SÓLO REPORTE |
| PRO-04 sin cliente | PR2 | — | MEDIO · a mano |
| PRO-07 orden de secciones | PR7 (parcial) | — | BAJO · motor |
| PRO-02, PRO-05, PRO-06 | — | Inversión, estados y aprobación | Huecos |

## Reglas del motor sin chequeo en el inventario U7

PJ4 (proyectos con nombre repetido), DC4 (carpetas hermanas repetidas), DC8 (hilos
documentales), CM3 (carpetas de comunicaciones repetidas), AC8 (cuenta sin contexto de
facturación), PR5 (propuesta ligada a un proyecto borrado), PR8 (propuestas repetidas)
y NM1 (espacios en nombres).
