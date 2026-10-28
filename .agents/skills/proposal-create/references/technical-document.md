# Detalle técnico y trazabilidad

Lee completo `frontend/composables/useTechnicalPrompt.js` antes de generar. Su shape y sus reglas prevalecen sobre este resumen.

## Resultado esperado

`technicalDocument` se rellena siempre, incluso cuando `section_visibility.technical_document=false`. En ese caso queda disponible para revisión interna, pero no se muestra al cliente.

No inventes un stack, proveedor, integración, URL, capacidad, compliance ni infraestructura. Usa datos del repositorio cuando el proyecto exista; para decisiones no descubribles, pregunta. El stack estándar indicado por el prompt técnico solo se usa después de que el operador lo acepte.

## Correspondencia comercial

- Crea una épica por grupo comercial base visible y por módulo adicional seleccionado, en el mismo orden.
- `epicKey` replica literalmente el id comercial.
- Para módulos adicionales, usa `linked_module_ids: ["module-<id>"]` tanto en la épica como en sus requerimientos.
- Cada item comercial incluido debe aparecer en al menos un `linked_item_ids`.
- Los ids se copian literalmente desde `functionalRequirements`; nunca se reconstruyen de memoria.
- Los `flowKey` son únicos, kebab-case y describen el comportamiento, no una plantilla repetida.
- Los requerimientos deben variar con la complejidad real. Como control de profundidad, al menos 80% de los items debe enlazar dos o más requerimientos; los flujos transaccionales o integraciones normalmente requieren tres o más.
- Un requerimiento no transversal no debe agrupar más de tres items. Los transversales usan un `flowKey` que comienza por `cross-`.

## Contenido

Completa propósito, stack, arquitectura, modelo de datos, preparación para crecimiento, épicas, APIs, integraciones, entornos, seguridad, rendimiento, respaldos, calidad y decisiones.

- Separa integraciones incluidas de excluidas y aclara quién aporta cuentas o credenciales.
- Escribe títulos y descripciones comprensibles para un decisor no técnico; deja los detalles en configuración y flujo de uso.
- Declara alternativas y razones reales, sin arquitectura ornamental.
- Los objetivos de rendimiento y seguridad deben ser verificables y proporcionales al alcance.
- Si algo aún depende de una decisión externa, vuelve al cuestionario; no uses `TODO`, `TBD`, datos de ejemplo ni URLs inventadas.

## Control antes del auditor

Comprueba manualmente:

1. todas las claves de primer nivel de la plantilla siguen presentes;
2. no hay épicas de módulos no contratados;
3. no falta ningún item comercial incluido;
4. no existe ningún `linked_item_ids` desconocido;
5. `epicKey` y `flowKey` son válidos y únicos;
6. exclusiones y supuestos comerciales aparecen también en el detalle técnico cuando afectan alcance.
