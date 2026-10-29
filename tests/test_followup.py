"""Follow-up arbiter: decision policy, Jev request shape and eval scoring.

No TypeSafe call is made: a fake client returns canned answers.
"""
from types import SimpleNamespace

import pytest

import followup
from followup import MANTENER, NUEVA, RETIRAR, REVISAR, Juicio, Umbrales, decidir
from stt_eval import followup_eval


def _juicio(relacion, cambia=0.0, p=0.9, **otras):
    probs = {relacion: p, **otras}
    return Juicio(relacion, p, probs, cambia, 0.0)


LEYENDO, CONTESTANDO, CONTESTADA = "preguntada", "respondiendo", "respondida"


@pytest.mark.parametrize("relacion,cambia,esperado", [
    ("filler_or_ack", 0.9, MANTENER),
    ("unrelated", 0.9, MANTENER),
    ("extends_question", 0.8, REVISAR),
    ("extends_question", 0.2, MANTENER),
    ("relaxes_or_answers", 0.75, REVISAR),
    ("relaxes_or_answers", 0.1, MANTENER),
    ("new_question", 0.0, NUEVA),
    ("drills_into_part", 0.0, NUEVA),
    ("withdraws_question", 0.0, RETIRAR),
])
def test_decidir_while_tester_reads(relacion, cambia, esperado):
    assert decidir(_juicio(relacion, cambia), LEYENDO) == esperado


@pytest.mark.parametrize("estado", [CONTESTANDO, CONTESTADA])
def test_once_answering_the_answer_is_never_rewritten(estado):
    assert decidir(_juicio("extends_question", 0.99), estado) == MANTENER
    assert decidir(_juicio("relaxes_or_answers", 0.99), estado) == MANTENER
    assert decidir(_juicio("drills_into_part"), estado) == NUEVA
    assert decidir(_juicio("new_question"), estado) == NUEVA


def test_split_between_extends_and_relaxes_still_rewrites():
    # Jev hesitates between the two relations that lead to the same action.
    j = _juicio("extends_question", 0.9, p=0.45, relaxes_or_answers=0.42)
    assert decidir(j, LEYENDO) == REVISAR


def test_decidir_keeps_when_unsure_or_failed():
    assert decidir(_juicio("new_question", p=0.4, filler_or_ack=0.35), LEYENDO) == MANTENER
    assert decidir(None, LEYENDO) == MANTENER


def test_decidir_threshold_is_configurable():
    j = _juicio("extends_question", cambia=0.5)
    assert decidir(j, LEYENDO) == MANTENER
    assert decidir(j, LEYENDO, Umbrales(cambio=0.4)) == REVISAR


def test_estado_marks_missing_answer_and_silence():
    st = followup.construir_estado("¿Qué usarías?", "", [], "Y en AWS.")
    assert st["suggested_answer"] == "(still being generated)"
    assert st["interviewee_said_since"] == ["(nothing)"]
    assert st["follow_up"] == "Y en AWS."


def test_preguntas_cover_every_relation_and_cite_state_fields():
    qs = followup.preguntas()
    assert set(qs["relation"].criteria) == set(followup.RELACIONES)
    for q in qs.values():
        assert "`follow_up`" in q.instructions


class FakeClient:
    def __init__(self, relation, confidence, changes, reacts=0.1):
        self.relation, self.confidence = relation, confidence
        self.changes, self.reacts = changes, reacts
        self.calls = []

    def system_one(self, state, questions):
        self.calls.append((state, questions))
        return SimpleNamespace(answers={
            "relation": SimpleNamespace(choice=self.relation, confidence=self.confidence,
                                        probabilities={self.relation: self.confidence}),
            "changes_answer": SimpleNamespace(noul=self.changes),
            "reacts_to_interviewee": SimpleNamespace(noul=self.reacts),
        })


def test_juzgar_sends_one_request_and_maps_answers():
    client = FakeClient("extends_question", 0.8, 0.9, reacts=0.2)
    j = followup.juzgar(client, "¿Qué usarías?", "Postgres", ["Vale."], "En AWS.")

    assert len(client.calls) == 1
    state, questions = client.calls[0]
    assert set(questions) == {"relation", "changes_answer", "reacts_to_interviewee"}
    assert state["interviewee_said_since"] == ["Vale."]
    assert (j.relacion, j.cambia, j.reacciona_tester) == ("extends_question", 0.9, 0.2)
    assert decidir(j) == REVISAR


def test_cases_file_is_consistent_with_policy_labels():
    cases = followup_eval.load_cases()
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids))
    actions = {MANTENER, REVISAR, NUEVA, RETIRAR}
    for c in cases:
        assert c["expected_relation"] in followup.RELACIONES, c["id"]
        assert c["expected_action"] in actions, c["id"]
        if c["expected_relation"] in ("filler_or_ack", "unrelated"):
            assert c["expected_action"] == MANTENER, c["id"]


def test_score_counts_costly_errors():
    cases = [
        {"id": "a", "question": "q", "suggested_answer": "s", "tester_said": [],
         "follow_up": "vale", "expected_relation": "filler_or_ack", "expected_action": "keep"},
        {"id": "b", "question": "q", "suggested_answer": "s", "tester_said": [],
         "follow_up": "y en AWS", "expected_relation": "extends_question", "expected_action": "revise"},
    ]
    # Jev says both extend the question and change the answer.
    results = followup_eval.judge_cases(FakeClient("extends_question", 0.9, 0.9), cases)
    report = followup_eval.score(results)

    assert report["relation_accuracy"] == 0.5
    assert report["revised_on_noise"] == ["a"]
    assert report["missed_revision"] == []
    assert report["action_confusion"] == {"keep->revise": 1, "revise->revise": 1}


def test_score_reports_failed_calls_as_keep():
    case = {"id": "x", "question": "q", "suggested_answer": "s", "tester_said": [],
            "follow_up": "f", "expected_relation": "new_question", "expected_action": "new"}

    def boom(*_a, **_k):
        raise TimeoutError("slow")

    report = followup_eval.score(followup_eval.judge_cases(None, [case], judge=boom))
    assert report["errors"][0]["id"] == "x"
    assert report["rows"][0]["action"] == MANTENER
