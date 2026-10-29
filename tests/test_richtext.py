"""Unit tests for richtext: markdown answer parsing, flattening, highlighting, inline HTML."""
import pytest

from richtext import (
    BULLETS,
    CODE,
    TEXT,
    _clase,
    inline_html,
    parse_answer,
    resaltar,
    solo_texto,
)


# --- parse_answer -------------------------------------------------------------

def test_parse_answer_empty_input_returns_no_sections():
    # Arrange / Act
    secciones = parse_answer("")

    # Assert
    assert secciones == []


def test_parse_answer_blank_lines_only_returns_no_sections():
    # Arrange / Act
    secciones = parse_answer("\n   \n\n")

    # Assert
    assert secciones == []


def test_parse_answer_text_without_header_uses_default_label():
    # Arrange / Act
    secciones = parse_answer("Hello world")

    # Assert
    assert secciones == [("Answer", [(TEXT, "Hello world")])]


def test_parse_answer_consecutive_lines_join_into_one_paragraph():
    # Arrange / Act
    secciones = parse_answer("  line one  \nline two")

    # Assert
    assert secciones == [("Answer", [(TEXT, "line one line two")])]


def test_parse_answer_blank_line_separates_paragraphs():
    # Arrange / Act
    secciones = parse_answer("one\n\ntwo")

    # Assert
    assert secciones == [("Answer", [(TEXT, "one"), (TEXT, "two")])]


def test_parse_answer_splits_sections_on_headers():
    # Arrange
    raw = "## Summary\nHi\n## Details\nMore"

    # Act
    secciones = parse_answer(raw)

    # Assert
    assert secciones == [
        ("Summary", [(TEXT, "Hi")]),
        ("Details", [(TEXT, "More")]),
    ]


def test_parse_answer_text_before_first_header_gets_default_label():
    # Arrange
    raw = "intro\n## Next\nbody"

    # Act
    secciones = parse_answer(raw)

    # Assert
    assert secciones == [
        ("Answer", [(TEXT, "intro")]),
        ("Next", [(TEXT, "body")]),
    ]


@pytest.mark.parametrize(
    ("raw", "etiqueta"),
    [
        ("### Sub\nx", "Sub"),
        ("## Closed ##\nx", "Closed"),
        ("  ##   Spaced label   \nx", "Spaced label"),
    ],
)
def test_parse_answer_header_label_is_trimmed(raw, etiqueta):
    # Arrange / Act
    secciones = parse_answer(raw)

    # Assert
    assert secciones == [(etiqueta, [(TEXT, "x")])]


def test_parse_answer_single_hash_line_is_plain_text():
    # Arrange / Act
    secciones = parse_answer("# Title")

    # Assert
    assert secciones == [("Answer", [(TEXT, "# Title")])]


def test_parse_answer_header_without_content_is_dropped():
    # Arrange
    raw = "## Empty\n## Full\ntext"

    # Act
    secciones = parse_answer(raw)

    # Assert
    assert secciones == [("Full", [(TEXT, "text")])]


def test_parse_answer_collects_all_bullet_markers_into_one_list():
    # Arrange
    raw = "- a\n* b\n• c\n1. d\n2) e"

    # Act
    secciones = parse_answer(raw)

    # Assert
    assert secciones == [("Answer", [(BULLETS, ["a", "b", "c", "d", "e"])])]


def test_parse_answer_paragraph_before_bullets_is_closed():
    # Arrange
    raw = "Intro\n- a\n- b"

    # Act
    secciones = parse_answer(raw)

    # Assert
    assert secciones == [("Answer", [(TEXT, "Intro"), (BULLETS, ["a", "b"])])]


def test_parse_answer_text_line_after_bullets_starts_new_paragraph():
    # Arrange
    raw = "- a\nafter"

    # Act
    secciones = parse_answer(raw)

    # Assert
    assert secciones == [("Answer", [(BULLETS, ["a"]), (TEXT, "after")])]


def test_parse_answer_blank_line_separates_bullet_lists():
    # Arrange
    raw = "- a\n\n- b"

    # Act
    secciones = parse_answer(raw)

    # Assert
    assert secciones == [("Answer", [(BULLETS, ["a"]), (BULLETS, ["b"])])]


