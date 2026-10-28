from __future__ import annotations

import copy
import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "proposal_artifact.py"
SPEC = importlib.util.spec_from_file_location("proposal_artifact", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

CREATE_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "create_draft.py"
CREATE_SPEC = importlib.util.spec_from_file_location("create_draft", CREATE_SCRIPT)
CREATE_MODULE = importlib.util.module_from_spec(CREATE_SPEC)
sys.modules[CREATE_SPEC.name] = CREATE_MODULE
assert CREATE_SPEC.loader is not None
CREATE_SPEC.loader.exec_module(CREATE_MODULE)


def valid_artifact():
    technical = {
        "purpose": "Administrar contenido informativo con trazabilidad.",
        "stack": [
            {"layer": "Backend", "technology": "Django", "rationale": "Gestión segura"}
        ],
        "architecture": {"summary": "Aplicación web modular.", "patterns": [], "diagramNote": ""},
        "dataModel": {"summary": "Contenido editable.", "relationships": "", "entities": []},
        "growthReadiness": {"summary": "Escalable por módulos.", "strategies": []},
        "epics": [
            {
                "epicKey": "views",
                "title": "Vistas",
                "description": "Contenido público.",
                "requirements": [
                    {
                        "flowKey": "show-home",
                        "title": "Mostrar inicio",
                        "linked_item_ids": ["item-views-pagina-de-inicio"],
                    },
                    {
                        "flowKey": "browse-home",
                        "title": "Navegar inicio",
                        "linked_item_ids": ["item-views-pagina-de-inicio"],
                    },
                ],
            }
        ],
        "apiSummary": "API autenticada.",
        "apiDomains": [],
        "integrations": {"included": [], "excluded": [], "notes": ""},
        "environments": [],
        "environmentsNote": "Entorno definido por ProjectApp.",
        "security": [],
        "performanceQuality": {"metrics": [], "practices": []},
        "backupsNote": "Respaldos programados.",
        "quality": {"dimensions": [], "testTypes": [], "criticalFlowsNote": ""},
        "decisions": [],
    }
    return {
        "general": {
            "proposalTitle": "Propuesta de sitio web — Acme",
            "clientName": "Acme",
            "inspirationalQuote": "Construimos una base digital útil.",
        },
        "functionalRequirements": {
            "index": "1",
            "title": "Requerimientos funcionales",
            "intro": "Alcance confirmado.",
            "groups": [
                {
                    "id": "views",
                    "icon": "🖥️",
                    "title": "Vistas",
                    "description": "Vistas públicas.",
                    "is_visible": True,
                    "price_percent": 0,
                    "items": [
                        {
                            "id": "item-views-pagina-de-inicio",
                            "name": "Página de inicio",
                            "description": (
                                "<b>Página</b> principal del proyecto."
                                "<br><br>El usuario podrá <b>consultar</b> el contenido publicado."
                            ),
                        }
                    ],
                }
            ],
            "additionalModules": [
                {
                    "id": "pwa_module",
                    "icon": "📱",
                    "title": "PWA",
                    "description": "Aplicación instalable.",
                    "is_visible": True,
                    "is_calculator_module": True,
                    "selected": False,
                    "default_selected": False,
                    "price_percent": 20,
                    "items": [],
                }
            ],
        },
        "investment": {
            "index": "2",
            "title": "Inversión",
            "totalInvestment": "$1.000",
            "currency": "COP",
            "paymentOptions": [
                {"label": "50% para iniciar", "description": "$500 COP"},
                {"label": "50% contra entrega", "description": "$500 COP"},
            ],
            "hostingPlan": {
                "title": "",
                "description": "",
                "specs": [],
                "hostingPercent": 0,
                "billingTiers": [],
                "renewalNote": "",
                "coverageNote": "",
                "freeMonths": 0,
                "freeMonthNote": "",
            },
        },
        "valueAddedModules": {
            "index": "3",
            "title": "Valor agregado",
            "intro": "",
            "module_ids": [],
            "justifications": {},
            "footer_note": "",
        },
        "roiProjection": {
            "index": "4",
            "title": "Retorno",
            "subtitle": "",
            "kpis": [],
            "scenariosTitle": "",
            "scenarios": [],
            "methodology": "",
            "ctaNote": "",
        },
        "commercialConditions": {
            "index": "5",
            "title": "Condiciones comerciales",
            "hourPackagesEnabled": False,
        },
        "technicalDocument": technical,
        "_meta": {
            "optional_metadata": {
                "email_intro": (
                    "Esta propuesta ordena la operación comercial de Acme en "
                    "un solo sitio para reducir reprocesos y acelerar decisiones."
                )
            }
        },
    }


def valid_manifest():
    return {
        "schema_version": 1,
        "target_environment": "development",
        "proposal": {
            "title": "Propuesta de sitio web — Acme",
            "client_name": "Acme",
            "client_email": "",
            "client_phone": "",
            "client_company": "Acme",
            "project_type": "website",
            "market_type": "b2b",
            "project_type_custom": "",
            "market_type_custom": "",
            "language": "es",
            "currency": "COP",
            "nationality": "COL",
            "base_investment": 1000,
        },
        "pricing": {
            "mode": "base_plus_modules",
            "quoted_total": 1000,
            "payments": [
                {"percentage": 50, "milestone": "Para iniciar"},
                {"percentage": 50, "milestone": "Contra entrega"},
            ],
        },
        "hosting": {
            "mode": "none",
            "percent": 0,
            "discount_nine_month": 0,
            "discount_semiannual": 0,
            "discount_quarterly": 0,
        },
        "modules": {"selected_additional": [], "value_added": []},
        "section_visibility": {
            "roi_projection": False,
            "technical_document": True,
            "value_added_modules": False,
            "commercial_conditions": False,
        },
        "commercial": {"hour_packages_enabled": False},
        "roi": {"enabled": False, "sources": []},
    }


class ProposalArtifactAuditTests(unittest.TestCase):
    def setUp(self):
        self.artifact = valid_artifact()
        self.manifest = valid_manifest()
        self.template = copy.deepcopy(self.artifact)

    def test_accepts_complete_artifact_without_optional_sections(self):
        result = MODULE.audit_artifact(self.artifact, self.manifest, self.template)

        self.assertTrue(result.passed, result.failures)

    def test_rejects_missing_live_section(self):
        del self.artifact["commercialConditions"]

        result = MODULE.audit_artifact(self.artifact, self.manifest, self.template)

        self.assertTrue(any("SECTION_MISSING" in failure for failure in result.failures))

    def test_build_payload_includes_email_intro(self):
        payload = MODULE.build_payload(self.artifact, self.manifest)

        self.assertEqual(
            payload["email_intro"],
            self.artifact["_meta"]["optional_metadata"]["email_intro"],
        )

    def test_rejects_missing_email_intro(self):
        self.artifact["_meta"]["optional_metadata"].pop("email_intro")

        result = MODULE.audit_artifact(self.artifact, self.manifest, self.template)

        self.assertTrue(any("EMAIL_INTRO:" in failure for failure in result.failures))

    def test_rejects_markup_in_email_intro(self):
        self.artifact["_meta"]["optional_metadata"]["email_intro"] = (
            "Resolvemos <b>reprocesos</b> para acelerar decisiones."
        )

        result = MODULE.audit_artifact(self.artifact, self.manifest, self.template)

        self.assertTrue(any("EMAIL_INTRO_HTML" in failure for failure in result.failures))

    def test_rejects_unconfirmed_default_module(self):
        module = self.artifact["functionalRequirements"]["additionalModules"][0]
        module["default_selected"] = True

        result = MODULE.audit_artifact(self.artifact, self.manifest, self.template)

        self.assertTrue(any("MODULE_DEFAULT" in failure for failure in result.failures))

    def test_rejects_payment_amount_not_based_on_effective_total(self):
        self.artifact["investment"]["paymentOptions"][0]["description"] = "$400 COP"

        result = MODULE.audit_artifact(self.artifact, self.manifest, self.template)

        self.assertTrue(any("PAYMENT_AMOUNT" in failure for failure in result.failures))

    def test_rejects_missing_technical_traceability(self):
        requirements = self.artifact["technicalDocument"]["epics"][0]["requirements"]
        for requirement in requirements:
            requirement["linked_item_ids"] = []

        result = MODULE.audit_artifact(self.artifact, self.manifest, self.template)

        self.assertTrue(any("TECHNICAL_COVERAGE" in failure for failure in result.failures))

    def test_rejects_apply_without_literal_confirmation(self):
        with self.assertRaises(MODULE.ProposalArtifactError):
            CREATE_MODULE.require_apply_confirmation(True, "yes")

    def test_accepts_final_total_with_selected_calculator_module(self):
        module = self.artifact["functionalRequirements"]["additionalModules"][0]
        module["selected"] = True
        module["default_selected"] = True
        module["items"] = [
            {
                "id": "item-pwa_module-instalacion",
                "name": "Instalación",
                "description": (
                    "<b>Instalación</b> del producto en el dispositivo."
                    "<br><br>El usuario podrá <b>instalar</b> el acceso desde su navegador."
                ),
            }
        ]
        self.manifest["modules"]["selected_additional"] = ["pwa_module"]
        self.manifest["pricing"]["mode"] = "final_inclusive"
        self.manifest["pricing"]["quoted_total"] = 1200
        for option in self.artifact["investment"]["paymentOptions"]:
            option["description"] = "$600 COP"
        self.artifact["technicalDocument"]["epics"].append(
            {
                "epicKey": "pwa_module",
                "title": "PWA",
                "description": "Instalación del producto.",
                "linked_module_ids": ["module-pwa_module"],
                "requirements": [
                    {
                        "flowKey": "install-pwa",
                        "title": "Instalar producto",
                        "linked_module_ids": ["module-pwa_module"],
                        "linked_item_ids": ["item-pwa_module-instalacion"],
                    },
                    {
                        "flowKey": "validate-pwa-installation",
                        "title": "Validar instalación",
                        "linked_module_ids": ["module-pwa_module"],
                        "linked_item_ids": ["item-pwa_module-instalacion"],
                    },
                ],
            }
        )

        result = MODULE.audit_artifact(self.artifact, self.manifest, self.template)

        self.assertTrue(result.passed, result.failures)
        self.assertEqual(result.details["effective_total"], "1200.00")

    def test_accepts_custom_hosting_terms(self):
        self.manifest["hosting"] = {
            "mode": "custom",
            "percent": 50,
            "discount_nine_month": 30,
            "discount_semiannual": 15,
            "discount_quarterly": 5,
        }
        self.artifact["investment"]["hostingPlan"].update(
            {
                "title": "Hosting, soporte y mantenimiento",
                "hostingPercent": 50,
                "billingTiers": [
                    {"frequency": "nine_month", "discountPercent": 30},
                    {"frequency": "semiannual", "discountPercent": 15},
                    {"frequency": "quarterly", "discountPercent": 5},
                ],
            }
        )

        result = MODULE.audit_artifact(self.artifact, self.manifest, self.template)

        self.assertTrue(result.passed, result.failures)

    def test_requires_evidence_when_roi_is_visible(self):
        self.manifest["roi"]["enabled"] = True
        self.manifest["section_visibility"]["roi_projection"] = True

        result = MODULE.audit_artifact(self.artifact, self.manifest, self.template)

        self.assertTrue(any("ROI_EVIDENCE" in failure for failure in result.failures))


if __name__ == "__main__":
    unittest.main()
