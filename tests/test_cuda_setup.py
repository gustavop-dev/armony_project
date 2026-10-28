"""Tests for cuda_setup.register_cuda_dlls with a fake site-packages tree.

os.add_dll_directory is the boundary replaced; sys.path, sys.platform, PATH
and the module's one-shot flag are patched per test.
"""
import os
import sys

import pytest

import cuda_setup


class DllRegistry:
    """Fake os.add_dll_directory; raises OSError for paths in ``refuse``."""

    def __init__(self):
        self.added = []
        self.refuse = set()

    def __call__(self, path):
        if path in self.refuse:
            raise OSError(f"cannot add {path}")
        self.added.append(path)


@pytest.fixture
def site(tmp_path):
    """site-packages with two DLL dirs, a lib without bin/ and a bin file."""
    sp = tmp_path / "Lib" / "site-packages"
    for lib in ("cublas", "cudnn"):
        (sp / "nvidia" / lib / "bin").mkdir(parents=True)
    (sp / "nvidia" / "nccl").mkdir(parents=True)
    (sp / "nvidia" / "cufft").mkdir(parents=True)
    (sp / "nvidia" / "cufft" / "bin").write_text("not a directory")
    return sp


@pytest.fixture
def dlls(monkeypatch, site):
    registry = DllRegistry()
    monkeypatch.setattr(cuda_setup, "_registered", False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "path", [str(site)])
    monkeypatch.setattr(os, "add_dll_directory", registry, raising=False)
    monkeypatch.setenv("PATH", r"C:\Windows")
    return registry


def bin_dir(site, lib):
    return str(site / "nvidia" / lib / "bin")


def test_non_windows_returns_empty(dlls, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")

    assert cuda_setup.register_cuda_dlls() == []


def test_non_windows_adds_no_dll_directory(dlls, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")

    cuda_setup.register_cuda_dlls()

    assert dlls.added == []


def test_returns_each_nvidia_bin_dir(dlls, site):
    added = cuda_setup.register_cuda_dlls()

    assert sorted(added) == [bin_dir(site, "cublas"), bin_dir(site, "cudnn")]


def test_adds_each_nvidia_bin_dir_to_dll_search(dlls, site):
    cuda_setup.register_cuda_dlls()

    assert sorted(dlls.added) == [bin_dir(site, "cublas"), bin_dir(site, "cudnn")]


def test_second_call_returns_empty(dlls):
    cuda_setup.register_cuda_dlls()

    assert cuda_setup.register_cuda_dlls() == []


def test_second_call_adds_nothing(dlls):
    cuda_setup.register_cuda_dlls()
    dlls.added.clear()

    cuda_setup.register_cuda_dlls()

    assert dlls.added == []


def test_os_error_skips_directory(dlls, site):
    dlls.refuse.add(bin_dir(site, "cublas"))

    added = cuda_setup.register_cuda_dlls()

    assert added == [bin_dir(site, "cudnn")]


def test_os_error_directory_not_added_to_path(dlls, site):
    dlls.refuse.add(bin_dir(site, "cublas"))

    cuda_setup.register_cuda_dlls()

    assert os.environ["PATH"] == bin_dir(site, "cudnn") + os.pathsep + r"C:\Windows"


def test_registered_dir_prepended_to_path(dlls, site):
    dlls.refuse.add(bin_dir(site, "cudnn"))

    cuda_setup.register_cuda_dlls()

    assert os.environ["PATH"] == bin_dir(site, "cublas") + os.pathsep + r"C:\Windows"


def test_path_entries_outside_site_packages_ignored(dlls, tmp_path, monkeypatch):
    other = tmp_path / "app"
    (other / "nvidia" / "cublas" / "bin").mkdir(parents=True)
    monkeypatch.setattr(sys, "path", [str(other)])

    assert cuda_setup.register_cuda_dlls() == []
