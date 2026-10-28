#!/usr/bin/env python3
"""Validate and optionally create a safe ProjectApp proposal draft."""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from typing import Any

from proposal_artifact import (
    ProposalArtifactError,
    actual_environment,
    audit_artifact,
    bootstrap_django,
    build_payload,
    decimal_value,
    live_template,
    live_validation,
    load_json,
    print_audit,
)


CONFIRMATION = "CREATE_DRAFT"


def require_apply_confirmation(apply: bool, confirmation: str) -> None:
    """Reject a mutating invocation before Django or the database is touched."""
    if apply and confirmation != CONFIRMATION:
        raise ProposalArtifactError(
            f"--apply requiere --confirm {CONFIRMATION}."
        )


def runtime_defaults(language: str) -> dict[str, Any]:
    from content.models import ProposalDefaultConfig

    config = ProposalDefaultConfig.objects.filter(language=language).first()
    return {
        "reminder_days": getattr(config, "reminder_days", 10),
        "urgency_reminder_days": getattr(config, "urgency_reminder_days", 15),
        "discount_percent": getattr(config, "default_discount_percent", 0),
    }


def duplicate_candidates(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    from django.db.models import Q

    from content.models import BusinessProposal, ProposalDefaultConfig
    from content.utils import render_slug_pattern, safe_slug

    proposal_data = manifest.get("proposal") or {}
    title = str(proposal_data.get("title") or "").strip()
    client_name = str(proposal_data.get("client_name") or "").strip()
    language = proposal_data.get("language", "es")

    candidate = BusinessProposal(
        title=title,
        client_name=client_name,
        project_type=proposal_data.get("project_type", ""),
        language=language,
    )
    config = ProposalDefaultConfig.objects.filter(language=language).first()
    pattern = getattr(config, "default_slug_pattern", "")
    rendered = render_slug_pattern(pattern, candidate, fallback="propuesta") if pattern else client_name
    slug = safe_slug(rendered, "propuesta")

    query = Q(title__iexact=title, client_name__iexact=client_name)
    if slug:
        query |= Q(slug=slug)
    rows = (
        BusinessProposal.objects.filter(query)
        .order_by("-created_at")
        .values("id", "title", "client_name", "slug", "status")[:10]
    )
    return list(rows)


def validated_serializer(artifact: dict[str, Any], manifest: dict[str, Any]):
    from content.serializers.proposal import ProposalFromJSONSerializer

    language = (manifest.get("proposal") or {}).get("language", "es")
    serializer = ProposalFromJSONSerializer(
        data=build_payload(artifact, manifest, runtime_defaults(language))
    )
    if not serializer.is_valid():
        raise ProposalArtifactError(
            "ProposalFromJSONSerializer rechazó el payload: "
            + json.dumps(serializer.errors, ensure_ascii=False, default=str)
        )
    return serializer


def _apply_manifest_to_sections(proposal, manifest: dict[str, Any]) -> None:
    from content.models import ProposalSection

    visibility = manifest.get("section_visibility") or {}
    selected = set((manifest.get("modules") or {}).get("selected_additional") or [])
    value_added = list((manifest.get("modules") or {}).get("value_added") or [])
    hosting = manifest.get("hosting") or {}

    for section in proposal.sections.all():
        update_fields: list[str] = []
        if section.section_type in visibility:
            enabled = bool(visibility[section.section_type])
            if section.is_enabled != enabled:
                section.is_enabled = enabled
                update_fields.append("is_enabled")

        content = dict(section.content_json or {})
        content_changed = False
        if section.section_type == ProposalSection.SectionType.FUNCTIONAL_REQUIREMENTS:
            modules = []
            for module in content.get("additionalModules") or []:
                module = dict(module)
                should_select = module.get("id") in selected
                if module.get("selected") is not should_select:
                    module["selected"] = should_select
                    content_changed = True
                if module.get("default_selected") is not should_select:
                    module["default_selected"] = should_select
                    content_changed = True
                modules.append(module)
            content["additionalModules"] = modules

        elif section.section_type == ProposalSection.SectionType.VALUE_ADDED_MODULES:
            if content.get("module_ids") != value_added:
                content["module_ids"] = value_added
                content_changed = True

        elif section.section_type == ProposalSection.SectionType.INVESTMENT:
            plan = dict(content.get("hostingPlan") or {})
            percent = int(decimal_value(hosting.get("percent")) or 0)
            if plan.get("hostingPercent") != percent:
                plan["hostingPercent"] = percent
                content_changed = True
            if hosting.get("mode") == "none" and plan.get("title"):
                plan["title"] = ""
                content_changed = True
            discount_fields = {
                "nine_month": "discount_nine_month",
                "semiannual": "discount_semiannual",
                "quarterly": "discount_quarterly",
            }
            tiers = []
            for tier in plan.get("billingTiers") or []:
                tier = dict(tier)
                manifest_key = discount_fields.get(tier.get("frequency"))
                if manifest_key:
                    discount = int(decimal_value(hosting.get(manifest_key)) or 0)
                    if tier.get("discountPercent") != discount:
                        tier["discountPercent"] = discount
                        content_changed = True
                tiers.append(tier)
            plan["billingTiers"] = tiers
            content["hostingPlan"] = plan

        if content_changed:
            section.content_json = content
            update_fields.append("content_json")
        if update_fields:
            section.save(update_fields=update_fields)


def create_draft(serializer, manifest: dict[str, Any]) -> dict[str, Any]:
    from django.conf import settings
    from django.db import transaction

    from content.models import BusinessProposal, ProposalChangeLog, ProposalSection
    from content.services.proposal_service import build_proposal_from_json
    from content.services.proposal_totals_service import (
        effective_total_for_proposal,
        resync_investment_from_modules,
    )

    proposal_data = manifest.get("proposal") or {}
    hosting = manifest.get("hosting") or {}
    selected_ids = list((manifest.get("modules") or {}).get("selected_additional") or [])
    quoted_total = decimal_value((manifest.get("pricing") or {}).get("quoted_total"))
    expected_email_intro = serializer.validated_data.get("email_intro", "")
    if quoted_total is None:
        raise ProposalArtifactError("pricing.quoted_total no es numérico.")

    with transaction.atomic():
        proposal, unmapped_keys = build_proposal_from_json(serializer.validated_data)
        proposal.status = BusinessProposal.Status.DRAFT
        proposal.automations_paused = True
        proposal.selected_modules = [f"module-{module_id}" for module_id in selected_ids]
        proposal.hosting_percent = int(decimal_value(hosting.get("percent")) or 0)
        proposal.hosting_discount_nine_month = int(
            decimal_value(hosting.get("discount_nine_month")) or 0
        )
        proposal.hosting_discount_semiannual = int(
            decimal_value(hosting.get("discount_semiannual")) or 0
        )
        proposal.hosting_discount_quarterly = int(
            decimal_value(hosting.get("discount_quarterly")) or 0
        )
        proposal.save(
            update_fields=[
                "status",
                "automations_paused",
                "selected_modules",
                "hosting_percent",
                "hosting_discount_nine_month",
                "hosting_discount_semiannual",
                "hosting_discount_quarterly",
                "updated_at",
            ]
        )

        _apply_manifest_to_sections(proposal, manifest)
        ProposalChangeLog.objects.create(
            proposal=proposal,
            change_type=ProposalChangeLog.ChangeType.CALCULATOR_CONFIRMED,
            actor_type=ProposalChangeLog.ActorType.SELLER,
            new_value=json.dumps(proposal.selected_modules, ensure_ascii=False),
            description="Selección de módulos confirmada al crear el borrador con proposal-create.",
        )
        ProposalChangeLog.objects.create(
            proposal=proposal,
            change_type=ProposalChangeLog.ChangeType.CREATED,
            actor_type=ProposalChangeLog.ActorType.SELLER,
            description="Borrador creado desde un artefacto auditado por proposal-create.",
        )

        fr_section = proposal.sections.get(
            section_type=ProposalSection.SectionType.FUNCTIONAL_REQUIREMENTS
        )
        resync_investment_from_modules(proposal, fr_section.content_json)
        effective = effective_total_for_proposal(proposal)
        if effective != quoted_total.quantize(Decimal("0.01")):
            raise ProposalArtifactError(
                f"El total efectivo persistido sería {effective}, esperado {quoted_total}."
            )

        proposal.refresh_from_db()
        if proposal.status != BusinessProposal.Status.DRAFT:
            raise ProposalArtifactError("La propuesta no quedó en draft.")
        if not proposal.automations_paused:
            raise ProposalArtifactError("Las automatizaciones no quedaron pausadas.")
        if proposal.view_count != 0:
            raise ProposalArtifactError("El borrador registra vistas inesperadas.")
        if proposal.email_intro != expected_email_intro:
            raise ProposalArtifactError("El mensaje personalizado no quedó persistido.")

        actual_visibility = dict(
            proposal.sections.values_list("section_type", "is_enabled")
        )
        for section_type, expected in (manifest.get("section_visibility") or {}).items():
            if actual_visibility.get(section_type) is not expected:
                raise ProposalArtifactError(
                    f"La visibilidad de {section_type} no quedó aplicada."
                )

        admin_base = str(getattr(settings, "FRONTEND_BASE_URL", "")).rstrip("/")
        admin_url = f"{admin_base}/panel/proposals/{proposal.id}/edit"
        return {
            "id": proposal.id,
            "uuid": str(proposal.uuid),
            "slug": proposal.slug,
            "status": proposal.status,
            "automations_paused": proposal.automations_paused,
            "selected_modules": proposal.selected_modules,
            "base_investment": str(proposal.total_investment),
            "effective_total": str(effective),
            "currency": proposal.currency,
            "email_intro": proposal.email_intro,
            "admin_url": admin_url,
            "unmapped_keys": unmapped_keys,
            "client": proposal_data.get("client_name"),
        }


def run(args: argparse.Namespace) -> int:
    require_apply_confirmation(args.apply, args.confirm)
    settings = bootstrap_django(args.settings)
    artifact = load_json(args.artifact)
    manifest = load_json(args.manifest)
    language = (manifest.get("proposal") or {}).get("language", "es")
    template, _ = live_template(language)

    result = audit_artifact(artifact, manifest, template)
    live_validation(artifact, manifest, settings, result)
    print_audit(result)
    if not result.passed:
        return 1

    candidates = duplicate_candidates(manifest)
    if candidates and not args.allow_duplicate:
        print("DUPLICATE_CANDIDATE " + json.dumps(candidates, ensure_ascii=False, default=str))
        return 3

    serializer = validated_serializer(artifact, manifest)
    summary = {
        "environment": actual_environment(settings),
        "client": (manifest.get("proposal") or {}).get("client_name"),
        "title": (manifest.get("proposal") or {}).get("title"),
        "effective_total": (manifest.get("pricing") or {}).get("quoted_total"),
        "currency": (manifest.get("proposal") or {}).get("currency"),
        "email_intro": (
            (artifact.get("_meta") or {}).get("optional_metadata") or {}
        ).get("email_intro", ""),
        "duplicate_override": bool(candidates),
    }

    if not args.apply:
        print("DRY_RUN_PASS " + json.dumps(summary, ensure_ascii=False, default=str))
        return 0
    created = create_draft(serializer, manifest)
    print("DRAFT_CREATED " + json.dumps(created, ensure_ascii=False, default=str))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact")
    parser.add_argument("manifest")
    parser.add_argument("--settings", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--allow-duplicate", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except ProposalArtifactError as exc:
        print(f"CREATE_ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # Keep CLI output compact; Django logs retain traceback.
        print(f"CREATE_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
