"""Unit tests for secretstore: DPAPI protection of stored API keys.

Runs against the real Windows DPAPI; ctypes is only faked to reach the branch
where CryptProtectData reports failure.
"""
import ctypes

import pytest

import secretstore


class _FailingCrypt32:
    """Stand-in for crypt32 whose DPAPI calls always report failure (0)."""

    @staticmethod
    def CryptProtectData(*_args):
        return 0

    @staticmethod
    def CryptUnprotectData(*_args):
        return 0


def test_proteger_adds_dpapi_prefix():
    result = secretstore.proteger("sk-ant-123")

    assert result.startswith("dpapi:")


def test_proteger_does_not_leak_plaintext():
    result = secretstore.proteger("sk-ant-123")

    assert "sk-ant-123" not in result


@pytest.mark.parametrize("plaintext", ["sk-ant-123", "contraseña-ñ-🔑", "x"])
def test_revelar_recovers_protected_value(plaintext):
    protected = secretstore.proteger(plaintext)

    result = secretstore.revelar(protected)

    assert result == plaintext


def test_proteger_leaves_already_protected_value_unchanged():
    protected = secretstore.proteger("sk-ant-123")

    result = secretstore.proteger(protected)

    assert result == protected


@pytest.mark.parametrize("empty", ["", None])
def test_proteger_passes_empty_value_through(empty):
    result = secretstore.proteger(empty)

    assert result == empty


@pytest.mark.parametrize("empty", ["", None])
def test_revelar_passes_empty_value_through(empty):
    result = secretstore.revelar(empty)

    assert result == empty


def test_revelar_passes_plaintext_through():
    result = secretstore.revelar("sk-legacy-plain")

    assert result == "sk-legacy-plain"


@pytest.mark.parametrize("garbage", [
    "dpapi:",                              # empty payload
    "dpapi:abc",                           # invalid base64 padding
    "dpapi:!!!***",                        # no base64 characters at all
    "dpapi:Z2FyYmFnZSBieXRlcyBoZXJl",      # valid base64, not a DPAPI blob
])
def test_revelar_returns_empty_string_for_undecryptable_payload(garbage):
    result = secretstore.revelar(garbage)

    assert result == ""


def test_proteger_returns_plaintext_when_encoding_fails():
    """A lone surrogate cannot be UTF-8 encoded; the value must not be lost."""
    result = secretstore.proteger("key-\ud800")

    assert result == "key-\ud800"


def test_proteger_returns_plaintext_when_dpapi_fails(monkeypatch):
    monkeypatch.setattr(ctypes.windll, "crypt32", _FailingCrypt32())

    result = secretstore.proteger("sk-ant-123")

    assert result == "sk-ant-123"


@pytest.mark.parametrize("value, expected", [
    ("dpapi:abc", True),
    ("sk-plain", False),
    ("", False),
    (None, False),
])
def test_esta_protegido(value, expected):
    result = secretstore.esta_protegido(value)

    assert result is expected
