"""Meeting notes: what is sent and when there is something to summarise."""
import sys
from types import SimpleNamespace

import notas


def test_only_spoken_lines_are_summarised():
    registro = [("Ellos", " ¿Plazos? "), ("Sugerido", "Dos semanas"), ("Agente", "cambio"),
                ("Yo", "Dos semanas"), ("Ellos", "  ")]

    assert notas.transcripcion(registro) == "Ellos: ¿Plazos?\nYo: Dos semanas"


def test_one_line_is_not_a_meeting():
    assert notas.hay_que_resumir([("Ellos", "hola"), ("Sugerido", "x")]) is False
    assert notas.hay_que_resumir([("Ellos", "hola"), ("Yo", "hola")]) is True


def test_long_meetings_keep_the_end():
    registro = [("Ellos", "x" * 1000)] * 200

    assert len(notas.transcripcion(registro)) == notas.MAX_CARACTERES


def test_notes_request(monkeypatch):
    llamadas = []

    class Cliente:
        def __init__(self, **kw):
            self.responses = SimpleNamespace(create=lambda **kw: (
                llamadas.append(kw) or SimpleNamespace(output_text="## Resumen\nOk")))

    monkeypatch.setitem(sys.modules, "openai",
                        SimpleNamespace(OpenAI=Cliente, Timeout=lambda *a, **k: None))

    texto = notas.generar("k", "gpt-6.1-sol", [("Ellos", "a"), ("Yo", "b")])

    assert texto == "## Resumen\nOk"
    assert llamadas[0]["input"][1]["content"][0]["text"] == "Ellos: a\nYo: b"
    assert llamadas[0]["reasoning"] == {"effort": "low"}
