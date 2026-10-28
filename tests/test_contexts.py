"""Unit tests for contexts: markdown context files with a small frontmatter.

The autouse ``isolated_data_dir`` fixture points ``contexts.CONTEXTS_DIR`` at
``<tmp>/contexts``, so these tests never touch the repo's own contexts/ folder.
"""
import os

import pytest

import contexts


@pytest.fixture
def ctx_dir(isolated_data_dir):
    """The isolated contexts folder, created and empty."""
    path = isolated_data_dir / "contexts"
    path.mkdir()
    return path


def _write(ctx_dir, filename, text):
    (ctx_dir / filename).write_text(text, encoding="utf-8")


def _ids(items):
    return [c["id"] for c in items]


@pytest.fixture
def mixed_contexts(ctx_dir):
    """Five contexts covering every active/lang combination used by the filters."""
    _write(ctx_dir, "ctx-1.md", "---\nname: ES\nactive: true\nlang: es\n---\nbody-es")
    _write(ctx_dir, "ctx-2.md", "---\nname: EN\nactive: true\nlang: en\n---\nbody-en")
    _write(ctx_dir, "ctx-3.md",
           "---\nname: Both\nactive: true\nlang: both\n---\nbody-both")
    _write(ctx_dir, "ctx-4.md",
           "---\nname: Off\nactive: false\nlang: es\n---\nbody-off")
    _write(ctx_dir, "ctx-5.md", "---\nname: Empty\nactive: true\nlang: es\n---\n   ")
    return ctx_dir


# --- _serialize / _parse -----------------------------------------------------------

def test_serialize_produces_frontmatter_and_stripped_body():
    result = contexts._serialize("Product X", True, "es", "  # Title\nText  \n")

    assert result == ("---\nname: Product X\nactive: true\nlang: es\n---\n"
                      "# Title\nText\n")


def test_serialize_writes_inactive_as_false():
    result = contexts._serialize("A", False, "both", "b")

    assert result == "---\nname: A\nactive: false\nlang: both\n---\nb\n"


@pytest.mark.parametrize("name, active, lang, body", [
    ("Product X", True, "es", "# Product X\n\nSome *markdown*."),
    ("Notes", False, "en", "line 1\n---\nline 3"),
    ("Name: with colon", True, "both", "body"),
    ("", False, "both", ""),
])
def test_parse_reverses_serialize(name, active, lang, body):
    text = contexts._serialize(name, active, lang, body)

    result = contexts._parse(text)

    assert result == (name, active, lang, body)


def test_parse_without_frontmatter_returns_defaults_with_stripped_body():
    result = contexts._parse("  # Title\nplain text  \n")

    assert result == ("", False, "both", "# Title\nplain text")


@pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", "Yes", "si", "sí",
                                   "Sí", "  true  "])
def test_parse_reads_truthy_active_spellings(value):
    result = contexts._parse(f"---\nactive: {value}\n---\nbody")

    assert result[1] is True


@pytest.mark.parametrize("value", ["false", "0", "no", "", "on", "y"])
def test_parse_reads_other_active_values_as_false(value):
    result = contexts._parse(f"---\nactive: {value}\n---\nbody")

    assert result[1] is False


@pytest.mark.parametrize("value, expected", [
    ("es", "es"),
    ("EN", "en"),
    ("both", "both"),
    ("fr", "both"),
    ("", "both"),
])
def test_parse_normalizes_lang(value, expected):
    result = contexts._parse(f"---\nlang: {value}\n---\nbody")

    assert result[2] == expected


def test_parse_defaults_lang_to_both_when_missing():
    result = contexts._parse("---\nname: A\n---\nbody")

    assert result[2] == "both"


def test_parse_ignores_header_lines_without_colon():
    result = contexts._parse("---\nname: A\njust a note\nactive: yes\n---\nbody")

    assert result == ("A", True, "both", "body")


def test_parse_matches_keys_case_insensitively():
    result = contexts._parse("---\nName: A\nACTIVE: true\nLang: en\n---\nbody")

    assert result == ("A", True, "en", "body")


# --- list_contexts -----------------------------------------------------------------

def test_list_contexts_creates_missing_folder(isolated_data_dir):
    contexts.list_contexts()

    assert (isolated_data_dir / "contexts").is_dir()


