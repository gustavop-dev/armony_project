# Guías que el cliente puede ejecutar

Una etapa reúne comportamientos relacionados; cada caso explica una acción
observable, no una lista de archivos o una descripción genérica del módulo.

| Parte | Contenido |
| --- | --- |
| Contexto | Qué se probará, para qué sirve y dónde se realiza |
| Preparación | Cuenta/rol acreditado, datos previos y dependencias |
| Pasos | Una acción concreta por paso, usando nombres visibles de controles |
| Éxito | Resultado que la persona puede observar y comprobar |
| Problemas | Señales de fallo y datos útiles para describir lo ocurrido |
| Resultado | Conforme, con observaciones, rechazado o pendiente de ejecutar |

Usa los campos del esquema vigente: access/environment/preparation/data,
steps/expected_result/failure_signals y dependencies. Si existe un rol
acreditado, incluye casos permitidos y bloqueados con su resultado. No inventes
cuentas, permisos, pantallas o restricciones. Sin datos previos necesarios,
explícalo; no agregues preparación artificial.

El cliente valida casos concretos en un ambiente concreto. Una aprobación
parcial no cierra casos sin ejecutar. Objeción y rechazo requieren motivo;
la respuesta del equipo comunica atención y no equivale a nueva conformidad.
Una segunda ronda vuelve a abrir pendientes, conservando los casos aprobados.

## Referencia editorial comprobada localmente

Las guías del repo Vástago muestran preparación global, resumen de etapa,
propósito/preparación/pasos/éxito/problemas por caso y una tabla final de
resultados con observaciones:

- `docs/reports/Reporte_QA_Etapa_1_Cimientos_16082026.md`.
- `docs/reports/Reporte_QA_Etapa_2_Conteo_Diario_16082026.md`.

Se utilizaron como referencia de **formato**, no como contrato del proyecto al
que se aplicará esta skill. No copiar sus cuentas o contraseñas ni presentar
esta lectura local como consulta del correo o Gestor Documental.
Los documentos históricos 137/138/181 son pistas de búsqueda, no lecturas
vivas acreditadas. Cuando se requiera su contenido, recuperar las versiones
accesibles y las comunicaciones originales por lectura autorizada, y registrar
qué se consultó. Una fuente inaccesible permanece pendiente, sin inventar citas.
