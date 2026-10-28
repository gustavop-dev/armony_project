"""Tests for theme: design tokens, optional font loading and the key-cap stylesheet.

``theme.FONT_DIR`` is pointed at ``tmp_path`` so the real assets/fonts/ folder (its
.ttf files are gitignored) never matters. Detecting the design families needs a
font whose family really is "Instrument Sans" / "JetBrains Mono"; since those are
not available, the Qt font database is replaced by a small fake at that boundary.
The fallback paths (no folder, unreadable file) use the real QFontDatabase.
"""
import os
from types import SimpleNamespace

import pytest

import theme


@pytest.fixture(autouse=True)
def fresh_font_state(monkeypatch):
    """Start every test with no design font loaded."""
    monkeypatch.setattr(theme, "_loaded", {"sans": False, "mono": False})


@pytest.fixture
def font_dir(tmp_path, monkeypatch):
    """An empty fonts folder that theme.load_fonts() will scan."""
    path = tmp_path / "fonts"
    path.mkdir()
    monkeypatch.setattr(theme, "FONT_DIR", str(path))
    return path


class FakeFontDatabase:
    """Stands in for QtGui.QFontDatabase: file name -> families, -1 when broken."""

    families_by_file = {}
    added = []

    @classmethod
    def addApplicationFont(cls, path):
        name = os.path.basename(path)
        cls.added.append(name)
        if name not in cls.families_by_file:
            return -1
        return name

    @classmethod
    def applicationFontFamilies(cls, fid):
        return cls.families_by_file[fid]


@pytest.fixture
def fake_fontdb(monkeypatch):
    """Install FakeFontDatabase behind theme.QtGui and return it."""
    FakeFontDatabase.families_by_file = {}
    FakeFontDatabase.added = []
    monkeypatch.setattr(theme, "QtGui", SimpleNamespace(QFontDatabase=FakeFontDatabase))
    return FakeFontDatabase


def _touch(font_dir, name):
    (font_dir / name).write_bytes(b"font")


def _install(font_dir, fake_fontdb, files):
    """Create each font file and register its families in the fake database."""
    for name in files:
        _touch(font_dir, name)
    fake_fontdb.families_by_file = files


# ------------------------------------------------------------------ load_fonts
def test_load_fonts_without_folder_loads_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(theme, "FONT_DIR", str(tmp_path / "missing"))

    assert theme.load_fonts() == {"sans": False, "mono": False}


def test_load_fonts_with_empty_folder_loads_nothing(font_dir):
    assert theme.load_fonts() == {"sans": False, "mono": False}


def test_load_fonts_skips_unreadable_font_file(qapp, font_dir):
    (font_dir / "InstrumentSans.ttf").write_bytes(b"this is not a font")

    assert theme.load_fonts() == {"sans": False, "mono": False}


def test_load_fonts_detects_instrument_sans(font_dir, fake_fontdb):
    _touch(font_dir, "InstrumentSans-Regular.ttf")
    fake_fontdb.families_by_file = {"InstrumentSans-Regular.ttf": ["Instrument Sans"]}

    assert theme.load_fonts() == {"sans": True, "mono": False}


def test_load_fonts_detects_jetbrains_mono(font_dir, fake_fontdb):
    _touch(font_dir, "JetBrainsMono.otf")
    fake_fontdb.families_by_file = {"JetBrainsMono.otf": ["JetBrains Mono"]}

    assert theme.load_fonts() == {"sans": False, "mono": True}


def test_load_fonts_accepts_uppercase_extension(font_dir, fake_fontdb):
    _touch(font_dir, "INSTRUMENT.TTF")
    fake_fontdb.families_by_file = {"INSTRUMENT.TTF": ["Instrument Sans"]}

    assert theme.load_fonts() == {"sans": True, "mono": False}


def test_load_fonts_ignores_non_font_files(font_dir, fake_fontdb):
    _touch(font_dir, "LEEME.txt")
    _touch(font_dir, "preview.png")

    theme.load_fonts()

    assert fake_fontdb.added == []


def test_load_fonts_ignores_unrelated_families(font_dir, fake_fontdb):
    _touch(font_dir, "Other.ttf")
    fake_fontdb.families_by_file = {"Other.ttf": ["Comic Neue"]}

    assert theme.load_fonts() == {"sans": False, "mono": False}


def test_load_fonts_continues_after_broken_file(font_dir, fake_fontdb):
    _touch(font_dir, "a-broken.ttf")
    _touch(font_dir, "b-mono.ttf")
    fake_fontdb.families_by_file = {"b-mono.ttf": ["JetBrains Mono"]}

    assert theme.load_fonts() == {"sans": False, "mono": True}


# ------------------------------------------------------------------ fonts_missing
def test_fonts_missing_lists_both_families_when_nothing_loaded(tmp_path, monkeypatch):
    monkeypatch.setattr(theme, "FONT_DIR", str(tmp_path / "missing"))
    theme.load_fonts()

    assert theme.fonts_missing() == ["Instrument Sans", "JetBrains Mono"]


@pytest.mark.parametrize("files, expected", [
    ({"sans.ttf": ["Instrument Sans"]}, ["JetBrains Mono"]),
    ({"mono.ttf": ["JetBrains Mono"]}, ["Instrument Sans"]),
    ({"sans.ttf": ["Instrument Sans"], "mono.ttf": ["JetBrains Mono"]}, []),
])
def test_fonts_missing_lists_only_unloaded_families(font_dir, fake_fontdb, files, expected):
    _install(font_dir, fake_fontdb, files)
    theme.load_fonts()

    assert theme.fonts_missing() == expected


# ------------------------------------------------------------------ kbd_qss
def test_kbd_qss_dark_style():
    assert theme.kbd_qss() == (
        "font-family: 'JetBrains Mono', 'Cascadia Mono', Consolas, monospace; "
        "font-size: 11px; padding: 2px 5px; border-radius: 5px; "
        "background: rgba(0,0,0,0.35); border: 1px solid rgba(243,234,212,0.14); "
        "color: #d9d0ba;")


def test_kbd_qss_light_style():
    assert theme.kbd_qss(light=True) == (
        "font-family: 'JetBrains Mono', 'Cascadia Mono', Consolas, monospace; "
        "font-size: 11px; padding: 2px 5px; border-radius: 5px; "
        "background: rgba(0,0,0,0.18); border: none; color: #2a2410;")


# ------------------------------------------------------------------ constants
@pytest.mark.parametrize("name, expected", [
    ("SANS_STACK", "'Instrument Sans', 'Segoe UI Variable Display', 'Segoe UI', sans-serif"),
    ("MONO_STACK", "'JetBrains Mono', 'Cascadia Mono', Consolas, monospace"),
    ("GOLD", "#f2c94c"),
    ("GOLD_BTN_INK", "#2a2410"),
    ("ANSWER_TEXT", "#ffffff"),
    ("WINDOW_OPACITY", 0.65),
    ("R_KBD", 5),
    ("PANEL_WIDTH", 1080),
])
def test_design_token_value(name, expected):
    assert getattr(theme, name) == expected


def test_font_dir_points_at_assets_fonts():
    assert theme.FONT_DIR.replace("\\", "/").endswith("/assets/fonts")
