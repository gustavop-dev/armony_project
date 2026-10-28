# Fuentes de verdad

## Precedencia

Cuando dos fuentes difieran, aplica este orden:

1. Decisiones que el operador confirmó para esta propuesta.
2. Plantilla y configuración activas obtenidas desde la base de datos del entorno elegido.
3. `_seller_prompt` incluido por `get_proposal_json_template`.
4. Prompt comercial y prompt técnico del frontend.
5. Reglas de esta skill.

El JSON activo manda sobre cantidades o defaults congelados en documentación. Las respuestas del operador mandan sobre opciones comerciales como mostrar ROI, ofrecer hosting o regalar módulos, siempre que el shape siga siendo válido.

## Superficies canónicas

Lee estas fuentes desde la raíz actual de ProjectApp:

- `backend/content/views/proposal.py`:
  - `get_proposal_json_template` y su `_seller_prompt`.
  - transformación de importación y exportación JSON.
- `frontend/composables/useSellerPrompt.js`: reglas de narrativa comercial y límites visuales de cada sección.
- `frontend/composables/useTechnicalPrompt.js`: contrato completo de `technicalDocument` y trazabilidad.
- `backend/content/serializers/proposal.py`:
  - `SECTION_KEY_MAP`;
  - `ProposalFromJSONSerializer`.
- `backend/content/services/proposal_service.py`:
  - `ProposalService.get_default_sections`;
  - `build_proposal_from_json`.
- `backend/content/services/proposal_totals_service.py`: inversión base, módulos calculables y total efectivo.

No copies estos prompts a un reference. Léelos cuando se ejecuta la skill para heredar cambios futuros.

## Hechos que deben descubrirse en cada ejecución

- número y orden de secciones;
- grupos base y módulos adicionales;
- módulos que lleguen seleccionados por defecto;
- porcentajes de módulos calculables;
- porcentaje y descuentos vigentes de hosting;
- moneda, nacionalidad, vigencia y recordatorios predeterminados;
- schemas de contenido de cada sección.

Obtén estos datos con la exportación activa descrita en `draft-creation.md`. No uses `get_hardcoded_defaults()` cuando exista acceso al entorno real: omitiría personalizaciones administrables.

## Contratos invariantes

- `content_json` se entrega directamente como props de componentes Vue: preservar claves y tipos es obligatorio.
- El import oficial pasa por `ProposalFromJSONSerializer` y `build_proposal_from_json`.
- El mensaje personalizado vive en `BusinessProposal.email_intro`, viaja como `_meta.optional_metadata.email_intro` en el artefacto y como `email_intro` en el payload. Puede guardarse vacío en borrador, pero el servicio bloquea cualquier envío o reenvío mientras esté vacío.
- `BusinessProposal.total_investment` es la inversión base. El total que ve el cliente suma módulos calculables seleccionados.
- Los números del hosting viven en `BusinessProposal`; `investment.hostingPlan` es su presentación.
- Una selección vacía de módulos debe quedar confirmada mediante `ProposalChangeLog.ChangeType.CALCULATOR_CONFIRMED`; de lo contrario pueden reaparecer defaults.
- `technicalDocument.requirements[].linked_item_ids` debe apuntar literalmente a IDs de `functionalRequirements`.

## Conflictos conocidos que no deben revivirse

- El sistema vigente tiene 18 tipos de sección; no codifiques “17”.
- Hosting no tiene un porcentaje perpetuo: se lee de `ProposalDefaultConfig` o se personaliza con aprobación.
- `valueAddedModules.module_ids` puede contener ninguno, un subconjunto o todos los módulos gratuitos válidos.
- Las formas de pago no están fijadas a 40/30/30; deben sumar 100 y reflejar lo acordado.
- Un módulo seleccionado por defecto en la plantilla no constituye autorización comercial.
