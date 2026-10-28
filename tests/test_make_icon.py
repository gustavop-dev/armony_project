"""Tests for make_icon.py: per-size rendering and .ico packaging."""
import os
import struct
from types import SimpleNamespace

import pytest
from PySide6 import QtWidgets

import make_icon

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@pytest.mark.parametrize("px", [16, 256])
def test_draw_returns_square_pixmap_of_requested_size(qtbot, px):
    pm = make_icon.dibujar(px)

    assert (pm.width(), pm.height()) == (px, px)


def test_png_bytes_are_png_encoded(qtbot):
    assert make_icon.png_bytes(make_icon.dibujar(16)).startswith(PNG_SIGNATURE)


def _ico_entries(path):
    data = open(path, "rb").read()
    reserved, kind, count = struct.unpack_from("<HHH", data, 0)
    entries = [struct.unpack_from("<BBBBHHII", data, 6 + 16 * i) for i in range(count)]
    return (reserved, kind, count), entries, data


def test_ico_header_declares_icon_type_and_count(tmp_path):
    path = str(tmp_path / "a.ico")

    make_icon.escribir_ico([(16, b"AAAA"), (32, b"BBBBBB")], path)

    assert _ico_entries(path)[0] == (0, 1, 2)


def test_ico_entries_carry_sizes_and_offsets(tmp_path):
    path = str(tmp_path / "a.ico")

    make_icon.escribir_ico([(16, b"AAAA"), (256, b"BBBBBB")], path)

    assert _ico_entries(path)[1] == [(16, 16, 0, 0, 1, 32, 4, 38),
                                     (0, 0, 0, 0, 1, 32, 6, 42)]


def test_ico_payload_follows_directory(tmp_path):
    path = str(tmp_path / "a.ico")

    make_icon.escribir_ico([(16, b"AAAA"), (32, b"BBBBBB")], path)

    assert _ico_entries(path)[2][38:] == b"AAAABBBBBB"


@pytest.fixture
def icon_dir(tmp_path, monkeypatch, qtbot):
    """Redirect outputs to tmp_path and reuse the test QApplication."""
    monkeypatch.setattr(make_icon, "HERE", str(tmp_path))
    monkeypatch.setattr(make_icon, "SALIDA", str(tmp_path / "assets" / "armony.ico"))
    # make_icon only uses QtWidgets to create the app; reuse the existing one.
    monkeypatch.setattr(make_icon, "QtWidgets", SimpleNamespace(
        QApplication=lambda _argv: QtWidgets.QApplication.instance()))
    return tmp_path


def test_main_writes_ico_with_all_sizes(icon_dir):
    make_icon.main()

    assert _ico_entries(str(icon_dir / "assets" / "armony.ico"))[0][2] == 7


@pytest.mark.parametrize("name", ["armony-256.png", "armony-tamanos.png"])
def test_main_writes_preview_images(icon_dir, name):
    make_icon.main()

    assert os.path.getsize(str(icon_dir / "assets" / name)) > 0
