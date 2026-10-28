# Contrato comercial, JSON y manifiesto

## Artefacto importable

Parte de la plantilla activa. Conserva todas las claves de sección camelCase y el shape de primer nivel de cada `content_json`. `_meta.optional_metadata` solo puede usar las claves presentes en la plantilla exportada; información operativa adicional vive en el manifiesto.

Reglas principales:

- `general.clientName` y `general.proposalTitle` deben coincidir con el manifiesto.
- `_meta.optional_metadata.email_intro` es obligatorio: redacta en texto plano un mensaje breve y específico que conecte el problema del cliente, la solución de esta propuesta y el resultado de negocio esperado. No uses HTML, Markdown ni una introducción genérica reutilizable.
- Mantén todos los grupos y módulos de `functionalRequirements` en su array y orden original.
- Cada item comercial debe ser atómico, tener descripción específica y un `id` único y estable con formato `item-<group_id>-<slug>`.
- Personaliza grupos base y módulos adicionales confirmados. No inventes alcance para módulos no seleccionados.
- En cada módulo adicional fija ambos flags: `selected` y `default_selected` son `true` únicamente cuando su id aparece en `modules.selected_additional`.
- `valueAddedModules.module_ids` debe coincidir exactamente con `modules.value_added`; puede estar vacío.
- El contenido debe seguir el prompt comercial vigente, respetar límites visuales y evitar placeholders.

## Manifiesto

Usa este contrato, sin agregar decisiones implícitas:

```json
{
  "schema_version": 1,
  "target_environment": "production",
  "proposal": {
    "title": "Propuesta de ...",
    "client_name": "...",
    "client_email": "",
    "client_phone": "",
    "client_company": "",
    "project_type": "",
    "market_type": "",
    "project_type_custom": "",
    "market_type_custom": "",
    "language": "es",
    "currency": "COP",
    "nationality": "COL",
    "base_investment": 0
  },
  "pricing": {
    "mode": "base_plus_modules",
    "quoted_total": 0,
    "payments": [
      {"percentage": 50, "milestone": "Para iniciar"},
      {"percentage": 50, "milestone": "Contra entrega"}
    ]
  },
  "hosting": {
    "mode": "none",
    "percent": 0,
    "discount_nine_month": 0,
    "discount_semiannual": 0,
    "discount_quarterly": 0
  },
  "modules": {
    "selected_additional": [],
    "value_added": []
  },
  "section_visibility": {
    "roi_projection": false,
    "technical_document": true,
    "value_added_modules": false,
    "commercial_conditions": false
  },
  "commercial": {
    "hour_packages_enabled": false
  },
  "roi": {
    "enabled": false,
    "sources": []
  }
}
```

`target_environment` admite `production` o `development`. El creador rechaza una configuración de Django que no corresponda.

`pricing.mode` admite:

- `base_plus_modules`: el valor entregado por el operador es la inversión base y ProjectApp suma los módulos con `price_percent > 0`.
- `final_inclusive`: el valor entregado es el total final; antes de generar, despeja y confirma una base que reproduzca ese total.

En ambos modos, `proposal.base_investment` contiene lo que se persistirá en `BusinessProposal.total_investment` y `pricing.quoted_total` contiene el total que debe ver el cliente.

## Aritmética

ProjectApp calcula cada módulo por separado:

```text
precio_módulo = redondear(base × price_percent / 100)
total_efectivo = base + suma(precio_módulo)
```

No sumes porcentajes antes de redondear. Los porcentajes de `pricing.payments` deben sumar 100. Cada monto de `investment.paymentOptions` se calcula sobre el total efectivo, mientras `investment.totalInvestment` representa la base.

## Hosting

- `none`: `percent=0` y `investment.hostingPlan.title` vacío para ocultarlo en web y PDF.
- `standard`: copia al manifiesto el porcentaje y descuentos activos del entorno; no números memorizados.
- `custom`: usa exclusivamente los números y la narrativa aprobados por el operador.

Los números de `investment.hostingPlan` deben coincidir con el manifiesto. El creador vuelve a fijarlos en el modelo para que la normalización pública no los reemplace.

## ROI

Cuando `roi.enabled=true`:

- `section_visibility.roi_projection` también es `true`;
- genera exactamente tres KPIs y tres escenarios;
- cada KPI tiene fuente real con organización y año;
- cada escenario explica supuestos y cada métrica enfatizada incluye su base aritmética;
- `roi.sources` conserva una evidencia por KPI con `url`, `title`, `organization`, `year` y `accessed_at` (`YYYY-MM-DD`).

Cuando está deshabilitado, la sección puede conservar el shape de la plantilla, pero queda oculta y el auditor no exige KPIs.

## Presentación comercial

Sigue el arco narrativo y el tono definidos en `useSellerPrompt.js`. Presenta problema y valor antes de inversión. Distingue hechos externos verificados, datos aportados por el cliente y proyecciones. Nunca redactes una proyección como garantía.
