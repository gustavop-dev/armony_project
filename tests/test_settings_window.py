"""Tests for settings_window: the full-screen settings view and its custom controls.

The autouse ``isolated_data_dir`` fixture points config.json and contexts/ at a
per-test temp dir, so every save is asserted by reading those files back. The
only other redirection is the combo-box chevron PNG that SettingsWindow writes
at construction time: it goes to the temp dir instead of the repo's assets/.
Secrets go through the real DPAPI store (the suite runs on Windows Python).
"""
import pytest
from PySide6 import QtCore, QtGui, QtWidgets

import config
import icons
import settings_window as sw

LEFT = QtCore.Qt.LeftButton


# ------------------------------------------------------------------ fixtures
@pytest.fixture(autouse=True)
def chevron_in_tmp(isolated_data_dir, monkeypatch):
    """Write the combo chevron PNG into the temp dir, not into the repo."""
    real_save_png = icons.save_png

    def save_to_tmp(name, color, px, _path, *args, **kwargs):
        return real_save_png(name, color, px, str(isolated_data_dir / "_chevron.png"),
                             *args, **kwargs)

    monkeypatch.setattr(icons, "save_png", save_to_tmp)


@pytest.fixture
def ctx_dir(isolated_data_dir):
    """The isolated contexts folder, created and empty."""
    path = isolated_data_dir / "contexts"
    path.mkdir()
    return path


@pytest.fixture
def make_window(qtbot):
    """Build a SettingsWindow from the on-disk config plus overrides."""
    def _make(**overrides):
        cfg = config.load_config()
        cfg.update(overrides)
        win = sw.SettingsWindow(cfg)
        qtbot.addWidget(win)
        return win
    return _make


# ------------------------------------------------------------------ helpers
def _write_ctx(ctx_dir, cid, name, active=False, lang="both", body=""):
    (ctx_dir / f"{cid}.md").write_text(
        f"---\nname: {name}\nactive: {'true' if active else 'false'}\nlang: {lang}\n---\n{body}\n",
        encoding="utf-8")


def _page(win):
    return win.content.widget()


def _labels(widget):
    return widget.findChildren(QtWidgets.QLabel)


def _heading(win):
    """Title of the section currently shown (first label of the page)."""
    return _labels(_page(win))[0].text()


def _row(win, key):
    """Field row whose key chip shows ``key`` in the current section."""
    chip = next(lab for lab in _labels(_page(win)) if lab.text() == key)
    return chip.parentWidget().parentWidget()


def _nav(win, label):
    return next(n for n in win.findChildren(sw.NavItem) if n._lab.text() == label)


def _goto(qtbot, win, label):
    qtbot.mouseClick(_nav(win, label), LEFT)


def _button(widget, text):
    return next(b for b in widget.findChildren(QtWidgets.QPushButton) if b.text() == text)


def _tool_button(win, tooltip):
    return next(b for b in win.findChildren(QtWidgets.QPushButton) if b.toolTip() == tooltip)


def _save(qtbot, win):
    qtbot.mouseClick(_button(win, "Guardar"), LEFT)


def _footer_text(win):
    return win.saved_lbl.text()


def _ctx_card(win, name):
    """Context card in the list whose title label shows ``name``."""
    return next(c for c in _cards(win) if c.findChild(QtWidgets.QLabel).text() == name)


def _ctx_editor(win):
    """Editor column of the Contexts section (parent of the name QLineEdit)."""
    return _page(win).findChild(QtWidgets.QLineEdit).parentWidget()


def _filter_segmented(win):
    """Language filter above the context list (the one offering "all")."""
    return next(seg for seg in _page(win).findChildren(sw.Segmented) if "all" in seg._btns)


def _texts(win):
    """Text of every label in the current section, in layout order."""
    return [lab.text() for lab in _labels(_page(win))]


def _card_names(win):
    """Titles of the context cards currently listed, top to bottom."""
    return [frame.findChild(QtWidgets.QLabel).text() for frame in _cards(win)]


def _cards(win):
    """Context cards: frames in the list column that own a small ToggleSwitch."""
    switches = _page(win).findChildren(sw.ToggleSwitch)
    return [s.parentWidget() for s in switches if s.width() == 34]


def _ctx_file(ctx_dir, cid):
    return (ctx_dir / f"{cid}.md").read_text(encoding="utf-8")