def test_parse_answer_bold_line_is_not_a_bullet():
    # Arrange / Act
    secciones = parse_answer("**Note** this")

    # Assert
    assert secciones == [("Answer", [(TEXT, "**Note** this")])]


def test_parse_answer_fenced_code_preserves_indentation():
    # Arrange
    raw = "```python\ndef f():\n    return 1\n```"

    # Act
    secciones = parse_answer(raw)

    # Assert
    assert secciones == [("Answer", [(CODE, "python", "def f():\n    return 1")])]


def test_parse_answer_fence_language_is_lowercased():
    # Arrange / Act
    secciones = parse_answer("```Python\nx\n```")

    # Assert
    assert secciones == [("Answer", [(CODE, "python", "x")])]


def test_parse_answer_tilde_fence_without_language_is_code():
    # Arrange / Act
    secciones = parse_answer("~~~\ncode\n~~~")

    # Assert
    assert secciones == [("Answer", [(CODE, "", "code")])]


def test_parse_answer_does_not_interpret_markdown_inside_code():
    # Arrange
    raw = "```\n## not header\n- not bullet\n\n```"

    # Act
    secciones = parse_answer(raw)

    # Assert
    assert secciones == [("Answer", [(CODE, "", "## not header\n- not bullet\n")])]


def test_parse_answer_code_splits_surrounding_paragraphs():
    # Arrange
    raw = "Intro\n```\nx\n```\nOutro"

    # Act
    secciones = parse_answer(raw)

    # Assert
    assert secciones == [("Answer", [(TEXT, "Intro"), (CODE, "", "x"), (TEXT, "Outro")])]


def test_parse_answer_code_closes_pending_bullets():
    # Arrange
    raw = "- a\n```sh\nls\n```"

    # Act
    secciones = parse_answer(raw)

    # Assert
    assert secciones == [("Answer", [(BULLETS, ["a"]), (CODE, "sh", "ls")])]


def test_parse_answer_unterminated_fence_keeps_partial_code():
    # Arrange
    raw = "## Code\n```js\nconst a = 1;\nconst b = 2;"

    # Act
    secciones = parse_answer(raw)

    # Assert
    assert secciones == [("Code", [(CODE, "js", "const a = 1;\nconst b = 2;")])]


def test_parse_answer_unterminated_fence_without_body_yields_empty_code():
    # Arrange / Act
    secciones = parse_answer("```py")

    # Assert
    assert secciones == [("Answer", [(CODE, "py", "")])]


# --- solo_texto ---------------------------------------------------------------

def test_solo_texto_empty_sections_return_empty_list():
    # Arrange / Act
    salida = solo_texto([])

    # Assert
    assert salida == []


def test_solo_texto_flattens_every_block_kind_with_spaces():
    # Arrange
    secciones = [("A", [(TEXT, "t"), (BULLETS, ["x", "y"]), (CODE, "py", "c = 1")])]

    # Act
    salida = solo_texto(secciones)

    # Assert
    assert salida == [("A", "t x y c = 1")]


def test_solo_texto_skips_empty_pieces():
    # Arrange
    secciones = [("A", [(TEXT, ""), (TEXT, "b")])]

    # Act
    salida = solo_texto(secciones)

    # Assert
    assert salida == [("A", "b")]


def test_solo_texto_drops_section_without_text():
    # Arrange
    secciones = [("A", [(CODE, "py", "")]), ("B", [(TEXT, "kept")])]

    # Act
    salida = solo_texto(secciones)

    # Assert
    assert salida == [("B", "kept")]


def test_solo_texto_accepts_parse_answer_output():
    # Arrange
    secciones = parse_answer("## S\nhi\n- a")

    # Act
    salida = solo_texto(secciones)

    # Assert
    assert salida == [("S", "hi a")]


# --- _clase (Pygments token type -> palette key) -----------------------------