def test_list_contexts_returns_empty_list_for_empty_folder(ctx_dir):
    result = contexts.list_contexts()

    assert result == []


def test_list_contexts_returns_parsed_entry(ctx_dir):
    _write(ctx_dir, "ctx-1.md", "---\nname: Prod\nactive: true\nlang: en\n---\nHello")

    result = contexts.list_contexts()

    assert result == [{"id": "ctx-1", "name": "Prod", "active": True,
                       "lang": "en", "body": "Hello"}]


def test_list_contexts_uses_id_as_name_when_missing(ctx_dir):
    _write(ctx_dir, "ctx-4.md", "no frontmatter")

    result = contexts.list_contexts()

    assert result[0]["name"] == "ctx-4"


def test_list_contexts_sorts_by_numeric_id(ctx_dir):
    _write(ctx_dir, "ctx-10.md", "ten")
    _write(ctx_dir, "ctx-2.md", "two")
    _write(ctx_dir, "ctx-1.md", "one")

    result = contexts.list_contexts()

    assert _ids(result) == ["ctx-1", "ctx-2", "ctx-10"]


def test_list_contexts_ignores_non_markdown_files(ctx_dir):
    _write(ctx_dir, "ctx-1.md", "kept")
    _write(ctx_dir, "notes.txt", "ignored")
    _write(ctx_dir, "ctx-2.md.bak", "ignored")

    result = contexts.list_contexts()

    assert _ids(result) == ["ctx-1"]


def test_list_contexts_accepts_uppercase_extension(ctx_dir):
    _write(ctx_dir, "ctx-1.MD", "upper")

    result = contexts.list_contexts()

    assert _ids(result) == ["ctx-1"]


def test_list_contexts_skips_unreadable_entry(ctx_dir):
    """A folder named like a context cannot be opened and must be skipped."""
    (ctx_dir / "ctx-1.md").mkdir()
    _write(ctx_dir, "ctx-2.md", "readable")

    result = contexts.list_contexts()

    assert _ids(result) == ["ctx-2"]


def test_list_contexts_reads_cp1252_file(ctx_dir):
    (ctx_dir / "ctx-1.md").write_bytes(b"espa\xf1ol")
    _write(ctx_dir, "ctx-2.md", "readable")

    result = contexts.list_contexts()

    assert [c["body"] for c in result] == ["español", "readable"]


def test_write_all_rewrites_cp1252_context_as_utf8(ctx_dir):
    (ctx_dir / "ctx-1.md").write_bytes(b"---\nname: Dise\xf1o\n---\nespa\xf1ol")

    contexts.write_all(contexts.list_contexts())

    assert "name: Diseño" in (ctx_dir / "ctx-1.md").read_text(encoding="utf-8")


def test_list_contexts_reads_utf8_bom_file(ctx_dir):
    (ctx_dir / "ctx-1.md").write_bytes(b"\xef\xbb\xbf---\nname: A\nactive: true\n---\nbody")

    assert contexts.list_contexts()[0]["name"] == "A"


# --- next_id -----------------------------------------------------------------------

@pytest.mark.parametrize("existing, expected", [
    ([], "ctx-1"),
    ([{"id": "ctx-1"}], "ctx-2"),
    ([{"id": "ctx-2"}, {"id": "ctx-7"}, {"id": "ctx-3"}], "ctx-8"),
    ([{"id": "notes"}], "ctx-1"),
    ([{"id": "ctx-09"}], "ctx-10"),
])
def test_next_id(existing, expected):
    result = contexts.next_id(existing)

    assert result == expected


# --- write_all ---------------------------------------------------------------------

def test_write_all_creates_missing_folder(isolated_data_dir):
    contexts.write_all([])

    assert (isolated_data_dir / "contexts").is_dir()


def test_write_all_writes_serialized_file(ctx_dir):
    contexts.write_all([{"id": "ctx-1", "name": "Prod", "active": True,
                         "lang": "es", "body": "Hello"}])

    content = (ctx_dir / "ctx-1.md").read_text(encoding="utf-8")
    assert content == "---\nname: Prod\nactive: true\nlang: es\n---\nHello\n"