# ================================================================== form building
def test_window_title_is_brand(make_window):
    win = make_window()

    assert win.windowTitle() == "Armony."


def test_window_opens_on_connection_section(make_window):
    win = make_window()

    assert _heading(win) == "Conexión"


def test_text_field_shows_configured_value(make_window):
    win = make_window(assemblyai_api_key="aai-123")

    edit = _row(win, "assemblyai_api_key").findChild(QtWidgets.QLineEdit)

    assert edit.text() == "aai-123"


SECRET_KEYS = ["openai_api_key", "assemblyai_api_key", "typesafe_api_key"]


def _combo(win, key):
    return _row(win, key).findChild(QtWidgets.QComboBox)


def _combo_values(combo):
    return [combo.itemData(i) for i in range(combo.count())]


def _all_field_keys():
    return [f["key"] for _sid, _ic, _label, _desc, fields in sw._schema() if fields
            for f in fields]


@pytest.mark.parametrize("key", SECRET_KEYS)
def test_secret_field_masks_its_text(make_window, key):
    win = make_window()

    edit = _row(win, key).findChild(QtWidgets.QLineEdit)

    assert edit.echoMode() == QtWidgets.QLineEdit.Password


@pytest.mark.parametrize("key, placeholder", [
    ("openai_api_key", "sk-proj-…"),
    ("typesafe_api_key", "apikey_…"),
])
def test_secret_field_shows_placeholder(make_window, key, placeholder):
    win = make_window()

    edit = _row(win, key).findChild(QtWidgets.QLineEdit)

    assert edit.placeholderText() == placeholder


@pytest.mark.parametrize("value, label", [("en", "English"), ("auto", "Auto")])
def test_language_select_shows_label_of_configured_value(qtbot, make_window, value,
                                                         label):
    win = make_window(language=value)
    _goto(qtbot, win, "General")

    assert _combo(win, "language").currentText() == label


def test_language_select_offers_es_en_auto(qtbot, make_window):
    win = make_window()
    _goto(qtbot, win, "General")

    assert _combo_values(_combo(win, "language")) == ["es", "en", "auto"]


def test_sections_are_keys_general_and_contexts():
    assert [label for _sid, _ic, label, _desc, _f in sw._schema()] == [
        "Conexión", "General", "Contexts"]


def test_only_user_settings_have_a_field():
    assert _all_field_keys() == ["openai_api_key", "assemblyai_api_key",
                                 "typesafe_api_key", "language", "window_opacity"]


@pytest.mark.parametrize("key", config.FIJAS)
def test_no_field_for_internal_settings(key):
    assert key not in _all_field_keys()


@pytest.mark.parametrize("key", ["openai_model", "openai_model_voice", "openai_model_vision"])
def test_no_model_selector(key):
    assert key not in _all_field_keys()


def test_no_provider_selector():
    assert not any(k == "llm_provider" or k.startswith("anthropic_")
                   for k in _all_field_keys())


def test_number_field_displays_formatted_value(qtbot, make_window):
    win = make_window(window_opacity=0.65)
    _goto(qtbot, win, "General")

    shown = [lab.text() for lab in _labels(_row(win, "window_opacity"))][-1]

    assert shown == "0.65"


# ================================================================== conditional rows
@pytest.fixture
def extra_section(monkeypatch):
    """Add a section with a toggle and a row shown only while it is on.

    No current field is a toggle or uses ``visible_si``; the generic controls
    are exercised by adding them to a copy of the real schema.
    """
    real_schema = sw._schema

    def schema():
        return real_schema() + [
            ("extra", "bolt", "Extra", "Campos de prueba.", [
                dict(key="flag", label="Flag", type="toggle", hint=""),
                dict(key="nivel", label="Nivel", type="number", min=0.5, max=10,
                     step=0.5, unit="x", hint="", visible_si=("flag", True)),
            ]),
        ]

    monkeypatch.setattr(sw, "_schema", schema)


@pytest.mark.parametrize("value", [True, False])
def test_toggle_field_reflects_configured_value(qtbot, make_window, extra_section,
                                                value):
    win = make_window(flag=value, nivel=1.0)
    _goto(qtbot, win, "Extra")

    assert _row(win, "flag").findChild(sw.ToggleSwitch).isChecked() is value


