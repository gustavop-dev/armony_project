"""Tests for icons: Heroicons drawn as in-memory SVG and tinted on demand.

Pixmaps are checked for size, scale and non-nullness only (no pixel comparisons).
Screen scaling is the boundary: the offscreen platform reports 1.0, and other
ratios are simulated by faking the screen lookup.
"""
from types import SimpleNamespace

import pytest
from PySide6 import QtGui

import icons


# ------------------------------------------------------------------ _svg
def test_svg_returns_utf8_bytes():
    assert isinstance(icons._svg("x", "#123456"), bytes)


def test_svg_contains_color():
    assert b'stroke="#123456"' in icons._svg("x", "#123456")


def test_svg_uses_default_stroke_width():
    assert b'stroke-width="1.5"' in icons._svg("x", "#123456")


def test_svg_uses_given_stroke_width():
    assert b'stroke-width="2.5"' in icons._svg("x", "#123456", 2.5)


def test_svg_is_complete_document():
    assert icons._svg("minus", "#fff") == (
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        b'stroke="#fff" stroke-width="1.5"><path stroke-linecap="round" '
        b'stroke-linejoin="round" d="M5 12h14"/></svg>')


@pytest.mark.parametrize("name, paths", [("camera", 2), ("eye", 2), ("bolt", 1)])
def test_svg_has_one_path_per_stroke(name, paths):
    assert icons._svg(name, "#fff").count(b"<path ") == paths


def test_svg_unknown_icon_raises_key_error():
    with pytest.raises(KeyError):
        icons._svg("no-such-icon", "#fff")


# ------------------------------------------------------------------ _screen_dpr
def test_screen_dpr_reads_offscreen_screen(qapp):
    assert icons._screen_dpr() == 1.0


def _fake_qtgui(monkeypatch, app):
    monkeypatch.setattr(icons, "QtGui", SimpleNamespace(
        QGuiApplication=SimpleNamespace(instance=lambda: app)))


def _app_with_screen(ratio):
    screen = SimpleNamespace(devicePixelRatio=lambda: ratio)
    return SimpleNamespace(primaryScreen=lambda: screen)


def test_screen_dpr_without_app_assumes_hidpi(monkeypatch):
    _fake_qtgui(monkeypatch, None)

    assert icons._screen_dpr() == 2.0


def test_screen_dpr_without_screen_assumes_hidpi(monkeypatch):
    _fake_qtgui(monkeypatch, SimpleNamespace(primaryScreen=lambda: None))

    assert icons._screen_dpr() == 2.0


@pytest.mark.parametrize("ratio, expected", [(1.5, 1.5), (2.0, 2.0), (0.5, 1.0)])
def test_screen_dpr_never_goes_below_one(monkeypatch, ratio, expected):
    _fake_qtgui(monkeypatch, _app_with_screen(ratio))

    assert icons._screen_dpr() == expected


# ------------------------------------------------------------------ pixmap
def test_pixmap_is_not_null(qapp):
    assert icons.pixmap("cog", "#f2c94c").isNull() is False


@pytest.mark.parametrize("px", [13, 16, 24])
def test_pixmap_has_requested_logical_size(qapp, px):
    pm = icons.pixmap("cog", "#f2c94c", px)

    assert (pm.deviceIndependentSize().width(), pm.deviceIndependentSize().height()) == (px, px)


def test_pixmap_renders_at_physical_screen_resolution(qapp, monkeypatch):
    monkeypatch.setattr(icons, "_screen_dpr", lambda: 1.5)

    pm = icons.pixmap("cog", "#f2c94c", 16)

    assert (pm.width(), pm.height(), pm.devicePixelRatio()) == (24, 24, 1.5)


def test_pixmap_has_alpha_channel(qapp):
    assert icons.pixmap("x", "#ffffff", 16).hasAlphaChannel() is True


def test_pixmap_unknown_icon_raises_key_error(qapp):
    with pytest.raises(KeyError):
        icons.pixmap("no-such-icon", "#fff", 16)


# ------------------------------------------------------------------ save_png
def test_save_png_returns_path(qapp, tmp_path):
    path = str(tmp_path / "chevron.png")

    assert icons.save_png("chevron_down", "#b8af9a", 24, path) == path


def test_save_png_writes_png_file(qapp, tmp_path):
    path = tmp_path / "chevron.png"

    icons.save_png("chevron_down", "#b8af9a", 24, str(path))

    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_save_png_writes_requested_size(qapp, tmp_path):
    path = tmp_path / "chevron.png"

    icons.save_png("chevron_down", "#b8af9a", 20, str(path))

    assert QtGui.QImage(str(path)).size().toTuple() == (20, 20)


def test_save_png_unknown_icon_writes_nothing(qapp, tmp_path):
    path = tmp_path / "nope.png"

    with pytest.raises(KeyError):
        icons.save_png("no-such-icon", "#fff", 16, str(path))

    assert path.exists() is False


# ------------------------------------------------------------------ label
@pytest.mark.parametrize("px", [12, 17])
def test_label_has_fixed_size(qtbot, px):
    lab = icons.label("puzzle", "#f2c94c", px)
    qtbot.addWidget(lab)

    assert (lab.minimumSize().toTuple(), lab.maximumSize().toTuple()) == ((px, px), (px, px))


def test_label_scales_contents(qtbot):
    lab = icons.label("puzzle", "#f2c94c")
    qtbot.addWidget(lab)

    assert lab.hasScaledContents() is True


def test_label_shows_pixmap(qtbot):
    lab = icons.label("puzzle", "#f2c94c")
    qtbot.addWidget(lab)

    assert lab.pixmap().isNull() is False


def test_label_has_transparent_style(qtbot):
    lab = icons.label("puzzle", "#f2c94c")
    qtbot.addWidget(lab)

    assert lab.styleSheet() == "background: transparent; border: none;"


def test_label_unknown_icon_raises_key_error(qtbot):
    with pytest.raises(KeyError):
        icons.label("no-such-icon", "#fff")
