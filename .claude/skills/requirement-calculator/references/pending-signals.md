# Señales pendientes — bandeja de candidatas

Cuando la calculadora clasifica una funcionalidad *"sin señal — por analogía"*, registra aquí la señal propuesta (append, nunca sobrescribir). Este archivo es la bandeja de entrada para la próxima versión del catálogo (`effort-indicators.md`); las señales se promueven manualmente tras revisión del dueño — el skill nunca modifica el catálogo directamente.

Formato de cada entrada:

`- <DDMMYYYY> · nivel sugerido: <XS|S|M|L|XL> · señal propuesta: "<texto>" · origen: "<funcionalidad del requerimiento>"`

---

- 02072026 · nivel sugerido: M · señal propuesta: "Texto sugerido automáticamente por el sistema a partir de datos ya registrados, editable por el usuario antes de persistir (observaciones, descripciones, respuestas precargadas)" · origen: "CD-06 Observación automática sugerida desde traslados + comentarios del usuario (Vástago Conteo Diario)" · **promovida al catálogo el 02072026**
- 02072026 · nivel sugerido: S · señal propuesta: "Retiro controlado de un comportamiento ya entregado — eliminar endpoint/acción + su UI + reescribir las pruebas que lo cubrían (≠ ocultar un elemento, que es XS; sube a M si exige decidir/archivar datos históricos)" · origen: "CD-11 Retirar la generación de ajustes del conteo actual (Vástago Conteo Diario)" · **promovida al catálogo el 02072026**
- 02072026 · nivel sugerido: M · señal propuesta: "Bloqueo/reserva exclusiva de un registro por usuario — al iniciar el trabajo el registro queda reservado a quien lo tomó y el segundo usuario recibe un mensaje de bloqueo (lock con select_for_update o equivalente; suele sumar el modificador Concurrencia/atomicidad; la liberación por timeout/vencimiento se cotiza con su tarea programada)" · origen: "ID-11 Bloqueo de concurrencia por Grupo+Bodega (Vástago Inventario Detallado)" · **promovida al catálogo el 02072026**
- 03082026 · nivel sugerido: L · señal propuesta: "Snapshot masivo del estado de un dominio como base de comparación (foto) + tablero de gestión por unidad de trabajo" · origen: "ID-03 Cargar Inventario / foto + tablero de Captura (corrida Fase 1.5 v5)"
- 03082026 · nivel sugerido: M · señal propuesta: "Comparación de captura contra snapshot con veredicto por registro (reporte de diferencias, sin ajuste)" · origen: "ID-06 Finalizar y comparar (corrida Fase 1.5 v5)"
- 03082026 · nivel sugerido: M · señal propuesta: "Pantalla de un documento del pipeline sobre componentes de documento existentes (grilla/formulario reutilizados)" · origen: "FA-REM-02 Pantallas de RM y SC (corrida Fase 1.5 v5)"
- 03082026 · nivel sugerido: S · señal propuesta: "Expiración/purga automática de registros por antigüedad, sin alerta ni UI (regla fija + tarea programada)" · origen: "FA-REM-04 Vencimiento del Borrador a 2 días (corrida Fase 1.5 v5)"
- 03082026 · nivel sugerido: M · señal propuesta: "Árbol de selección con casillas sobre catálogo fijo, reemplazando una tabla plana existente (no edita estructura)" · origen: "FA-PERM-02 Pantalla de Roles en árbol expandible (corrida Fase 1.5 v5)"
- 03082026 · nivel sugerido: S · señal propuesta: "Ocultar/mostrar por rol barrido sobre N roles/superficies con verificación multi-rol (elevación por composición desde XS)" · origen: "FA-USER-04 Retirar selector de sucursal (corrida Fase 1.5 v5)"
- 15082026 · nivel sugerido: S · señal propuesta: "Bloque visual ilustrativo estático a medida (scorecard, canvas, antes/después) — maquetación de un artefacto visual de marketing con datos fijos, sin interacción ni backend; el nivel es por unidad y sube a M cuando son 3 o más en un mismo paquete" · origen: "W-28 assets visuales de Xpandia (antes/después, Decision Context Canvas, mapa de 20 locales)"