@pytest.mark.parametrize("flag, expected", [(True, True), (False, False)])
def test_conditional_row_follows_configured_value(qtbot, make_window, extra_section,
                                                  flag, expected):
    win = make_window(flag=flag, nivel=1.0)
    _goto(qtbot, win, "Extra")

    assert _row(win, "nivel").isVisibleTo(win) is expected


def test_conditional_row_hides_when_condition_changes(qtbot, make_window, extra_section):
    win = make_window(flag=True, nivel=1.0)
    _goto(qtbot, win, "Extra")

    qtbot.mouseClick(_row(win, "flag").findChild(sw.ToggleSwitch), LEFT)

    assert _row(win, "nivel").isVisibleTo(win) is False


@pytest.mark.parametrize("start", [True, False])
def test_toggle_click_is_saved(qtbot, make_window, extra_section, start):
    win = make_window(flag=start, nivel=1.0)
    _goto(qtbot, win, "Extra")
    qtbot.mouseClick(_row(win, "flag").findChild(sw.ToggleSwitch), LEFT)

    _save(qtbot, win)

    assert config.load_config()["flag"] is (not start)


# ================================================================== saving
@pytest.mark.parametrize("key, value", [
    ("openai_api_key", "sk-proj-typed"),
    ("assemblyai_api_key", "aai-typed"),
    ("typesafe_api_key", "apikey_typed"),
])
def test_saved_secret_round_trips_through_config(qtbot, make_window, key, value):
    win = make_window()
    _row(win, key).findChild(QtWidgets.QLineEdit).setText(value)

    _save(qtbot, win)

    assert config.load_config()[key] == value


@pytest.mark.parametrize("key, value", [
    ("openai_api_key", "sk-proj-typed"),
    ("typesafe_api_key", "apikey_typed"),
])
def test_saved_secret_is_not_written_in_plaintext(qtbot, make_window, isolated_data_dir,
                                                  key, value):
    win = make_window()
    _row(win, key).findChild(QtWidgets.QLineEdit).setText(value)

    _save(qtbot, win)

    assert value not in (isolated_data_dir / "config.json").read_text(encoding="utf-8")


def test_text_field_saves_stripped_value(qtbot, make_window):
    win = make_window()
    _row(win, "assemblyai_api_key").findChild(QtWidgets.QLineEdit).setText("  aai-1  ")

    _save(qtbot, win)

    assert config.load_config()["assemblyai_api_key"] == "aai-1"


def test_select_change_is_saved(qtbot, make_window):
    win = make_window(language="es")
    _goto(qtbot, win, "General")
    combo = _combo(win, "language")
    combo.setCurrentIndex(combo.findData("auto"))

    _save(qtbot, win)

    assert config.load_config()["language"] == "auto"


def test_fixed_model_is_kept_on_save(qtbot, make_window):
    win = make_window()

    _save(qtbot, win)

    assert config.load_config()["openai_model"] == "gpt-6.1-sol"


@pytest.mark.parametrize("position, expected", [(0, 0.15), (17, 1.0), (7, 0.5)])
def test_slider_position_is_saved_as_real_value(qtbot, make_window, position, expected):
    win = make_window()
    _goto(qtbot, win, "General")
    _row(win, "window_opacity").findChild(QtWidgets.QSlider).setValue(position)

    _save(qtbot, win)

    assert config.load_config()["window_opacity"] == expected


def test_slider_move_updates_displayed_value(qtbot, make_window):
    win = make_window()
    _goto(qtbot, win, "General")
    row = _row(win, "window_opacity")

    row.findChild(QtWidgets.QSlider).setValue(3)

    assert [lab.text() for lab in _labels(row)][-1] == "0.30"


def test_save_keeps_keys_without_a_field(qtbot, make_window):
    win = make_window(test_mode=True)

    _save(qtbot, win)

    assert config.load_config()["test_mode"] is True


def test_internal_values_are_not_saved_from_the_window(qtbot, make_window,
                                                       isolated_data_dir):
    win = make_window(openai_tokens_voice=400, silence_hang=1.5)

    _save(qtbot, win)

    stored = (isolated_data_dir / "config.json").read_text(encoding="utf-8")
    assert "openai_tokens_voice" not in stored and "silence_hang" not in stored