@pytest.mark.parametrize(
    ("tipo", "clase"),
    [
        ("Token.Comment.Single", "com"),
        ("Token.Literal.String.Doc", "doc"),
        ("Token.Literal.String.Interpol", "esc"),
        ("Token.Literal.String.Escape", "esc"),
        ("Token.Literal.String.Affix", "esc"),
        ("Token.Literal.String.Double", "str"),
        ("Token.Literal.Number.Integer", "num"),
        ("Token.Name.Decorator", "dec"),
        ("Token.Keyword.Constant", "kwc"),
        ("Token.Operator.Word", "kwc"),
        ("Token.Keyword", "kw"),
        ("Token.Name.Builtin.Pseudo", "self"),
        ("Token.Name.Function", "def"),
        ("Token.Name.Class", "cls"),
        ("Token.Name.Exception", "cls"),
        ("Token.Name.Namespace", "cls"),
        ("Token.Name.Builtin", "bi"),
        ("Token.Punctuation", "pun"),
        ("Token.Operator", "op"),
        ("Token.Name", "txt"),
        ("Token.Text", "txt"),
    ],
)
def test_clase_maps_token_type_to_palette_key(tipo, clase):
    # Arrange / Act
    resultado = _clase(tipo)

    # Assert
    assert resultado == clase


# --- resaltar -----------------------------------------------------------------

def test_resaltar_colours_python_tokens():
    # Arrange
    codigo = "x = 1"

    # Act
    salida = resaltar(codigo, "python")

    # Assert
    assert salida == (
        '<span style="color:#efe7d5;">x</span>'
        '<span style="color:#efe7d5;">&nbsp;</span>'
        '<span style="color:#e2d9c2;">=</span>'
        '<span style="color:#efe7d5;">&nbsp;</span>'
        '<span style="color:#f2a06a;">1</span>'
    )


def test_resaltar_comment_is_italic():
    # Arrange / Act
    salida = resaltar("# hi", "python")

    # Assert
    assert salida == '<span style="color:#7f7a6c;font-style:italic;">#&nbsp;hi</span>'


def test_resaltar_escapes_html_in_code():
    # Arrange / Act
    salida = resaltar("a < b", "python")

    # Assert
    assert salida == (
        '<span style="color:#efe7d5;">a</span>'
        '<span style="color:#efe7d5;">&nbsp;</span>'
        '<span style="color:#e2d9c2;">&lt;</span>'
        '<span style="color:#efe7d5;">&nbsp;</span>'
        '<span style="color:#efe7d5;">b</span>'
    )


def test_resaltar_splits_multiline_token_across_lines():
    # Arrange
    codigo = '"""a\nb"""'

    # Act
    salida = resaltar(codigo, "python")

    # Assert
    assert salida == (
        '<span style="color:#84a877;font-style:italic;">&quot;&quot;&quot;a</span>'
        "<br>"
        '<span style="color:#84a877;font-style:italic;">b&quot;&quot;&quot;</span>'
    )


def test_resaltar_with_line_numbers_prefixes_number():
    # Arrange
    codigo = "x = 1"

    # Act
    salida = resaltar(codigo, "python", numerar=True)

    # Assert
    assert salida == (
        '<span style="color:#5c564a;">1&nbsp;&nbsp;&nbsp;</span>'
        '<span style="color:#efe7d5;">x</span>'
        '<span style="color:#efe7d5;">&nbsp;</span>'
        '<span style="color:#e2d9c2;">=</span>'
        '<span style="color:#efe7d5;">&nbsp;</span>'
        '<span style="color:#f2a06a;">1</span>'
    )


def test_resaltar_line_numbers_are_right_aligned_to_widest():
    # Arrange
    codigo = "a\nb\nc\nd\ne\nf\ng\nh\ni\nj"

    # Act
    primera = resaltar(codigo, "text", numerar=True).split("<br>")[0]

    # Assert
    assert primera == (
        '<span style="color:#5c564a;">&nbsp;1&nbsp;&nbsp;&nbsp;</span>'
        '<span style="color:#efe7d5;">a</span>'
    )


def test_resaltar_widest_line_number_has_no_padding():
    # Arrange
    codigo = "a\nb\nc\nd\ne\nf\ng\nh\ni\nj"

    # Act
    ultima = resaltar(codigo, "text", numerar=True).split("<br>")[-1]

    # Assert
    assert ultima == (
        '<span style="color:#5c564a;">10&nbsp;&nbsp;&nbsp;</span>'
        '<span style="color:#efe7d5;">j</span>'
    )


@pytest.mark.parametrize("lenguaje", ["", "no-such-language-zzz"])
def test_resaltar_guesses_lexer_when_language_missing_or_unknown(lenguaje):
    # Arrange
    codigo = "x = 1"

    # Act
    salida = resaltar(codigo, lenguaje)

    # Assert
    assert salida == '<span style="color:#efe7d5;">x&nbsp;=&nbsp;1</span>'


