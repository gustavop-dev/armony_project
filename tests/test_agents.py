"""Agents: preset seeding, storage round trip, defaults and prompt assembly."""
import json
import os

import pytest

import agents
import config
from llm import REGLAS


def _files(isolated_data_dir):
    return sorted(os.listdir(isolated_data_dir / "agents"))


def test_first_listing_seeds_the_presets_in_order(isolated_data_dir):
    lista = agents.list_agents()

    assert [a["id"] for a in lista] == ["coach", "directo", "grok", "senior"]
    assert _files(isolated_data_dir) == ["coach.json", "directo.json", "grok.json",
                                         "senior.json"]


def test_coach_preset_is_todays_prompt_and_rules():
    coach = agents.preset("coach")

    assert coach["instrucciones"] == agents.prompt_bilingue(
        config.DEFAULT_PROMPT_ES, config.DEFAULT_PROMPT_EN)
    assert coach["reglas"] == REGLAS


def test_every_preset_ships_the_full_rules():
    assert all(agents.preset(pid)["reglas"] == REGLAS for pid in agents.PRESETS)


def test_bilingual_prompt_joins_both_languages():
    assert agents.prompt_bilingue(" ES ", " EN ") == (
        "ES\n\n---\n\n(The same instructions in English; follow whichever "
        "matches the language being spoken.)\n\nEN")


def test_bilingual_prompt_keeps_a_single_language():
    assert (agents.prompt_bilingue("ES", ""), agents.prompt_bilingue(None, "EN")) == (
        "ES", "EN")


def test_edits_survive_a_round_trip():
    lista = agents.list_agents()
    lista[2]["instrucciones"] = "Sé sarcástico."
    lista[2]["reglas"] = "Sin secciones."
    lista[2]["name"] = "Grok 2"

    agents.write_all(lista)

    grok = agents.get("grok")
    assert (grok["name"], grok["instrucciones"], grok["reglas"]) == (
        "Grok 2", "Sé sarcástico.", "Sin secciones.")


def test_removed_agent_file_is_deleted(isolated_data_dir):
    lista = agents.list_agents()

    agents.write_all([a for a in lista if a["id"] != "directo"])

    assert "directo.json" not in _files(isolated_data_dir)


def test_presets_come_back_when_no_agent_is_left(isolated_data_dir):
    agents.list_agents()
    agents.write_all([])

    assert [a["id"] for a in agents.list_agents()][0] == "coach"


def test_new_agent_starts_as_a_copy_of_the_coach():
    nuevo = agents.nuevo(agents.list_agents())
    coach = agents.preset("coach")

    assert (nuevo["id"], nuevo["name"], nuevo["preset"]) == (
        "agente-1", "Nuevo agente", "coach")
    assert (nuevo["instrucciones"], nuevo["reglas"]) == (
        coach["instrucciones"], coach["reglas"])


def test_new_ids_keep_counting():
    existentes = [{"id": "agente-1"}, {"id": "agente-4"}, {"id": "grok"}]

    assert agents.next_id(existentes) == "agente-5"


def test_custom_agents_are_listed_after_the_presets():
    lista = agents.list_agents()
    lista.insert(0, agents.nuevo(lista, "Mío"))
    agents.write_all(lista)

    assert [a["id"] for a in agents.list_agents()][-1] == "agente-1"


def test_restore_goes_back_to_the_agent_preset():
    copia = dict(agents.preset("grok"), id="agente-1", instrucciones="otra cosa")

    assert agents.predeterminado(copia)["instrucciones"] == agents.preset("grok")["instrucciones"]


def test_unknown_preset_restores_to_the_coach():
    assert agents.predeterminado({"preset": "nope"})["id"] == "coach"


def test_unknown_agent_falls_back_to_the_first():
    assert agents.get("borrado")["id"] == "coach"


def test_unreadable_agent_file_is_skipped(isolated_data_dir):
    agents.list_agents()
    (isolated_data_dir / "agents" / "roto.json").write_text("{no json", encoding="utf-8")

    assert "roto" not in [a["id"] for a in agents.list_agents()]