def test_values_edited_in_two_sections_are_saved(qtbot, make_window):
    win = make_window()
    _row(win, "assemblyai_api_key").findChild(QtWidgets.QLineEdit).setText("aai-x")
    _goto(qtbot, win, "General")
    combo = _combo(win, "language")
    combo.setCurrentIndex(combo.findData("en"))

    _save(qtbot, win)

    saved = config.load_config()
    assert (saved["assemblyai_api_key"], saved["language"]) == ("aai-x", "en")


# ================================================================== footer state / signals
def test_footer_starts_as_saved(make_window):
    win = make_window()

    assert _footer_text(win) == "Todo guardado"


def test_footer_marks_unsaved_after_edit(make_window):
    win = make_window()

    _row(win, "assemblyai_api_key").findChild(QtWidgets.QLineEdit).setText("x")

    assert _footer_text(win) == "Cambios sin guardar"


def test_save_emits_saved(qtbot, make_window):
    win = make_window()

    with qtbot.waitSignal(win.saved, timeout=1000):
        _save(qtbot, win)


def test_save_emits_closed(qtbot, make_window):
    win = make_window()

    with qtbot.waitSignal(win.closed, timeout=1000):
        _save(qtbot, win)


def test_save_failure_shows_error(qtbot, make_window, isolated_data_dir, monkeypatch):
    win = make_window()
    monkeypatch.setattr(config, "CONFIG_PATH", str(isolated_data_dir))  # a directory

    _save(qtbot, win)

    assert _footer_text(win) == "Error al guardar: no se pudo escribir config.json"


def test_save_failure_keeps_window_open(qtbot, make_window, isolated_data_dir, monkeypatch):
    win = make_window()
    monkeypatch.setattr(config, "CONFIG_PATH", str(isolated_data_dir))  # a directory

    with qtbot.assertNotEmitted(win.closed):
        _save(qtbot, win)


def test_edit_after_save_failure_clears_error(qtbot, make_window, isolated_data_dir,
                                              monkeypatch):
    win = make_window()
    monkeypatch.setattr(config, "CONFIG_PATH", str(isolated_data_dir))  # a directory
    _save(qtbot, win)

    _row(win, "assemblyai_api_key").findChild(QtWidgets.QLineEdit).setText("x")

    assert _footer_text(win) == "Cambios sin guardar"


def test_cancel_emits_closed(qtbot, make_window):
    win = make_window()

    with qtbot.waitSignal(win.closed, timeout=1000):
        qtbot.mouseClick(_button(win, "Cancelar"), LEFT)


def test_cancel_does_not_write_config(qtbot, make_window, isolated_data_dir):
    win = make_window()
    _row(win, "assemblyai_api_key").findChild(QtWidgets.QLineEdit).setText("aai-x")

    qtbot.mouseClick(_button(win, "Cancelar"), LEFT)

    assert not (isolated_data_dir / "config.json").exists()


def test_back_button_emits_closed(qtbot, make_window):
    win = make_window()

    with qtbot.waitSignal(win.closed, timeout=1000):
        qtbot.mouseClick(_tool_button(win, "Volver a la reunión"), LEFT)


def test_go_to_meeting_nav_emits_closed(qtbot, make_window):
    win = make_window()

    with qtbot.waitSignal(win.closed, timeout=1000):
        _goto(qtbot, win, "Go to the meeting")


def test_close_button_emits_close_app(qtbot, make_window):
    win = make_window()

    with qtbot.waitSignal(win.closeApp, timeout=1000):
        qtbot.mouseClick(_tool_button(win, "Cerrar Armony."), LEFT)


def test_close_button_does_not_emit_closed(qtbot, make_window):
    win = make_window()

    with qtbot.assertNotEmitted(win.closed):
        qtbot.mouseClick(_tool_button(win, "Cerrar Armony."), LEFT)


def test_minimize_button_minimizes_window(qtbot, make_window):
    win = make_window()
    win.show()

    qtbot.mouseClick(_tool_button(win, "Minimizar"), LEFT)

    assert win.isMinimized() is True


def test_escape_emits_closed(qtbot, make_window):
    win = make_window()

    with qtbot.waitSignal(win.closed, timeout=1000):
        qtbot.keyClick(win, QtCore.Qt.Key_Escape)


def test_other_key_does_not_emit_closed(qtbot, make_window):
    win = make_window()

    with qtbot.assertNotEmitted(win.closed):
        qtbot.keyClick(win, QtCore.Qt.Key_A)


