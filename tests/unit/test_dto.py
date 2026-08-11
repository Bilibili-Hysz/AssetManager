"""Unit tests for LAN response DTO coercion helpers."""
import pytest

from AssetsManager.lan.dto import _as_int


def test_as_int_accepts_int():
    assert _as_int(42) == 42


def test_as_int_rounds_floats():
    assert _as_int(3.7) == 4
    assert _as_int(-2.2) == -2


def test_as_int_parses_numeric_strings():
    assert _as_int(" 42 ") == 42
    assert _as_int("3.7") == 4


def test_as_int_rejects_none_and_bool():
    with pytest.raises(ValueError):
        _as_int(None)
    with pytest.raises(ValueError):
        _as_int(True)


def test_as_int_rejects_non_numeric_string():
    with pytest.raises(ValueError):
        _as_int("abc")


def test_as_int_rejects_infinity():
    with pytest.raises(ValueError):
        _as_int(float("inf"))
    with pytest.raises(ValueError):
        _as_int(float("-inf"))


def test_as_int_rejects_nan():
    with pytest.raises(ValueError):
        _as_int(float("nan"))