def test_write_all_fills_missing_fields_with_defaults(ctx_dir):
    contexts.write_all([{"id": "ctx-3"}])

    content = (ctx_dir / "ctx-3.md").read_text(encoding="utf-8")
    assert content == "---\nname: ctx-3\nactive: false\nlang: both\n---\n\n"


def test_write_all_output_reads_back_through_list_contexts(ctx_dir):
    contexts.write_all([{"id": "ctx-2", "name": "B", "active": True,
                         "lang": "en", "body": "two"}])

    result = contexts.list_contexts()

    assert result == [{"id": "ctx-2", "name": "B", "active": True,
                       "lang": "en", "body": "two"}]


def test_write_all_deletes_removed_contexts(ctx_dir):
    _write(ctx_dir, "ctx-1.md", "keep")
    _write(ctx_dir, "ctx-2.md", "drop")

    contexts.write_all([{"id": "ctx-1", "body": "keep"}])

    assert sorted(os.listdir(ctx_dir)) == ["ctx-1.md"]


def test_write_all_keeps_non_markdown_files(ctx_dir):
    _write(ctx_dir, "readme.txt", "not a context")

    contexts.write_all([])

    assert sorted(os.listdir(ctx_dir)) == ["readme.txt"]


def test_write_all_ignores_entry_that_cannot_be_deleted(ctx_dir):
    """A folder named like a context cannot be removed; write_all must not raise."""
    (ctx_dir / "ctx-9.md").mkdir()

    contexts.write_all([{"id": "ctx-1", "body": "x"}])

    assert sorted(os.listdir(ctx_dir)) == ["ctx-1.md", "ctx-9.md"]


def test_write_all_preserves_listed_uppercase_extension_context(ctx_dir):
    _write(ctx_dir, "ctx-1.MD", "upper")
    listed = contexts.list_contexts()

    contexts.write_all(listed)

    assert len(os.listdir(ctx_dir)) == 1


# --- active_text / active_count ----------------------------------------------------

@pytest.mark.parametrize("meeting_lang, expected", [
    ("es", "body-es\n\nbody-both"),
    ("en", "body-en\n\nbody-both"),
    ("auto", "body-es\n\nbody-en\n\nbody-both"),
    (None, "body-es\n\nbody-en\n\nbody-both"),
])
def test_active_text_filters_by_meeting_language(mixed_contexts, meeting_lang,
                                                 expected):
    result = contexts.active_text(meeting_lang)

    assert result == expected


def test_active_text_defaults_to_all_languages(mixed_contexts):
    result = contexts.active_text()

    assert result == "body-es\n\nbody-en\n\nbody-both"


def test_active_text_is_empty_without_contexts(ctx_dir):
    result = contexts.active_text()

    assert result == ""


@pytest.mark.parametrize("meeting_lang, expected", [
    ("es", 3),     # ES, Both and the empty ES one
    ("en", 2),     # EN and Both
    ("auto", 4),   # every active context
])
def test_active_count_filters_by_meeting_language(mixed_contexts, meeting_lang,
                                                  expected):
    result = contexts.active_count(meeting_lang)

    assert result == expected


def test_active_count_defaults_to_all_languages(mixed_contexts):
    result = contexts.active_count()

    assert result == 4


# --- estimate_tokens ---------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("", 0),
    (None, 0),
    ("abc", 1),
    ("abcd", 1),
    ("abcdefgh", 2),
    ("x" * 400, 100),
])
def test_estimate_tokens(text, expected):
    result = contexts.estimate_tokens(text)

    assert result == expected


@pytest.mark.parametrize("filename", ["ctx-1.MD", "ctx-1.Md", "Notas.MD"])
def test_write_all_keeps_content_of_mixed_case_extension(ctx_dir, filename):
    _write(ctx_dir, filename, "keep me")

    contexts.write_all(contexts.list_contexts())

    assert [c["body"] for c in contexts.list_contexts()] == ["keep me"]


def test_write_all_still_deletes_removed_mixed_case_context(ctx_dir):
    _write(ctx_dir, "ctx-1.MD", "drop me")
    _write(ctx_dir, "ctx-2.md", "keep me")

    contexts.write_all([c for c in contexts.list_contexts() if c["id"] == "ctx-2"])

    assert os.listdir(ctx_dir) == ["ctx-2.md"]