def test_title_bar_drag_moves_window(make_window):
    win = make_window()
    win.move(200, 200)
    bar = next(lab for lab in _labels(win) if "Settings" in lab.text()).parentWidget()
    local = QtCore.QPointF(5, 5)

    bar.mousePressEvent(QtGui.QMouseEvent(
        QtCore.QEvent.MouseButtonPress, local, QtCore.QPointF(210, 210),
        LEFT, LEFT, QtCore.Qt.NoModifier))
    bar.mouseMoveEvent(QtGui.QMouseEvent(
        QtCore.QEvent.MouseMove, local, QtCore.QPointF(310, 260),
        QtCore.Qt.NoButton, LEFT, QtCore.Qt.NoModifier))

    assert win.pos() == QtCore.QPoint(300, 250)


# ================================================================== navigation
@pytest.mark.parametrize("label", ["General", "Contexts", "Conexión"])
def test_nav_click_shows_section(qtbot, make_window, label):
    win = make_window()
    _goto(qtbot, win, "Contexts")

    _goto(qtbot, win, label)

    assert _heading(win) == label


def test_nav_right_click_keeps_section(qtbot, make_window):
    win = make_window()

    qtbot.mouseClick(_nav(win, "General"), QtCore.Qt.RightButton)

    assert _heading(win) == "Conexión"


@pytest.mark.parametrize("label, color", [("General", "#f7e39a"), ("Conexión", "#b8af9a")])
def test_nav_item_color_marks_active_section(qtbot, make_window, label, color):
    win = make_window()

    _goto(qtbot, win, "General")

    assert _nav(win, label)._lab.styleSheet() == f"color: {color}; background: transparent;"


def test_nav_item_emits_clicked_on_left_press(qtbot):
    item = sw.NavItem("bolt", "Conexión")
    qtbot.addWidget(item)

    with qtbot.waitSignal(item.clicked, timeout=1000):
        qtbot.mouseClick(item, LEFT)


# ================================================================== contexts
def test_contexts_badge_counts_active(make_window, ctx_dir):
    _write_ctx(ctx_dir, "ctx-1", "A", active=True)
    _write_ctx(ctx_dir, "ctx-2", "B", active=True)
    _write_ctx(ctx_dir, "ctx-3", "C", active=False)

    win = make_window()

    assert _nav(win, "Contexts")._badge.text() == "2"


def test_contexts_badge_hidden_without_active(make_window, ctx_dir):
    _write_ctx(ctx_dir, "ctx-1", "A", active=False)

    win = make_window()

    assert _nav(win, "Contexts")._badge.isHidden() is True


def test_contexts_editor_shows_first_context(qtbot, make_window, ctx_dir):
    _write_ctx(ctx_dir, "ctx-1", "Alpha", body="alpha body")
    _write_ctx(ctx_dir, "ctx-2", "Beta")
    win = make_window()

    _goto(qtbot, win, "Contexts")

    assert _page(win).findChild(QtWidgets.QLineEdit).text() == "Alpha"


def test_contexts_editor_shows_body(qtbot, make_window, ctx_dir):
    _write_ctx(ctx_dir, "ctx-1", "Alpha", body="alpha body")
    win = make_window()

    _goto(qtbot, win, "Contexts")

    assert _page(win).findChild(QtWidgets.QPlainTextEdit).toPlainText() == "alpha body"


def test_contexts_without_files_shows_placeholder(qtbot, make_window, ctx_dir):
    win = make_window()

    _goto(qtbot, win, "Contexts")

    assert "Selecciona un contexto para editarlo" in _texts(win)


def test_contexts_card_click_selects_context(qtbot, make_window, ctx_dir):
    _write_ctx(ctx_dir, "ctx-1", "Alpha")
    _write_ctx(ctx_dir, "ctx-2", "Beta")
    win = make_window()
    _goto(qtbot, win, "Contexts")

    qtbot.mouseClick(_ctx_card(win, "Beta"), LEFT)

    assert _page(win).findChild(QtWidgets.QLineEdit).text() == "Beta"


def test_contexts_add_writes_new_file(qtbot, make_window, ctx_dir):
    win = make_window()
    _goto(qtbot, win, "Contexts")
    qtbot.mouseClick(_page(win).findChildren(QtWidgets.QPushButton)[0], LEFT)

    _save(qtbot, win)

    assert _ctx_file(ctx_dir, "ctx-1") == (
        "---\nname: Nuevo contexto\nactive: false\nlang: both\n---\n\n")