@pytest.mark.parametrize("codigo", ["", "\n\n"])
def test_resaltar_returns_none_for_empty_code(codigo):
    # Arrange / Act
    salida = resaltar(codigo, "python")

    # Assert
    assert salida is None


@pytest.mark.parametrize("lenguaje", ["python", "no-such-language-zzz"])
def test_resaltar_returns_none_when_code_cannot_be_lexed(lenguaje):
    # Arrange / Act
    salida = resaltar(None, lenguaje)

    # Assert
    assert salida is None


# --- inline_html --------------------------------------------------------------

def test_inline_html_plain_text_is_unchanged():
    # Arrange / Act
    salida = inline_html("hello world")

    # Assert
    assert salida == "hello world"


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("<script>alert(1)</script>", "&lt;script&gt;alert(1)&lt;/script&gt;"),
        ("a & b", "a &amp; b"),
        ("\"x\" 'y'", "&quot;x&quot; &#x27;y&#x27;"),
        ("<b>not bold</b>", "&lt;b&gt;not bold&lt;/b&gt;"),
    ],
)
def test_inline_html_escapes_html_special_characters(texto, esperado):
    # Arrange / Act
    salida = inline_html(texto)

    # Assert
    assert salida == esperado


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("**bold** text", "<b>bold</b> text"),
        ("__bold__ text", "<b>bold</b> text"),
    ],
)
def test_inline_html_renders_bold(texto, esperado):
    # Arrange / Act
    salida = inline_html(texto)

    # Assert
    assert salida == esperado


def test_inline_html_renders_italic():
    # Arrange / Act
    salida = inline_html("an *italic* word")

    # Assert
    assert salida == "an <i>italic</i> word"


def test_inline_html_ignores_intraword_asterisks():
    # Arrange / Act
    salida = inline_html("a*b*c")

    # Assert
    assert salida == "a*b*c"


def test_inline_html_does_not_bold_across_lines():
    # Arrange / Act
    salida = inline_html("**a\nb**")

    # Assert
    assert salida == "**a\nb**"


def test_inline_html_wraps_inline_code_with_style():
    # Arrange / Act
    salida = inline_html("run `make`", code_style="color:red;")

    # Assert
    assert salida == 'run <span style="color:red;">make</span>'


def test_inline_html_inline_code_default_style_is_empty():
    # Arrange / Act
    salida = inline_html("`make`")

    # Assert
    assert salida == '<span style="">make</span>'


def test_inline_html_escapes_markup_inside_inline_code():
    # Arrange / Act
    salida = inline_html("`<div>&</div>`")

    # Assert
    assert salida == '<span style="">&lt;div&gt;&amp;&lt;/div&gt;</span>'


def test_inline_html_escapes_markup_inside_bold():
    # Arrange / Act
    salida = inline_html("**<i>**")

    # Assert
    assert salida == "<b>&lt;i&gt;</b>"


def test_inline_html_keeps_lone_power_operator_inside_code():
    """Docstring example: '**' inside `a ** b` must not become bold."""
    # Arrange / Act
    salida = inline_html("`a ** b`")

    # Assert
    assert salida == '<span style="">a ** b</span>'


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("`__init__`", '<span style="">__init__</span>'),
        ("`x ** 2` and **bold**", '<span style="">x ** 2</span> and <b>bold</b>'),
        ("`* x *`", '<span style="">* x *</span>'),
    ],
)
def test_inline_html_does_not_format_inside_inline_code(texto, esperado):
    # Arrange / Act
    salida = inline_html(texto)

    # Assert
    assert salida == esperado


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("**use `x` here**", '<b>use <span style="">x</span> here</b>'),
        ("*see `y`*", '<i>see <span style="">y</span></i>'),
        ("`a` and `b`", '<span style="">a</span> and <span style="">b</span>'),
        ("Override `__init__` and `**kwargs`",
         'Override <span style="">__init__</span> and <span style="">**kwargs</span>'),
        ("`<script>`", '<span style="">&lt;script&gt;</span>'),
        ("raw \x00 0 \x00 byte", "raw  0  byte"),
    ],
)
def test_inline_html_emphasis_around_inline_code(texto, esperado):
    assert inline_html(texto) == esperado
