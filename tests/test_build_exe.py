"""Tests for build_exe.py: dependency probing, OpenSSL DLL discovery and the
PyInstaller command line. subprocess is replaced; nothing is built."""
import os

import pytest

import build_exe


@pytest.mark.parametrize("module, expected", [
    ("json", True), ("module_that_does_not_exist_xyz", False)])
def test_installed_probe(module, expected):
    assert build_exe.instalado(module) is expected


def test_installed_probe_handles_find_spec_errors(monkeypatch):
    def broken(_name):
        raise ValueError("bad spec")
    monkeypatch.setattr(build_exe.importlib.util, "find_spec", broken)

    assert build_exe.instalado("anything") is False


# ------------------------------------------------------------- OpenSSL DLLs
def _touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").close()


@pytest.fixture
def prefixes(tmp_path, monkeypatch):
    base, venv = tmp_path / "base", tmp_path / "venv"
    base.mkdir()
    venv.mkdir()
    monkeypatch.setattr(build_exe.sys, "base_prefix", str(base))
    monkeypatch.setattr(build_exe.sys, "prefix", str(venv))
    return base, venv


def test_openssl_dlls_found_in_conda_library_bin(prefixes):
    base, _ = prefixes
    _touch(str(base / "Library" / "bin" / "libssl-3-x64.dll"))
    _touch(str(base / "Library" / "bin" / "zlib.dll"))

    assert [os.path.basename(p) for p in build_exe.dlls_de_openssl()] == ["libssl-3-x64.dll"]


def test_openssl_dlls_deduplicated_by_file_name(prefixes):
    base, _ = prefixes
    _touch(str(base / "Library" / "bin" / "libcrypto-3-x64.dll"))
    _touch(str(base / "DLLs" / "LIBCRYPTO-3-X64.DLL"))

    assert len(build_exe.dlls_de_openssl()) == 1


def test_openssl_dlls_empty_without_matches(prefixes):
    assert build_exe.dlls_de_openssl() == []


# ------------------------------------------------------------------- main()
def _values_after(cmd, flag):
    """Arguments that follow each occurrence of a PyInstaller flag."""
    return [cmd[i + 1] for i, arg in enumerate(cmd) if arg == flag]


@pytest.fixture
def build(tmp_path, monkeypatch):
    """Run main() against a temp project dir; returns the recorded commands."""
    _touch(str(tmp_path / "assets" / "armony.ico"))
    calls = []
    monkeypatch.setattr(build_exe, "HERE", str(tmp_path))
    monkeypatch.setattr(build_exe.subprocess, "check_call",
                        lambda cmd, cwd=None: calls.append(cmd))
    monkeypatch.setattr(build_exe, "dlls_de_openssl", lambda: [])

    def run(installed=()):
        monkeypatch.setattr(build_exe, "instalado", lambda m: m in installed)
        build_exe.main()
        return calls
    return run


def test_main_builds_single_windowless_exe(build, tmp_path):
    cmd = build()[0]

    assert cmd[1:9] == ["-m", "PyInstaller", "--name", "Armony", "--onefile",
                        "--noconsole", "--noconfirm", "--clean"]


def test_main_targets_app_entry_point(build, tmp_path):
    cmd = build()[0]

    assert cmd[-1] == os.path.join(str(tmp_path), "app.py")


def test_main_generates_missing_icon_first(build, tmp_path):
    os.remove(str(tmp_path / "assets" / "armony.ico"))

    calls = build()

    assert calls[0][1] == os.path.join(str(tmp_path), "make_icon.py")


def test_main_collects_pygments_when_installed(build):
    cmd = build(installed=("pygments",))[0]

    assert _values_after(cmd, "--collect-all") == ["pygments"]


def test_main_excludes_offline_stack_without_faster_whisper(build):
    cmd = build()[0]

    assert _values_after(cmd, "--exclude-module") == ["faster_whisper", "ctranslate2", "torch"]


def test_main_collects_offline_stack_with_faster_whisper(build):
    cmd = build(installed=("faster_whisper",))[0]

    assert _values_after(cmd, "--collect-all") == ["faster_whisper", "ctranslate2"]


def test_main_collects_cuda_binaries_with_nvidia(build):
    cmd = build(installed=("faster_whisper", "nvidia"))[0]

    assert cmd[cmd.index("--collect-binaries") + 1] == "nvidia"


def test_main_bundles_openssl_dlls(build, monkeypatch):
    monkeypatch.setattr(build_exe, "dlls_de_openssl", lambda: ["C:\\py\\libssl-3.dll"])

    cmd = build()[0]

    assert cmd[cmd.index("--add-binary") + 1] == f"C:\\py\\libssl-3.dll{build_exe.SEP}."


def test_main_reports_missing_exe(build, capsys):
    build()

    assert "no encuentro dist/Armony.exe" in capsys.readouterr().out


def test_main_reports_built_exe_size(build, tmp_path, capsys):
    exe = tmp_path / "dist" / "Armony.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"\0" * 3 * 1_048_576)

    build()

    assert "(3 MB)" in capsys.readouterr().out