def test_contexts_add_uses_next_free_id(qtbot, make_window, ctx_dir):
    _write_ctx(ctx_dir, "ctx-3", "Existing")
    win = make_window()
    _goto(qtbot, win, "Contexts")
    qtbot.mouseClick(_page(win).findChildren(QtWidgets.QPushButton)[0], LEFT)

    _save(qtbot, win)

    assert sorted(p.name for p in ctx_dir.iterdir()) == ["ctx-3.md", "ctx-4.md"]


def test_contexts_add_selects_new_context(qtbot, make_window, ctx_dir):
    _write_ctx(ctx_dir, "ctx-1", "Alpha")
    win = make_window()
    _goto(qtbot, win, "Contexts")

    qtbot.mouseClick(_page(win).findChildren(QtWidgets.QPushButton)[0], LEFT)

    assert _page(win).findChild(QtWidgets.QLineEdit).text() == "Nuevo contexto"


def test_contexts_add_under_language_filter_uses_that_language(qtbot, make_window, ctx_dir):
    win = make_window()
    _goto(qtbot, win, "Contexts")
    qtbot.mouseClick(_button(_filter_segmented(win), "EN"), LEFT)
    qtbot.mouseClick(_page(win).findChildren(QtWidgets.QPushButton)[0], LEFT)

    _save(qtbot, win)

    assert "lang: en\n" in _ctx_file(ctx_dir, "ctx-1")


def test_contexts_rename_is_saved(qtbot, make_window, ctx_dir):
    _write_ctx(ctx_dir, "ctx-1", "Alpha", body="b")
    win = make_window()
    _goto(qtbot, win, "Contexts")
    _page(win).findChild(QtWidgets.QLineEdit).setText("Renamed")

    _save(qtbot, win)

    assert _ctx_file(ctx_dir, "ctx-1") == "---\nname: Renamed\nactive: false\nlang: both\n---\nb\n"


def test_contexts_body_edit_is_saved(qtbot, make_window, ctx_dir):
    _write_ctx(ctx_dir, "ctx-1", "Alpha", body="old")
    win = make_window()
    _goto(qtbot, win, "Contexts")
    _page(win).findChild(QtWidgets.QPlainTextEdit).setPlainText("# New body")

    _save(qtbot, win)

    assert _ctx_file(ctx_dir, "ctx-1") == (
        "---\nname: Alpha\nactive: false\nlang: both\n---\n# New body\n")


def test_contexts_editor_toggle_activates_context(qtbot, make_window, ctx_dir):
    _write_ctx(ctx_dir, "ctx-1", "Alpha", active=False, body="b")
    win = make_window()
    _goto(qtbot, win, "Contexts")
    qtbot.mouseClick(_ctx_editor(win).findChild(sw.ToggleSwitch), LEFT)

    _save(qtbot, win)

    assert _ctx_file(ctx_dir, "ctx-1") == "---\nname: Alpha\nactive: true\nlang: both\n---\nb\n"


def test_contexts_card_toggle_deactivates_context(qtbot, make_window, ctx_dir):
    _write_ctx(ctx_dir, "ctx-1", "Alpha", active=True)
    _write_ctx(ctx_dir, "ctx-2", "Beta", active=True)
    win = make_window()
    _goto(qtbot, win, "Contexts")
    qtbot.mouseClick(_ctx_card(win, "Beta").findChild(sw.ToggleSwitch), LEFT)

    _save(qtbot, win)

    assert "active: false\n" in _ctx_file(ctx_dir, "ctx-2")


def test_contexts_toggle_updates_badge(qtbot, make_window, ctx_dir):
    _write_ctx(ctx_dir, "ctx-1", "Alpha", active=False)
    win = make_window()
    _goto(qtbot, win, "Contexts")

    qtbot.mouseClick(_ctx_editor(win).findChild(sw.ToggleSwitch), LEFT)

    assert _nav(win, "Contexts")._badge.text() == "1"


def test_contexts_delete_removes_file(qtbot, make_window, ctx_dir):
    _write_ctx(ctx_dir, "ctx-1", "Alpha")
    _write_ctx(ctx_dir, "ctx-2", "Beta")
    win = make_window()
    _goto(qtbot, win, "Contexts")
    _dup, trash = _ctx_card(win, "Alpha").findChildren(QtWidgets.QPushButton)
    qtbot.mouseClick(trash, LEFT)

    _save(qtbot, win)

    assert sorted(p.name for p in ctx_dir.iterdir()) == ["ctx-2.md"]


