---
name: proposal-create
description: "Crea una nueva propuesta comercial de ProjectApp mediante preguntas adaptativas, JSON importable, detalle técnico trazable y creación opcional de un borrador seguro. Usar cuando el operador invoque /proposal-create o $proposal-create con el contexto de una propuesta nueva; no usar para editar propuestas existentes."
allowed-tools: Bash, Read, Write, WebSearch, WebFetch, AskUserQuestion
---

# Proposal Create

Crea propuestas nuevas sin convertir un brief incompleto en hechos inventados. El resultado normal es:

1. decisiones comerciales confirmadas;
2. mensaje personalizado que explica qué resuelve la propuesta para el cliente;
3. JSON importable en ProjectApp;
4. manifiesto de decisiones no representadas completamente por el JSON;
5. auditoría mecánica aprobada;
6. si el operador lo autoriza después de revisar el resumen, un borrador sin enviar.

Esta skill es de invocación explícita. Nunca actualiza propuestas existentes, envía correos ni cambia el estado a `sent`.

## Recursos y carga progresiva

- Lee siempre [references/source-of-truth.md](references/source-of-truth.md) antes de obtener la plantilla.
- Lee siempre [references/questionnaire.md](references/questionnaire.md) antes de formular preguntas.
- Lee [references/commercial-json.md](references/commercial-json.md) al construir el JSON y el manifiesto.
- Lee [references/technical-document.md](references/technical-document.md) antes de rellenar `technicalDocument`.
- Lee [references/draft-creation.md](references/draft-creation.md) únicamente si se va a auditar o crear el borrador.

No copies dentro de esta skill los prompts completos del producto. Deben leerse desde sus fuentes canónicas para evitar que el flujo se quede congelado en reglas antiguas.

## Flujo obligatorio

### 1. Aterrizar el contexto y la plantilla

1. Ubica la raíz de ProjectApp y confirma el entorno que contiene las propuestas reales.
2. Obtén la fecha del sistema; nunca la supongas.
3. Extrae del mensaje todos los hechos ya informados y regístralos en un ledger de decisiones.
4. Si el brief nombra un proyecto o repositorio disponible, inspecciónalo en modo lectura antes de preguntar por capacidades, stack o estado actual que puedan descubrirse allí.
5. Exporta la plantilla activa con el comando de `references/draft-creation.md`. Debe provenir de `ProposalService.get_default_sections()`, no de constantes copiadas en esta skill.
6. Lee el `_seller_prompt` vigente y los prompts comercial/técnico indicados en `references/source-of-truth.md`.

Si no se puede leer la plantilla activa, detente: no generes un JSON basándote únicamente en memoria o en la skill histórica.

### 2. Preguntar hasta cerrar decisiones

Usa el cuestionario adaptativo. No repitas lo que el operador ya explicó y no limites artificialmente el número de rondas.

- Pregunta primero lo que cambia alcance, precio o narrativa.
- Presenta opciones concretas cuando existan decisiones discretas, pero permite una respuesta libre cuando se necesite contexto.
- Si falta el precio, pide el valor o propone calcularlo con `$requirement-calculator`; nunca uses cero silenciosamente.
- Si una respuesta abre otra decisión material, pregunta de nuevo.
- Resume el ledger y corrige cualquier contradicción antes de escribir el artefacto.

No sustituyas preguntas por supuestos sobre hosting, ROI, módulos, regalos, condiciones comerciales, pagos, stack, integraciones o hechos del negocio.

### 3. Generar el JSON y el manifiesto

Trabaja a partir de la plantilla exportada, preservando sus secciones, claves, tipos, grupos y módulos en el orden vigente.

- Guarda el JSON en `proposal-artifacts/<slug>_<dd_mm_yyyy>.json`.
- Guarda el manifiesto en `proposal-artifacts/<slug>_<dd_mm_yyyy>.manifest.json`.
- El JSON contiene la propuesta visible/importable.
- `_meta.optional_metadata.email_intro` contiene un mensaje específico en texto plano que conecta problema, solución y resultado de negocio; nunca lo dejes como copy genérico.
- El manifiesto contiene metadata operativa y decisiones explícitas: entorno, precio base/total cotizado, pagos, hosting, visibilidad, ROI y módulos.
- Mantén `functionalRequirements` y `technicalDocument` enlazados mediante IDs estables.
- Genera siempre el detalle técnico. Si será interno, deshabilita su sección en el manifiesto, pero no lo dejes vacío.
- Marca todos los módulos adicionales no confirmados con `selected=false` y `default_selected=false`, incluso si la plantilla activa los trae seleccionados.

Si el ROI está habilitado, busca y abre fuentes actuales y verificables. Prioriza fuentes primarias colombianas o latinoamericanas; guarda las URLs y la fecha de consulta en el manifiesto. No cites una cifra que la página abierta no respalde.

### 4. Auditar y presentar para aprobación

Ejecuta el auditor siguiendo `references/draft-creation.md`. Un `AUDIT_FAIL` obliga a corregir y repetir; nunca presentes el trabajo como terminado con fallos.

Cuando obtengas `AUDIT_PASS`, presenta un resumen que permita aprobar sin leer todo el JSON:

- cliente, objetivo y alcance;
- mensaje personalizado del correo de envío;
- inversión base, módulos con recargo y total efectivo;
- cuotas y hitos;
- hosting;
- ROI y fuentes, o exclusión del ROI;
- módulos adicionales y módulos de valor agregado;
- secciones ocultas, incluido el detalle técnico interno;
- ruta de ambos artefactos y advertencias del auditor.

Pregunta de forma explícita si se autoriza crear el borrador en el entorno indicado. La aprobación del brief o del JSON no equivale a autorización para escribir en la base de datos.

### 5. Crear un borrador, solo con autorización

Primero ejecuta el creador sin `--apply`. Si reporta un posible duplicado, muéstralo y solicita una decisión; no uses `--allow-duplicate` por iniciativa propia.

Después de una aprobación explícita posterior al resumen, ejecuta el comando mutante con la confirmación literal. El creador debe:

- usar `ProposalFromJSONSerializer` y `build_proposal_from_json`;
- operar dentro de una transacción;
- conservar `status=draft`;
- dejar `automations_paused=true`;
- persistir una selección de módulos confirmada, incluso si está vacía;
- aplicar hosting y visibilidad desde el manifiesto;
- verificar el total efectivo y el estado final;
- verificar que el mensaje personalizado se persistió exactamente;
- devolver únicamente la URL administrativa, sin abrir la URL pública.

Si la creación falla, conserva los artefactos, reporta el error y no intentes rutas de escritura alternativas.

## Condiciones de salida

Una ejecución queda completa como artefacto cuando existen JSON, manifiesto, un `email_intro` específico y `AUDIT_PASS`. Solo queda completa como borrador cuando, además, la verificación confirma `draft`, automatizaciones pausadas, selección exacta de módulos, mensaje persistido y total efectivo correcto.

Indica siempre si el resultado fue `artefacto auditado` o `borrador creado`. Nunca digas que la propuesta fue enviada.