def test_missing_fields_take_the_preset_text(isolated_data_dir):
    agents.list_agents()
    (isolated_data_dir / "agents" / "agente-1.json").write_text(
        json.dumps({"name": "Corto", "preset": "directo"}), encoding="utf-8")

    corto = agents.get("agente-1")
    assert corto["instrucciones"] == agents.preset("directo")["instrucciones"]


def test_system_prompt_adds_the_agent_knowledge():
    agente = {"instrucciones": " Sé breve. ", "conocimiento": [
        {"id": "doc-1", "name": "CV", "body": " Backend 6 años "},
        {"id": "doc-2", "name": "Vacío", "body": "  "},
        {"id": "doc-3", "name": "Oferta", "body": "Fintech"}]}

    assert agents.system_prompt(agente) == (
        "Sé breve.\n\n# Contexto de esta reunion\nBackend 6 años\n\nFintech")


def test_system_prompt_without_context_is_just_the_instructions():
    assert agents.system_prompt({"instrucciones": "Sé breve."}) == "Sé breve."


def test_tone_goes_between_instructions_and_knowledge():
    agente = {"instrucciones": "Sé breve.", "tono": "Dice «la verdad es que».",
              "conocimiento": [{"id": "doc-1", "name": "CV", "body": "Backend"}]}

    texto = agents.system_prompt(agente)

    assert texto.index("Sé breve.") < texto.index("# Tono y estilo") < texto.index(
        "«la verdad es que»") < texto.index("# Contexto de esta reunion")


def test_empty_tone_adds_nothing():
    assert "Tono" not in agents.system_prompt({"instrucciones": "Sé breve.", "tono": " "})


def test_tone_survives_a_round_trip():
    lista = agents.list_agents()
    lista[0]["tono"] = "## Registro\nCercano"
    agents.write_all(lista)

    assert agents.get("coach")["tono"] == "## Registro\nCercano"


def test_presets_start_without_tone():
    assert all(agents.preset(pid)["tono"] == "" for pid in agents.PRESETS)


def test_presets_answer_automatically_with_screens_and_notes():
    coach = agents.preset("coach")

    assert (coach["modo"], coach["capturas"], coach["notas"]) == ("automatico", True, True)


def test_permissions_survive_a_round_trip():
    lista = agents.list_agents()
    lista[1].update(modo="manual", capturas=False, notas=False)
    agents.write_all(lista)

    d = agents.get("directo")
    assert (d["modo"], d["capturas"], d["notas"]) == ("manual", False, False)


def test_unknown_mode_falls_back_to_automatic(isolated_data_dir):
    import json
    agents.list_agents()
    (isolated_data_dir / "agents" / "agente-1.json").write_text(
        json.dumps({"name": "Raro", "modo": "telepatico"}), encoding="utf-8")

    assert agents.get("agente-1")["modo"] == "automatico"


@pytest.mark.parametrize("agente, capturas, notas", [
    ({"modo": "notetaker", "capturas": True, "notas": False}, False, True),
    ({"modo": "manual", "capturas": False, "notas": False}, False, False),
    ({"modo": "automatico", "capturas": True, "notas": True}, True, True),
])
def test_notetaker_has_no_screens_and_always_notes(agente, capturas, notas):
    assert (agents.usa_capturas(agente), agents.toma_notas(agente)) == (capturas, notas)


def test_every_preset_has_its_own_face():
    caras = [(agents.preset(p)["personaje"], agents.preset(p)["color"]) for p in agents.PRESETS]

    assert len(set(caras)) == len(caras)


def test_new_agents_rotate_faces():
    lista = agents.list_agents()
    uno = agents.nuevo(lista)
    dos = agents.nuevo(lista + [uno])

    assert (uno["personaje"], uno["color"]) != (dos["personaje"], dos["color"])


def test_face_survives_a_round_trip():
    lista = agents.list_agents()
    lista[0].update(personaje="oso", color="lavanda")
    agents.write_all(lista)

    c = agents.get("coach")
    assert (c["personaje"], c["color"]) == ("oso", "lavanda")