def test_contexts_delete_selected_moves_selection_to_first(qtbot, make_window, ctx_dir):
    _write_ctx(ctx_dir, "ctx-1", "Alpha")
    _write_ctx(ctx_dir, "ctx-2", "Beta")
    win = make_window()
    _goto(qtbot, win, "Contexts")
    _dup, trash = _ctx_card(win, "Alpha").findChildren(QtWidgets.QPushButton)

    qtbot.mouseClick(trash, LEFT)

    assert _page(win).findChild(QtWidgets.QLineEdit).text() == "Beta"


def test_contexts_delete_last_shows_placeholder(qtbot, make_window, ctx_dir):
    _write_ctx(ctx_dir, "ctx-1", "Alpha")
    win = make_window()
    _goto(qtbot, win, "Contexts")
    _dup, trash = _ctx_card(win, "Alpha").findChildren(QtWidgets.QPushButton)

    qtbot.mouseClick(trash, LEFT)

    assert "Selecciona un contexto para editarlo" in _texts(win)


def test_contexts_duplicate_writes_inactive_copy(qtbot, make_window, ctx_dir):
    _write_ctx(ctx_dir, "ctx-1", "Alpha", active=True, lang="es", body="b")
    win = make_window()
    _goto(qtbot, win, "Contexts")
    dup, _trash = _ctx_card(win, "Alpha").findChildren(QtWidgets.QPushButton)
    qtbot.mouseClick(dup, LEFT)

    _save(qtbot, win)

    assert _ctx_file(ctx_dir, "ctx-2") == (
        "---\nname: Alpha (copia)\nactive: false\nlang: es\n---\nb\n")


def test_contexts_language_change_is_saved(qtbot, make_window, ctx_dir):
    _write_ctx(ctx_dir, "ctx-1", "Alpha", lang="both", body="b")
    win = make_window()
    _goto(qtbot, win, "Contexts")
    lang_seg = next(s for s in _page(win).findChildren(sw.Segmented) if "both" in s._btns)
    qtbot.mouseClick(_button(lang_seg, "EN"), LEFT)

    _save(qtbot, win)

    assert _ctx_file(ctx_dir, "ctx-1") == "---\nname: Alpha\nactive: false\nlang: en\n---\nb\n"


@pytest.mark.parametrize("flt, expected", [
    ("ES", ["Spanish", "Both"]),
    ("EN", ["English", "Both"]),
])
def test_contexts_filter_lists_matching_cards(qtbot, make_window, ctx_dir, flt, expected):
    _write_ctx(ctx_dir, "ctx-1", "Spanish", lang="es")
    _write_ctx(ctx_dir, "ctx-2", "English", lang="en")
    _write_ctx(ctx_dir, "ctx-3", "Both", lang="both")
    win = make_window()
    _goto(qtbot, win, "Contexts")

    qtbot.mouseClick(_button(_filter_segmented(win), flt), LEFT)

    assert _card_names(win) == expected


def test_contexts_filter_back_to_all_lists_every_card(qtbot, make_window, ctx_dir):
    _write_ctx(ctx_dir, "ctx-1", "Spanish", lang="es")
    _write_ctx(ctx_dir, "ctx-2", "English", lang="en")
    win = make_window()
    _goto(qtbot, win, "Contexts")
    qtbot.mouseClick(_button(_filter_segmented(win), "ES"), LEFT)

    qtbot.mouseClick(_button(_filter_segmented(win), "Todos"), LEFT)

    assert _card_names(win) == ["Spanish", "English"]


def test_contexts_filter_without_matches_shows_empty_note(qtbot, make_window, ctx_dir):
    _write_ctx(ctx_dir, "ctx-1", "Spanish", lang="es")
    win = make_window()
    _goto(qtbot, win, "Contexts")

    qtbot.mouseClick(_button(_filter_segmented(win), "EN"), LEFT)

    assert "Sin contextos en este idioma." in _texts(win)


