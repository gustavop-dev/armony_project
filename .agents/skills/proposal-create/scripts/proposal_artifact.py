#!/usr/bin/env python3
"""Export and audit ProjectApp business-proposal artifacts.

The module keeps the mechanical invariants out of the prose-only skill.  The
``template`` command reads active defaults without mutating data.  The
``audit`` command can run offline with an exported template and, when Django
settings are supplied, also validates through the real DRF serializer.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


RESERVED_ARTIFACT_KEYS = {"_meta", "_seller_prompt"}
SECTION_KEY_MAP = {
    "general": "greeting",
    "executiveSummary": "executive_summary",
    "contextDiagnostic": "context_diagnostic",
    "conversionStrategy": "conversion_strategy",
    "designUX": "design_ux",
    "creativeSupport": "creative_support",
    "developmentStages": "development_stages",
    "processMethodology": "process_methodology",
    "functionalRequirements": "functional_requirements",
    "timeline": "timeline",
    "investment": "investment",
    "proposalSummary": "proposal_summary",
    "finalNote": "final_note",
    "nextSteps": "next_steps",
    "technicalDocument": "technical_document",
    "valueAddedModules": "value_added_modules",
    "roiProjection": "roi_projection",
    "commercialConditions": "commercial_conditions",
}
REQUIRED_VISIBILITY_DECISIONS = {
    "roi_projection",
    "technical_document",
    "value_added_modules",
    "commercial_conditions",
}
PLACEHOLDER_RE = re.compile(
    r"\b(?:TODO|TBD|FIXME|LOREM\s+IPSUM)\b|"
    r"<\s*(?:cliente|client|empresa|company)\s*>|"
    r"client@example\.com|Propuesta\s+de\s+\.\.\.",
    re.IGNORECASE,
)
FLOW_KEY_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
HTML_TAG_RE = re.compile(r"<\s*/?\s*[a-z][^>]*>", re.IGNORECASE)
MARKDOWN_RE = re.compile(r"(?:\*\*|__|`|!?\[[^\]]+\]\([^)]+\)|^\s{0,3}#{1,6}\s)", re.MULTILINE)


class ProposalArtifactError(RuntimeError):
    """Raised when the artifact tooling cannot safely continue."""


@dataclass
class AuditResult:
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.failures

    def fail(self, code: str, detail: str) -> None:
        self.failures.append(f"{code}: {detail}")

    def warn(self, code: str, detail: str) -> None:
        self.warnings.append(f"{code}: {detail}")


def find_repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "backend" / "manage.py").is_file():
            return parent
    raise ProposalArtifactError("No se encontró la raíz de ProjectApp.")


def bootstrap_django(settings_module: str | None) -> Any:
    module = settings_module or os.environ.get("DJANGO_SETTINGS_MODULE")
    if not module:
        raise ProposalArtifactError(
            "Indica --settings; no se permite caer implícitamente en settings_dev."
        )
    backend = find_repo_root() / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    os.environ["DJANGO_SETTINGS_MODULE"] = module
    import django

    django.setup()
    from django.conf import settings

    return settings


def load_json(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ProposalArtifactError(f"No existe {source}.") from exc
    except json.JSONDecodeError as exc:
        raise ProposalArtifactError(
            f"JSON inválido en {source}: línea {exc.lineno}, columna {exc.colno}."
        ) from exc
    if not isinstance(value, dict):
        raise ProposalArtifactError(f"{source} debe contener un objeto JSON.")
    return value


def write_json(path: str | Path, value: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def decimal_value(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def integer_from_display(value: Any) -> int | None:
    if value in (None, ""):
        return None
    digits = re.sub(r"[^0-9]", "", str(value))
    return int(digits) if digits else None


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")


def artifact_sections(artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(value)
        for key, value in artifact.items()
        if key not in RESERVED_ARTIFACT_KEYS
    }


def build_payload(
    artifact: dict[str, Any],
    manifest: dict[str, Any],
    runtime_defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    proposal = manifest.get("proposal") or {}
    defaults = runtime_defaults or {}
    optional_metadata = (artifact.get("_meta") or {}).get("optional_metadata") or {}
    payload = {
        "title": proposal.get("title", ""),
        "client_name": proposal.get("client_name", ""),
        "client_email": proposal.get("client_email", ""),
        "email_intro": optional_metadata.get("email_intro", ""),
        "client_phone": proposal.get("client_phone", ""),
        "client_company": proposal.get("client_company", ""),
        "project_type": proposal.get("project_type", ""),
        "market_type": proposal.get("market_type", ""),
        "project_type_custom": proposal.get("project_type_custom", ""),
        "market_type_custom": proposal.get("market_type_custom", ""),
        "language": proposal.get("language", "es"),
        "total_investment": proposal.get("base_investment", 0),
        "currency": proposal.get("currency", "COP"),
        "nationality": proposal.get("nationality", "COL"),
        "reminder_days": defaults.get("reminder_days", 10),
        "urgency_reminder_days": defaults.get("urgency_reminder_days", 15),
        "discount_percent": defaults.get("discount_percent", 0),
        "sections": artifact_sections(artifact),
    }
    if proposal.get("client_id") is not None:
        payload["client_id"] = proposal["client_id"]
    return payload


def calculate_effective_total(
    base: Decimal,
    selected_modules: list[dict[str, Any]],
) -> Decimal:
    total = base.quantize(Decimal("0.01"))
    for module in selected_modules:
        percent = decimal_value(module.get("price_percent")) or Decimal("0")
        if percent <= 0:
            continue
        module_price = (base * percent / Decimal("100")).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
        total += module_price
    return total.quantize(Decimal("0.01"))


def _section_shape_audit(
    artifact: dict[str, Any], template: dict[str, Any], result: AuditResult
) -> None:
    expected_sections = {
        key for key in template if key not in RESERVED_ARTIFACT_KEYS
    }
    actual_sections = {
        key for key in artifact if key not in RESERVED_ARTIFACT_KEYS
    }
    for key in sorted(expected_sections - actual_sections):
        result.fail("SECTION_MISSING", key)
    for key in sorted(actual_sections - expected_sections):
        result.fail("SECTION_UNKNOWN", key)

    for key in sorted(expected_sections & actual_sections):
        expected = template.get(key)
        actual = artifact.get(key)
        if not isinstance(expected, dict) or not isinstance(actual, dict):
            if type(expected) is not type(actual):
                result.fail("SECTION_TYPE", f"{key} cambió de tipo")
            continue
        missing = set(expected) - set(actual)
        extra = set(actual) - set(expected)
        for field_name in sorted(missing):
            result.fail("FIELD_MISSING", f"{key}.{field_name}")
        for field_name in sorted(extra):
            result.fail("FIELD_UNKNOWN", f"{key}.{field_name}")


def _manifest_audit(manifest: dict[str, Any], result: AuditResult) -> None:
    if manifest.get("schema_version") != 1:
        result.fail("MANIFEST_VERSION", "schema_version debe ser 1")

    target = manifest.get("target_environment")
    if target not in {"production", "development"}:
        result.fail("TARGET_ENV", "usa production o development")

    proposal = manifest.get("proposal")
    if not isinstance(proposal, dict):
        result.fail("PROPOSAL_META", "falta proposal")
        proposal = {}
    for key in ("title", "client_name", "language", "currency", "nationality"):
        if not proposal.get(key):
            result.fail("PROPOSAL_META", f"falta proposal.{key}")
    if proposal.get("language") not in {"es", "en"}:
        result.fail("LANGUAGE", "proposal.language debe ser es o en")
    if proposal.get("currency") not in {"COP", "USD"}:
        result.fail("CURRENCY", "proposal.currency debe ser COP o USD")
    base = decimal_value(proposal.get("base_investment"))
    if base is None or base <= 0:
        result.fail("BASE_INVESTMENT", "debe ser mayor que cero")

    pricing = manifest.get("pricing")
    if not isinstance(pricing, dict):
        result.fail("PRICING", "falta pricing")
        pricing = {}
    if pricing.get("mode") not in {"base_plus_modules", "final_inclusive"}:
        result.fail("PRICING_MODE", "modo no soportado")
    quoted = decimal_value(pricing.get("quoted_total"))
    if quoted is None or quoted <= 0:
        result.fail("QUOTED_TOTAL", "debe ser mayor que cero")
    payments = pricing.get("payments")
    if not isinstance(payments, list) or not payments:
        result.fail("PAYMENTS", "se requiere al menos una cuota")
    else:
        total_percent = Decimal("0")
        for index, payment in enumerate(payments):
            if not isinstance(payment, dict):
                result.fail("PAYMENT_SHAPE", f"cuota {index + 1}")
                continue
            percent = decimal_value(payment.get("percentage"))
            if percent is None or percent <= 0:
                result.fail("PAYMENT_PERCENT", f"cuota {index + 1}")
            else:
                total_percent += percent
            if not str(payment.get("milestone") or "").strip():
                result.fail("PAYMENT_MILESTONE", f"cuota {index + 1}")
        if total_percent != Decimal("100"):
            result.fail("PAYMENT_SUM", f"las cuotas suman {total_percent}%")

    hosting = manifest.get("hosting")
    if not isinstance(hosting, dict):
        result.fail("HOSTING", "falta hosting")
        hosting = {}
    if hosting.get("mode") not in {"none", "standard", "custom"}:
        result.fail("HOSTING_MODE", "usa none, standard o custom")
    for key in (
        "percent",
        "discount_nine_month",
        "discount_semiannual",
        "discount_quarterly",
    ):
        number = decimal_value(hosting.get(key))
        if number is None or number < 0 or number > 100:
            result.fail("HOSTING_NUMBER", f"hosting.{key} debe estar entre 0 y 100")
    if hosting.get("mode") == "none" and decimal_value(hosting.get("percent")) != 0:
        result.fail("HOSTING_NONE", "hosting none requiere percent=0")

    modules = manifest.get("modules")
    if not isinstance(modules, dict):
        result.fail("MODULES", "falta modules")
    else:
        for key in ("selected_additional", "value_added"):
            values = modules.get(key)
            if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
                result.fail("MODULE_LIST", f"modules.{key} debe ser array de ids")
            elif len(values) != len(set(values)):
                result.fail("MODULE_DUPLICATE", f"modules.{key} contiene duplicados")

    visibility = manifest.get("section_visibility")
    if not isinstance(visibility, dict):
        result.fail("VISIBILITY", "falta section_visibility")
        visibility = {}
    for section_type in REQUIRED_VISIBILITY_DECISIONS:
        if not isinstance(visibility.get(section_type), bool):
            result.fail("VISIBILITY_DECISION", section_type)
    valid_types = set(SECTION_KEY_MAP.values())
    for section_type, enabled in visibility.items():
        if section_type not in valid_types:
            result.fail("VISIBILITY_SECTION", section_type)
        if not isinstance(enabled, bool):
            result.fail("VISIBILITY_VALUE", section_type)

    commercial = manifest.get("commercial")
    if not isinstance(commercial, dict) or not isinstance(
        commercial.get("hour_packages_enabled"), bool
    ):
        result.fail("COMMERCIAL", "falta commercial.hour_packages_enabled")

    roi = manifest.get("roi")
    if not isinstance(roi, dict) or not isinstance(roi.get("enabled"), bool):
        result.fail("ROI", "falta roi.enabled")
    elif roi.get("enabled") != visibility.get("roi_projection"):
        result.fail("ROI_VISIBILITY", "roi.enabled y visibilidad no coinciden")


def _email_intro_audit(artifact: dict[str, Any], result: AuditResult) -> None:
    metadata = artifact.get("_meta")
    if not isinstance(metadata, dict):
        result.fail("EMAIL_INTRO_META", "falta _meta")
        return
    optional_metadata = metadata.get("optional_metadata")
    if not isinstance(optional_metadata, dict):
        result.fail("EMAIL_INTRO_META", "falta _meta.optional_metadata")
        return
    email_intro = optional_metadata.get("email_intro")
    if not isinstance(email_intro, str) or not email_intro.strip():
        result.fail("EMAIL_INTRO", "_meta.optional_metadata.email_intro es obligatorio")
        return
    if HTML_TAG_RE.search(email_intro):
        result.fail("EMAIL_INTRO_HTML", "email_intro debe ser texto plano")
    if MARKDOWN_RE.search(email_intro):
        result.fail("EMAIL_INTRO_MARKDOWN", "email_intro no admite Markdown")
    result.details["email_intro_chars"] = len(email_intro.strip())


def _functional_requirements_audit(
    artifact: dict[str, Any],
    template: dict[str, Any],
    manifest: dict[str, Any],
    result: AuditResult,
) -> tuple[dict[str, int], set[str], set[str]]:
    fr = artifact.get("functionalRequirements")
    template_fr = template.get("functionalRequirements")
    if not isinstance(fr, dict) or not isinstance(template_fr, dict):
        result.fail("FUNCTIONAL_REQUIREMENTS", "sección inválida")
        return {}, set(), set()

    all_groups = list(fr.get("groups") or [])
    all_modules = list(fr.get("additionalModules") or [])
    template_groups = [g.get("id") for g in template_fr.get("groups") or [] if isinstance(g, dict)]
    template_modules = [m.get("id") for m in template_fr.get("additionalModules") or [] if isinstance(m, dict)]
    actual_group_ids = [g.get("id") for g in all_groups if isinstance(g, dict)]
    actual_module_ids = [m.get("id") for m in all_modules if isinstance(m, dict)]

    if [gid for gid in actual_group_ids if gid in template_groups] != template_groups:
        result.fail("GROUP_ORDER", "se eliminaron o reordenaron grupos base")
    if [mid for mid in actual_module_ids if mid in template_modules] != template_modules:
        result.fail("MODULE_ORDER", "se eliminaron o reordenaron módulos")

    module_by_id = {
        str(module.get("id")): module
        for module in all_modules
        if isinstance(module, dict) and module.get("id")
    }
    group_by_id = {
        str(group.get("id")): group
        for group in all_groups
        if isinstance(group, dict) and group.get("id")
    }
    selected_expected = set((manifest.get("modules") or {}).get("selected_additional") or [])
    unknown_selected = selected_expected - set(module_by_id)
    for module_id in sorted(unknown_selected):
        result.fail("MODULE_UNKNOWN", module_id)
    for module_id, module in module_by_id.items():
        expected = module_id in selected_expected
        if module.get("selected") is not expected:
            result.fail("MODULE_SELECTED", f"{module_id} no coincide con el manifiesto")
        if module.get("default_selected") is not expected:
            result.fail("MODULE_DEFAULT", f"{module_id} deja escapar un default")

    value_added_expected = list((manifest.get("modules") or {}).get("value_added") or [])
    value_added = artifact.get("valueAddedModules") or {}
    value_added_actual = value_added.get("module_ids") or []
    if value_added_actual != value_added_expected:
        result.fail("VALUE_ADDED", "module_ids no coincide con el manifiesto")
    if not (manifest.get("section_visibility") or {}).get("value_added_modules") and value_added_actual:
        result.fail("VALUE_ADDED_HIDDEN", "una sección oculta debe tener module_ids vacío")

    all_catalog = {**group_by_id, **module_by_id}
    for module_id in value_added_expected:
        module = all_catalog.get(module_id)
        if module is None:
            result.fail("VALUE_ADDED_UNKNOWN", module_id)
            continue
        percent = decimal_value(module.get("price_percent")) or Decimal("0")
        if percent > 0:
            result.fail("VALUE_ADDED_PRICED", f"{module_id} tiene recargo {percent}%")

    item_ids: set[str] = set()
    required_item_ids: set[str] = set()
    item_container: dict[str, str] = {}
    collision_counts: dict[str, int] = {}
    language = (manifest.get("proposal") or {}).get("language", "es")

    for container in all_groups + all_modules:
        if not isinstance(container, dict) or not container.get("id"):
            continue
        container_id = str(container["id"])
        is_required = container in all_groups and container.get("is_visible") is not False
        is_required = is_required or container_id in selected_expected
        for item in container.get("items") or []:
            if not isinstance(item, dict):
                result.fail("ITEM_SHAPE", f"{container_id} contiene un item no objeto")
                continue
            item_id = str(item.get("id") or "")
            name = str(item.get("name") or "")
            if not name:
                result.fail("ITEM_NAME", container_id)
                continue
            base = f"item-{container_id}-{slugify(name)}"
            collision_counts[base] = collision_counts.get(base, 0) + 1
            expected_id = base if collision_counts[base] == 1 else f"{base}-{collision_counts[base]}"
            if item_id != expected_id:
                result.fail("ITEM_ID", f"{item_id or '<vacío>'}; esperado {expected_id}")
            if item_id in item_ids:
                result.fail("ITEM_ID_DUPLICATE", item_id)
            if item_id:
                item_ids.add(item_id)
                item_container[item_id] = container_id
                if is_required:
                    required_item_ids.add(item_id)
            if is_required:
                description = str(item.get("description") or "")
                if "<br><br>" not in description:
                    result.fail("ITEM_DESCRIPTION", f"{item_id} requiere dos párrafos")
                else:
                    second = description.split("<br><br>", 1)[1]
                    plain_second = re.sub(r"<[^>]+>", "", second).strip()
                    prefix = "The user will be able" if language == "en" else "El usuario podrá"
                    if not plain_second.startswith(prefix):
                        result.fail("ITEM_USER_ACTION", f"{item_id} debe iniciar con «{prefix}»")

    result.details["item_container"] = item_container
    return collision_counts, item_ids, required_item_ids


def _pricing_and_hosting_audit(
    artifact: dict[str, Any], manifest: dict[str, Any], result: AuditResult
) -> None:
    proposal = manifest.get("proposal") or {}
    pricing = manifest.get("pricing") or {}
    modules_manifest = manifest.get("modules") or {}
    fr = artifact.get("functionalRequirements") or {}
    module_by_id = {
        str(module.get("id")): module
        for module in fr.get("additionalModules") or []
        if isinstance(module, dict) and module.get("id")
    }
    selected = [
        module_by_id[module_id]
        for module_id in modules_manifest.get("selected_additional") or []
        if module_id in module_by_id
    ]
    base = decimal_value(proposal.get("base_investment"))
    quoted = decimal_value(pricing.get("quoted_total"))
    if base is not None and quoted is not None:
        effective = calculate_effective_total(base, selected)
        result.details["effective_total"] = str(effective)
        if effective != quoted.quantize(Decimal("0.01")):
            result.fail(
                "EFFECTIVE_TOTAL",
                f"ProjectApp calcularía {effective}, no {quoted}",
            )
    else:
        effective = Decimal("0")

    investment = artifact.get("investment") or {}
    displayed_base = integer_from_display(investment.get("totalInvestment"))
    if base is not None and displayed_base != int(base):
        result.fail("INVESTMENT_BASE", f"investment.totalInvestment={displayed_base}, base={base}")
    if investment.get("currency") != proposal.get("currency"):
        result.fail("INVESTMENT_CURRENCY", "investment.currency no coincide")

    payments = pricing.get("payments") or []
    options = investment.get("paymentOptions") or []
    if len(options) != len(payments):
        result.fail("PAYMENT_COUNT", f"JSON={len(options)}, manifiesto={len(payments)}")
    for index, (payment, option) in enumerate(zip(payments, options), start=1):
        percent = decimal_value(payment.get("percentage"))
        label = str(option.get("label") or "")
        if percent is not None and not re.search(rf"(?<!\d){re.escape(str(percent.normalize()))}%", label):
            integer_percent = str(int(percent)) if percent == percent.to_integral() else str(percent)
            if f"{integer_percent}%" not in label:
                result.fail("PAYMENT_LABEL", f"cuota {index} no muestra {percent}%")
        amount = integer_from_display(option.get("description"))
        if percent is not None and effective > 0:
            expected_amount = int(effective * percent / Decimal("100"))
            if amount != expected_amount:
                result.fail("PAYMENT_AMOUNT", f"cuota {index}: {amount}, esperado {expected_amount}")

    hosting = manifest.get("hosting") or {}
    plan = investment.get("hostingPlan") or {}
    percent = decimal_value(hosting.get("percent"))
    plan_percent = decimal_value(plan.get("hostingPercent"))
    if percent is not None and plan_percent != percent:
        result.fail("HOSTING_PERCENT", f"JSON={plan_percent}, manifiesto={percent}")
    title = str(plan.get("title") or "").strip()
    if hosting.get("mode") == "none" and title:
        result.fail("HOSTING_VISIBLE", "hosting none requiere título vacío")
    if hosting.get("mode") in {"standard", "custom"} and not title:
        result.fail("HOSTING_HIDDEN", "hosting habilitado requiere título")

    discount_fields = {
        "nine_month": "discount_nine_month",
        "semiannual": "discount_semiannual",
        "quarterly": "discount_quarterly",
    }
    tiers = {
        str(tier.get("frequency")): tier
        for tier in plan.get("billingTiers") or []
        if isinstance(tier, dict) and tier.get("frequency")
    }
    if hosting.get("mode") != "none":
        for frequency, manifest_key in discount_fields.items():
            expected = decimal_value(hosting.get(manifest_key))
            actual = decimal_value((tiers.get(frequency) or {}).get("discountPercent"))
            if expected != actual:
                result.fail("HOSTING_DISCOUNT", f"{frequency}: JSON={actual}, manifiesto={expected}")


def _roi_audit(artifact: dict[str, Any], manifest: dict[str, Any], result: AuditResult) -> None:
    roi_manifest = manifest.get("roi") or {}
    if not roi_manifest.get("enabled"):
        return
    roi = artifact.get("roiProjection") or {}
    kpis = roi.get("kpis") or []
    scenarios = roi.get("scenarios") or []
    if len(kpis) != 3:
        result.fail("ROI_KPIS", f"se esperaban 3 y hay {len(kpis)}")
    for index, kpi in enumerate(kpis, start=1):
        source = str((kpi or {}).get("source") or "")
        if not source or not YEAR_RE.search(source):
            result.fail("ROI_KPI_SOURCE", f"KPI {index} sin fuente y año")
    if len(scenarios) != 3:
        result.fail("ROI_SCENARIOS", f"se esperaban 3 y hay {len(scenarios)}")
    names = [str((scenario or {}).get("name") or "") for scenario in scenarios]
    if names != ["conservative", "realistic", "optimistic"]:
        result.fail("ROI_SCENARIO_NAMES", str(names))
    if not str(roi.get("methodology") or "").strip():
        result.fail("ROI_METHODOLOGY", "falta metodología")
    for scenario in scenarios:
        assumptions = scenario.get("assumptions") or []
        if not 2 <= len(assumptions) <= 4:
            result.fail("ROI_ASSUMPTIONS", str(scenario.get("name")))
        metrics = scenario.get("metrics") or []
        emphasized = [metric for metric in metrics if metric.get("emphasis") is True]
        if len(emphasized) != 1:
            result.fail("ROI_EMPHASIS", str(scenario.get("name")))
        elif not str(emphasized[0].get("basis") or "").strip():
            result.fail("ROI_BASIS", str(scenario.get("name")))

    sources = roi_manifest.get("sources") or []
    if len(sources) != 3:
        result.fail("ROI_EVIDENCE", f"se requieren 3 evidencias y hay {len(sources)}")
    for index, source in enumerate(sources, start=1):
        if not isinstance(source, dict):
            result.fail("ROI_EVIDENCE_SHAPE", str(index))
            continue
        parsed = urlparse(str(source.get("url") or ""))
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            result.fail("ROI_EVIDENCE_URL", str(index))
        for key in ("title", "organization", "year", "accessed_at"):
            if not source.get(key):
                result.fail("ROI_EVIDENCE_FIELD", f"{index}.{key}")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(source.get("accessed_at") or "")):
            result.fail("ROI_ACCESSED_AT", str(index))


def _technical_audit(
    artifact: dict[str, Any],
    template: dict[str, Any],
    required_item_ids: set[str],
    all_item_ids: set[str],
    manifest: dict[str, Any],
    result: AuditResult,
) -> None:
    technical = artifact.get("technicalDocument")
    template_technical = template.get("technicalDocument")
    if not isinstance(technical, dict) or not isinstance(template_technical, dict):
        result.fail("TECHNICAL_DOCUMENT", "sección inválida")
        return
    if set(technical) != set(template_technical):
        result.fail("TECHNICAL_SHAPE", "las claves de primer nivel cambiaron")
    if not str(technical.get("purpose") or "").strip():
        result.fail("TECHNICAL_PURPOSE", "falta purpose")
    if not technical.get("stack"):
        result.fail("TECHNICAL_STACK", "stack vacío")

    fr = artifact.get("functionalRequirements") or {}
    selected = set((manifest.get("modules") or {}).get("selected_additional") or [])
    expected_epics = [
        str(group.get("id"))
        for group in fr.get("groups") or []
        if isinstance(group, dict) and group.get("id") and group.get("is_visible") is not False
    ]
    expected_epics.extend(
        str(module.get("id"))
        for module in fr.get("additionalModules") or []
        if isinstance(module, dict) and module.get("id") in selected
    )

    epics = technical.get("epics") or []
    epic_keys = [str(epic.get("epicKey") or "") for epic in epics if isinstance(epic, dict)]
    for epic_key in expected_epics:
        if epic_keys.count(epic_key) != 1:
            result.fail("TECHNICAL_EPIC", f"{epic_key} aparece {epic_keys.count(epic_key)} veces")
    for epic_key in epic_keys:
        if epic_key not in expected_epics and not epic_key.startswith("cross-"):
            result.fail("TECHNICAL_EPIC_EXTRA", epic_key)

    flow_keys: set[str] = set()
    link_counts = {item_id: 0 for item_id in required_item_ids}
    for epic in epics:
        if not isinstance(epic, dict):
            result.fail("TECHNICAL_EPIC_SHAPE", "épica no objeto")
            continue
        epic_key = str(epic.get("epicKey") or "")
        expected_module_links = [f"module-{epic_key}"] if epic_key in selected else []
        actual_epic_links = epic.get("linked_module_ids") or []
        if actual_epic_links != expected_module_links:
            result.fail(
                "LINKED_MODULE",
                f"épica {epic_key}: {actual_epic_links}, esperado {expected_module_links}",
            )
        for requirement in epic.get("requirements") or []:
            if not isinstance(requirement, dict):
                result.fail("TECHNICAL_REQUIREMENT_SHAPE", epic_key)
                continue
            flow_key = str(requirement.get("flowKey") or "")
            actual_requirement_links = requirement.get("linked_module_ids") or []
            if actual_requirement_links != expected_module_links:
                result.fail(
                    "LINKED_MODULE",
                    f"{flow_key or epic_key}: {actual_requirement_links}, esperado {expected_module_links}",
                )
            if not FLOW_KEY_RE.fullmatch(flow_key):
                result.fail("FLOW_KEY", flow_key or "<vacío>")
            if flow_key in flow_keys:
                result.fail("FLOW_KEY_DUPLICATE", flow_key)
            flow_keys.add(flow_key)
            linked = requirement.get("linked_item_ids") or []
            if not isinstance(linked, list):
                result.fail("LINKED_ITEMS_SHAPE", flow_key)
                continue
            for item_id in linked:
                if item_id not in all_item_ids:
                    result.fail("LINKED_ITEM_UNKNOWN", f"{flow_key} -> {item_id}")
                if item_id in link_counts:
                    link_counts[item_id] += 1
            if not flow_key.startswith("cross-") and len(linked) > 3:
                result.fail("LINKED_ITEM_BREADTH", f"{flow_key} enlaza {len(linked)} items")

    missing = [item_id for item_id, count in link_counts.items() if count == 0]
    for item_id in missing:
        result.fail("TECHNICAL_COVERAGE", item_id)
    if link_counts:
        deep = sum(1 for count in link_counts.values() if count >= 2)
        ratio = Decimal(deep) / Decimal(len(link_counts))
        result.details["technical_depth_ratio"] = f"{ratio:.2%}"
        if ratio < Decimal("0.80"):
            result.fail("TECHNICAL_DEPTH", f"solo {ratio:.0%} de items tiene 2+ requerimientos")


def _commercial_visibility_audit(
    artifact: dict[str, Any], manifest: dict[str, Any], result: AuditResult
) -> None:
    commercial = artifact.get("commercialConditions") or {}
    expected = (manifest.get("commercial") or {}).get("hour_packages_enabled")
    if commercial.get("hourPackagesEnabled") is not expected:
        result.fail("HOUR_PACKAGES", "hourPackagesEnabled no coincide con el manifiesto")


def _placeholder_audit(value: Any, result: AuditResult, path: str = "sections") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            _placeholder_audit(child, result, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _placeholder_audit(child, result, f"{path}[{index}]")
    elif isinstance(value, str) and PLACEHOLDER_RE.search(value):
        result.fail("PLACEHOLDER", path)


def audit_artifact(
    artifact: dict[str, Any],
    manifest: dict[str, Any],
    template: dict[str, Any],
) -> AuditResult:
    result = AuditResult()
    _manifest_audit(manifest, result)
    _section_shape_audit(artifact, template, result)
    _email_intro_audit(artifact, result)

    general = artifact.get("general") or {}
    proposal = manifest.get("proposal") or {}
    if general.get("clientName") != proposal.get("client_name"):
        result.fail("CLIENT_NAME", "general.clientName no coincide con el manifiesto")
    if general.get("proposalTitle") != proposal.get("title"):
        result.fail("PROPOSAL_TITLE", "general.proposalTitle no coincide con el manifiesto")

    _, all_item_ids, required_item_ids = _functional_requirements_audit(
        artifact, template, manifest, result
    )
    _pricing_and_hosting_audit(artifact, manifest, result)
    _roi_audit(artifact, manifest, result)
    _technical_audit(
        artifact,
        template,
        required_item_ids,
        all_item_ids,
        manifest,
        result,
    )
    _commercial_visibility_audit(artifact, manifest, result)
    _placeholder_audit(artifact_sections(artifact), result)
    result.details["sections"] = len(artifact_sections(artifact))
    result.details["items"] = len(all_item_ids)
    return result


def live_template(
    language: str,
    *,
    allow_hardcoded_fallback: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    from django.db import OperationalError

    from content.models import ProposalDefaultConfig
    from content.serializers.proposal import SECTION_TYPE_TO_KEY
    from content.services.proposal_service import ProposalService

    try:
        sections = ProposalService.get_default_sections(language)
        config = ProposalDefaultConfig.objects.filter(language=language).first()
    except OperationalError:
        if not allow_hardcoded_fallback:
            raise
        sections = ProposalService.get_hardcoded_defaults(language)
        config = None
    template: dict[str, Any] = {}
    for config in sections:
        section_type = config["section_type"]
        key = SECTION_TYPE_TO_KEY.get(section_type, section_type)
        template[key] = copy.deepcopy(config["content_json"])
    template["_meta"] = {
        "description": "Proposal JSON template — fill and import through ProjectApp",
        "required_fields": ["general.clientName"],
        "optional_metadata": {
            "title": "Propuesta de ... — Client Name",
            "client_email": "client@example.com",
            "email_intro": (
                "Mensaje específico en texto plano: problema del cliente, "
                "solución propuesta y resultado de negocio esperado."
            ),
            "language": language,
            "total_investment": 0,
            "currency": "COP | USD",
            "nationality": "COL | EXT | USA",
        },
    }
    fr = template.get("functionalRequirements") or {}
    for group in fr.get("groups") or []:
        group["_do_not_remove"] = True
    for module in fr.get("additionalModules") or []:
        module["_do_not_remove"] = True

    runtime = {
        "hosting_percent": getattr(config, "hosting_percent", 60),
        "hosting_discount_nine_month": getattr(config, "hosting_discount_nine_month", 40),
        "hosting_discount_semiannual": getattr(config, "hosting_discount_semiannual", 20),
        "hosting_discount_quarterly": getattr(config, "hosting_discount_quarterly", 10),
        "reminder_days": getattr(config, "reminder_days", 10),
        "urgency_reminder_days": getattr(config, "urgency_reminder_days", 15),
        "discount_percent": getattr(config, "default_discount_percent", 0),
    }
    return template, runtime


def actual_environment(settings: Any) -> str:
    return "production" if bool(getattr(settings, "IS_PRODUCTION", False)) else "development"


def live_validation(
    artifact: dict[str, Any],
    manifest: dict[str, Any],
    settings: Any,
    result: AuditResult,
) -> None:
    from content.models import ProposalDefaultConfig
    from content.serializers.proposal import ProposalFromJSONSerializer

    actual = actual_environment(settings)
    target = manifest.get("target_environment")
    if actual != target:
        result.fail("ENVIRONMENT_MISMATCH", f"settings={actual}, manifiesto={target}")

    language = (manifest.get("proposal") or {}).get("language", "es")
    config = ProposalDefaultConfig.objects.filter(language=language).first()
    runtime_defaults = {
        "reminder_days": getattr(config, "reminder_days", 10),
        "urgency_reminder_days": getattr(config, "urgency_reminder_days", 15),
        "discount_percent": getattr(config, "default_discount_percent", 0),
    }
    serializer = ProposalFromJSONSerializer(
        data=build_payload(artifact, manifest, runtime_defaults)
    )
    if not serializer.is_valid():
        result.fail(
            "SERIALIZER",
            json.dumps(serializer.errors, ensure_ascii=False, default=str),
        )

    hosting = manifest.get("hosting") or {}
    if hosting.get("mode") == "standard":
        expected = {
            "percent": getattr(config, "hosting_percent", 60),
            "discount_nine_month": getattr(config, "hosting_discount_nine_month", 40),
            "discount_semiannual": getattr(config, "hosting_discount_semiannual", 20),
            "discount_quarterly": getattr(config, "hosting_discount_quarterly", 10),
        }
        for key, value in expected.items():
            if decimal_value(hosting.get(key)) != Decimal(str(value)):
                result.fail("HOSTING_STANDARD_DRIFT", f"{key}: activo={value}, manifiesto={hosting.get(key)}")


def print_audit(result: AuditResult) -> None:
    print("AUDIT_PASS" if result.passed else "AUDIT_FAIL")
    for failure in result.failures:
        print(f"  FAIL {failure}")
    for warning in result.warnings:
        print(f"  WARN {warning}")
    if result.details:
        print("  DETAILS " + json.dumps(result.details, ensure_ascii=False, sort_keys=True))


def template_command(args: argparse.Namespace) -> int:
    settings = bootstrap_django(args.settings)
    template, runtime = live_template(
        args.language,
        allow_hardcoded_fallback=actual_environment(settings) == "development",
    )
    write_json(args.output, template)
    print(
        "TEMPLATE_WRITTEN "
        + json.dumps(
            {
                "path": str(Path(args.output).resolve()),
                "environment": actual_environment(settings),
                "language": args.language,
                "sections": len(artifact_sections(template)),
                "runtime_defaults": runtime,
            },
            ensure_ascii=False,
        )
    )
    return 0


def audit_command(args: argparse.Namespace) -> int:
    artifact = load_json(args.artifact)
    manifest = load_json(args.manifest)
    if args.template:
        template = load_json(args.template)
    else:
        settings = bootstrap_django(args.settings)
        language = (manifest.get("proposal") or {}).get("language", "es")
        template, _ = live_template(
            language,
            allow_hardcoded_fallback=actual_environment(settings) == "development",
        )
    result = audit_artifact(artifact, manifest, template)
    if args.settings:
        settings = bootstrap_django(args.settings)
        live_validation(artifact, manifest, settings, result)
    print_audit(result)
    return 0 if result.passed else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    template_parser = subparsers.add_parser("template", help="Export active proposal template")
    template_parser.add_argument("--settings", required=True)
    template_parser.add_argument("--language", choices=("es", "en"), default="es")
    template_parser.add_argument("--output", required=True)
    template_parser.set_defaults(handler=template_command)

    audit_parser = subparsers.add_parser("audit", help="Audit an artifact and manifest")
    audit_parser.add_argument("artifact")
    audit_parser.add_argument("manifest")
    audit_parser.add_argument("--template")
    audit_parser.add_argument("--settings")
    audit_parser.set_defaults(handler=audit_command)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except ProposalArtifactError as exc:
        print(f"TOOL_ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
