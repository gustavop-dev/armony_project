"""Answers painted like ChatGPT / Claude: the prompt block, lists with
numbers, tables, quotes and subheadings. Offscreen Qt."""
import pytest
from PySide6 import QtCore, QtWidgets

import overlay_ui

ANSWER = """## Qué hay que construir
1. Depósito de garantía
   - con webhook firmado
2. Activación
### Riesgos
| Riesgo | Mitigación |
|---|---|
| Doble cobro | Idempotency-Key |
> Ojo con la concurrencia
---
## Prompt inicial
````markdown
# Contexto
- **Stack**: Django
```python
x = 1
```
````
"""


@pytest.fixture
def panel(qtbot):
    p = overlay_ui.TranscriptPanel(modo="pantalla")
    qtbot.addWidget(p)
    p.resize(640, 900)
    p.clear_answer()
    p.append_answer(ANSWER)
    p.cerrar_respuesta()
    yield p
    qtbot.wait(5)


def labels(widget):
    return [lab.text() for lab in widget.findChildren(QtWidgets.QLabel)]


def test_prompt_block_is_labelled_and_copies_the_raw_prompt(panel, qtbot):
    bloque, = panel.findChildren(overlay_ui.CodeBlock)

    assert bloque.es_prompt is True
    assert bloque.findChild(QtWidgets.QLabel, "lenguaje").text() == "PROMPT"
    assert bloque.lbl_copy.text() == "Copy prompt"
    qtbot.mouseClick(bloque.btn_copy, QtCore.Qt.LeftButton)
    assert QtWidgets.QApplication.clipboard().text() == (
        "# Contexto\n- **Stack**: Django\n```python\nx = 1\n```")


def test_prompt_is_coloured_markdown_without_line_numbers(panel):
    bloque, = panel.findChildren(overlay_ui.CodeBlock)
    texto = bloque.cuerpo.text()

    assert "# Contexto</b>" in texto and "**Stack**</b>" in texto
    assert overlay_ui.richtext.COLOR_NUMERO not in texto


def test_code_blocks_outside_the_prompt_keep_their_language(qtbot):
    bloque = overlay_ui.CodeBlock("python", "x = 1", titulo="Solución")
    qtbot.addWidget(bloque)

    assert bloque.es_prompt is False and bloque.prosa is False
    assert bloque.findChild(QtWidgets.QLabel, "lenguaje").text() == "PYTHON"
    assert bloque.lbl_copy.text() == "Copy"


def test_markdown_block_outside_a_prompt_section_is_not_called_a_prompt(qtbot):
    bloque = overlay_ui.CodeBlock("markdown", "# README", titulo="Ejemplo")
    qtbot.addWidget(bloque)

    assert bloque.prosa is True and bloque.es_prompt is False
    assert bloque.findChild(QtWidgets.QLabel, "lenguaje").text() == "MARKDOWN"


def test_numbered_list_keeps_numbers_and_nesting(panel):
    lista = next(t for t in labels(panel) if "Depósito de garantía" in t)

    assert ">1.</td>" in lista and ">2.</td>" in lista
    # The nested point sits in the text column, under its parent's text.
    assert '<tr><td></td><td style="padding-left:0px;">' in lista and "◦</span>" in lista


def test_table_has_header_and_rows(panel):
    tabla = next(t for t in labels(panel) if "Idempotency-Key" in t)

    assert "<th" in tabla and ">Riesgo</th>" in tabla and ">Doble cobro</td>" in tabla


def test_subheading_quote_and_rule_are_drawn(panel):
    textos = labels(panel)

    assert any("Riesgos" in t and "font-weight:600" in t for t in textos)
    cita = next(lab for lab in panel.findChildren(QtWidgets.QLabel)
                if "Ojo con la concurrencia" in lab.text())
    assert "border-left: 3px" in cita.styleSheet()


def test_new_blocks_can_be_selected_to_ask_about_them(panel):
    tabla = next(lab for lab in panel.findChildren(QtWidgets.QLabel)
                 if "Idempotency-Key" in lab.text())

    assert tabla.textInteractionFlags() & QtCore.Qt.TextSelectableByMouse