@pytest.mark.parametrize("text", ["2 activos", "~30 tok", "2 contexts loaded"])
def test_contexts_summary_reports_active_contexts(qtbot, make_window, ctx_dir, text):
    _write_ctx(ctx_dir, "ctx-1", "Alpha", active=True, body="x" * 40)
    _write_ctx(ctx_dir, "ctx-2", "Beta", active=True, body="y" * 80)
    _write_ctx(ctx_dir, "ctx-3", "Gamma", active=False, body="z" * 400)
    win = make_window()

    _goto(qtbot, win, "Contexts")

    assert text in _texts(win)


def test_contexts_summary_warns_on_large_context(qtbot, make_window, ctx_dir):
    _write_ctx(ctx_dir, "ctx-1", "Alpha", active=True, body="x" * 16008)
    win = make_window()

    _goto(qtbot, win, "Contexts")

    assert ("⚠ Contexto grande: puede subir el costo y la latencia de la primera respuesta."
            in _texts(win))


def test_contexts_summary_silent_on_small_context(qtbot, make_window, ctx_dir):
    _write_ctx(ctx_dir, "ctx-1", "Alpha", active=True, body="x" * 400)
    win = make_window()

    _goto(qtbot, win, "Contexts")

    assert not any(text.startswith("⚠") for text in _texts(win))


# ================================================================== ToggleSwitch
@pytest.mark.parametrize("small, size", [(False, (42, 24)), (True, (34, 20))])
def test_toggle_switch_size(qtbot, small, size):
    switch = sw.ToggleSwitch(small=small)
    qtbot.addWidget(switch)

    assert (switch.width(), switch.height()) == size


@pytest.mark.parametrize("checked", [True, False])
def test_toggle_switch_initial_state(qtbot, checked):
    switch = sw.ToggleSwitch(checked)
    qtbot.addWidget(switch)

    assert switch.isChecked() is checked


def test_toggle_switch_click_emits_new_state(qtbot):
    switch = sw.ToggleSwitch(False)
    qtbot.addWidget(switch)

    with qtbot.waitSignal(switch.toggled, timeout=1000) as blocker:
        qtbot.mouseClick(switch, LEFT)

    assert blocker.args == [True]


@pytest.mark.parametrize("checked", [True, False])
def test_toggle_switch_paints(qtbot, checked):
    switch = sw.ToggleSwitch(checked)
    qtbot.addWidget(switch)

    assert switch.grab().isNull() is False


# ================================================================== Segmented
def test_segmented_value_starts_at_current(qtbot):
    seg = sw.Segmented([("a", "A"), ("b", "B")], "b")
    qtbot.addWidget(seg)

    assert seg.value() == "b"


def test_segmented_click_emits_value(qtbot):
    seg = sw.Segmented([("a", "A"), ("b", "B")], "a")
    qtbot.addWidget(seg)

    with qtbot.waitSignal(seg.changed, timeout=1000) as blocker:
        qtbot.mouseClick(_button(seg, "B"), LEFT)

    assert blocker.args == ["b"]


def test_segmented_click_updates_value(qtbot):
    seg = sw.Segmented([("a", "A"), ("b", "B")], "a")
    qtbot.addWidget(seg)

    qtbot.mouseClick(_button(seg, "B"), LEFT)

    assert seg.value() == "b"


def test_segmented_click_on_current_does_not_emit(qtbot):
    seg = sw.Segmented([("a", "A"), ("b", "B")], "a")
    qtbot.addWidget(seg)

    with qtbot.assertNotEmitted(seg.changed):
        qtbot.mouseClick(_button(seg, "A"), LEFT)


def test_segmented_highlights_picked_option(qtbot):
    seg = sw.Segmented([("a", "A"), ("b", "B")], "a", small=True)
    qtbot.addWidget(seg)

    qtbot.mouseClick(_button(seg, "B"), LEFT)

    assert "color: #f7e39a" in _button(seg, "B").styleSheet()


# ================================================================== Dot
def test_dot_has_fixed_diameter(qtbot):
    dot = sw.Dot("#ff0000", 12)
    qtbot.addWidget(dot)

    assert (dot.width(), dot.height()) == (12, 12)


def test_dot_set_color_changes_color(qtbot):
    dot = sw.Dot("#ff0000", 8)
    qtbot.addWidget(dot)

    dot.set_color("#00ff00")

    assert dot._c.name() == "#00ff00"


def test_dot_paints(qtbot):
    dot = sw.Dot()
    qtbot.addWidget(dot)

    assert dot.grab().isNull() is False
