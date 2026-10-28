# Cuestionario adaptativo

## Principio

Preguntar es preferible a inventar. Primero extrae lo que ya dijo el operador, luego pregunta solo por vacíos materiales. Usa rondas pequeñas y relacionadas; continúa hasta que el ledger esté completo.

Si el contexto nombra un sistema o repositorio disponible, inspecciónalo en lectura antes de preguntar por su estado, stack o capacidades existentes. La inspección descubre hechos técnicos, pero no decide preferencias comerciales.

## Ledger de decisiones

Antes de generar, debe quedar resuelto:

### Identidad y narrativa

- cliente, empresa y persona decisora;
- idioma y datos de contacto disponibles;
- sector, ubicación y público objetivo;
- situación actual y problema concreto;
- objetivo de negocio y resultado esperado;
- mensaje breve para el correo de envío que conecte el problema confirmado, la solución propuesta y ese resultado de negocio;
- diferenciadores reales que deban mencionarse;
- hechos, cifras o competidores aportados por el cliente;
- alcance y exclusiones explícitas.

Si falta un hecho que cambiaría la historia comercial, pregunta. No inventes métricas internas, clientes, volúmenes, competidores, integraciones ni casos de éxito.

El mensaje del correo puede derivarse de hechos ya confirmados; no abras una pregunta separada si problema, solución y resultado ya están claros. Si alguno falta, resuélvelo en el ledger antes de redactar. Debe ser texto plano, específico para ese cliente y sin HTML ni Markdown.

### Alcance y entrega

- funcionalidades, roles y flujos incluidos;
- qué ya existe y qué debe construirse;
- integraciones incluidas, excluidas o pendientes de credenciales;
- restricciones técnicas, legales, de seguridad o marca;
- cronograma o fecha objetivo;
- stack conocido. Si no existe una decisión, ofrece el stack estándar descrito por el prompt técnico y pide confirmación; no lo adoptes silenciosamente.

### Inversión

- moneda y nacionalidad;
- valor cotizado;
- si ese valor es inversión base o total final que ya incluye módulos con recargo;
- cuotas, porcentajes e hito de cada pago;
- impuestos, vigencia y descuento, cuando apliquen.

Si no hay precio, pregunta por el valor o propone `$requirement-calculator`. No continúes con `0` como supuesto.

Si hay módulos calculables y el operador da un total final, calcula la inversión base que permite que ProjectApp reconstruya ese total y muestra el cálculo antes de confirmarlo.

### Decisiones que se preguntan siempre

Aunque el brief parezca completo, confirma explícitamente:

1. **Hosting**: no se ofrece, términos estándar vigentes o términos personalizados.
2. **ROI**: se muestra o se oculta. Si se muestra, confirma los datos base del cliente que pueden usarse y qué no debe presentarse como promesa.
3. **Módulos adicionales**: ninguno o lista confirmada. Presenta como sugerencias los detectados en el brief; nunca los selecciones automáticamente.
4. **Módulos de valor agregado**: ninguno, subconjunto confirmado o todos los gratuitos aplicables.
5. **Condiciones comerciales**: mostrar u ocultar; si se muestran, confirmar si aparecen bolsas de horas.
6. **Detalle técnico**: visible al cliente o interno. En ambos casos se genera.

Cuando el hosting sea personalizado, pregunta porcentaje de referencia, descuentos por frecuencia, cobertura y meses gratuitos. Con términos estándar, lee los números vigentes y muéstralos en la confirmación.

Cuando el ROI se habilite, cualquier dato interno necesario para proyectar escenarios —tráfico, volumen de clientes, ticket, tiempo ahorrado o tasa de conversión— debe venir del operador o quedar identificado como supuesto aprobado. Las estadísticas externas se investigan después.

## Confirmaciones separadas

Hay dos hitos distintos:

1. Confirmación del ledger para generar y auditar los artefactos.
2. Autorización posterior al resumen para crear el borrador en la base indicada.

No conviertas la primera en permiso para ejecutar la segunda. En la confirmación final nombra el entorno, cliente, título y total efectivo.
