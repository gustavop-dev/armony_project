"""Unit tests for intent.parece_pregunta (first gate: does an utterance ask for a reply)."""
import pytest

from intent import parece_pregunta


@pytest.mark.parametrize("texto", ["", "   ", "\n\t ", None])
def test_empty_or_blank_input_is_not_a_question(texto):
    # Arrange / Act
    resultado = parece_pregunta(texto, "es")

    # Assert
    assert resultado is False


@pytest.mark.parametrize("texto", ["...", "!!! ---", "¡¡ ¡¡"])
def test_input_without_words_is_not_a_question(texto):
    # Arrange / Act
    resultado = parece_pregunta(texto, "es")

    # Assert
    assert resultado is False


@pytest.mark.parametrize(
    "texto",
    [
        "vienes mañana?",
        "¿vienes mañana",
        "?",
        "el informe esta listo?",
    ],
)
def test_question_mark_makes_it_a_question(texto):
    # Arrange / Act
    resultado = parece_pregunta(texto, "es")

    # Assert
    assert resultado is True


@pytest.mark.parametrize("idioma", ["es", "en", "auto", "fr"])
def test_question_mark_counts_in_any_language_mode(idioma):
    # Arrange
    texto = "the report is ready?"

    # Act
    resultado = parece_pregunta(texto, idioma)

    # Assert
    assert resultado is True


@pytest.mark.parametrize(
    "texto",
    [
        "como lo ves",
        "y cuando entregamos",
        "quien lleva esto",
        "entonces cuantos usuarios hay",
        "y entonces ahora cuando entregamos",
    ],
)
def test_spanish_interrogative_within_first_four_words_is_a_question(texto):
    # Arrange / Act
    resultado = parece_pregunta(texto, "es")

    # Assert
    assert resultado is True


@pytest.mark.parametrize(
    "texto",
    [
        "y entonces ahora ya cuando entregamos",
        "ayer hable con ellos sobre cuando entregamos",
    ],
)
def test_spanish_interrogative_after_fourth_word_is_not_a_question(texto):
    # Arrange / Act
    resultado = parece_pregunta(texto, "es")

    # Assert
    assert resultado is False


@pytest.mark.parametrize(
    "texto",
    ["cómo lo ves", "cuál es el plan", "dónde está el fichero", "cuántas personas vienen"],
)
def test_interrogative_matching_ignores_accents(texto):
    # Arrange / Act
    resultado = parece_pregunta(texto, "es")

    # Assert
    assert resultado is True


@pytest.mark.parametrize("texto", ["COMO lo ves", "Cuando entregamos", "CUÁL es el plan"])
def test_interrogative_matching_ignores_case(texto):
    # Arrange / Act
    resultado = parece_pregunta(texto, "es")

    # Assert
    assert resultado is True


def test_porque_explanation_is_not_a_question():
    """'porque' (joined) explains; it must not be treated as an interrogative."""
    # Arrange
    texto = "porque el cliente cambio el alcance"

    # Act
    resultado = parece_pregunta(texto, "es")

    # Assert
    assert resultado is False


def test_separated_por_que_is_a_question():
    # Arrange
    texto = "por que no funciona el despliegue"

    # Act
    resultado = parece_pregunta(texto, "es")

    # Assert
    assert resultado is True


@pytest.mark.xfail(
    strict=True,
    reason="[KNOWN-101] mid-sentence interrogative inside the first 4 words is "
    "flagged as a question, contradicting the module's own examples",
)
@pytest.mark.parametrize("texto", ["no se que hacer", "lo que sea"])
def test_mid_sentence_interrogative_is_not_a_question(texto):
    """The module comment names these exact phrases as non-questions."""
    # Arrange / Act
    resultado = parece_pregunta(texto, "es")

    # Assert
    assert resultado is False


@pytest.mark.parametrize(
    "texto",
    [
        "cuentame un poco de ti",
        "Explícame el diseño de la base de datos",
        "enséñame el código",
        "me gustaría saber el plazo",
        "tienes la palabra",
        "puede usted repetirlo",
        "necesito que revises el informe",
    ],
)
def test_spanish_request_phrase_is_a_question(texto):
    # Arrange / Act
    resultado = parece_pregunta(texto, "es")

    # Assert
    assert resultado is True


@pytest.mark.parametrize(
    "texto",
    [
        "tell me about yourself",
        "Walk me through the design",
        "I'd like to know the budget",
        "let me know your thoughts",
        "go ahead",
        "could you send the slides",
    ],
)
def test_english_request_phrase_is_a_question(texto):
    # Arrange / Act
    resultado = parece_pregunta(texto, "en")

    # Assert
    assert resultado is True


@pytest.mark.parametrize(
    "texto",
    ["how does this work", "Why not now", "which one goes first", "so where are we"],
)
def test_english_interrogative_within_first_four_words_is_a_question(texto):
    # Arrange / Act
    resultado = parece_pregunta(texto, "en")

    # Assert
    assert resultado is True


@pytest.mark.parametrize(
    ("texto", "idioma"),
    [
        ("el informe esta listo", "es"),
        ("the report is ready", "en"),
        ("el informe esta listo", "auto"),
        ("the report is ready", "auto"),
    ],
)
def test_plain_statement_is_not_a_question(texto, idioma):
    # Arrange / Act
    resultado = parece_pregunta(texto, idioma)

    # Assert
    assert resultado is False


@pytest.mark.parametrize(
    "texto", ["tell me about yourself", "how does this work"]
)
def test_spanish_mode_ignores_english_vocabulary(texto):
    # Arrange / Act
    resultado = parece_pregunta(texto, "es")

    # Assert
    assert resultado is False


@pytest.mark.parametrize("texto", ["cuentame un poco de ti", "como lo ves"])
def test_english_mode_ignores_spanish_vocabulary(texto):
    # Arrange / Act
    resultado = parece_pregunta(texto, "en")

    # Assert
    assert resultado is False


@pytest.mark.parametrize(
    "texto",
    [
        "tell me about yourself",
        "how does this work",
        "cuentame un poco de ti",
        "como lo ves",
    ],
)
def test_auto_mode_uses_both_vocabularies(texto):
    # Arrange / Act
    resultado = parece_pregunta(texto, "auto")

    # Assert
    assert resultado is True


def test_default_language_is_spanish():
    # Arrange
    texto = "how does this work"

    # Act
    resultado = parece_pregunta(texto)

    # Assert
    assert resultado is False


@pytest.mark.parametrize("idioma", ["fr", "", None])
def test_unknown_language_lets_any_worded_text_through(idioma):
    # Arrange
    texto = "el informe esta listo"

    # Act
    resultado = parece_pregunta(texto, idioma)

    # Assert
    assert resultado is True


def test_unknown_language_still_rejects_text_without_words():
    # Arrange
    texto = "!!!"

    # Act
    resultado = parece_pregunta(texto, "fr")

    # Assert
    assert resultado is False


def test_english_interrogative_with_typographic_apostrophe_is_a_question():
    # Arrange
    texto = "what’s the plan"

    # Act
    resultado = parece_pregunta(texto, "en")

    # Assert
    assert resultado is True


@pytest.mark.xfail(
    strict=True,
    reason="[KNOWN-102] English contractions with an ASCII apostrophe "
    "(what's, how's) are not recognised as interrogatives",
)
@pytest.mark.parametrize("texto", ["what's the plan", "how's it going", "where's the file"])
def test_english_contracted_interrogative_is_a_question(texto):
    """Transcripts often drop '?'; the gate must err on letting questions through."""
    # Arrange / Act
    resultado = parece_pregunta(texto, "en")

    # Assert
    assert resultado is True
