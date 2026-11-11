"""Tests for Docling detection and install-hint helper."""

import warnings

import pytest

from any2md._docling import (
    DoclingWarningCapture,
    has_docling,
    install_hint,
    INSTALL_HINT_MSG,
)


def test_has_docling_returns_bool():
    result = has_docling()
    assert isinstance(result, bool)


def test_install_hint_msg_contains_pip_command():
    assert "pip install" in INSTALL_HINT_MSG
    assert "any2md[high-fidelity]" in INSTALL_HINT_MSG


def test_install_hint_emits_once_per_process(capsys):
    # Reset module-level rate-limit flag for the test
    from any2md import _docling

    _docling._hint_emitted.clear()
    install_hint()
    install_hint()  # second call should be silent
    captured = capsys.readouterr()
    # The hint should appear in stderr exactly once
    assert captured.err.count("pip install") == 1


# ---- DoclingWarningCapture ---------------------------------------------


def _warn(message, category=UserWarning):
    warnings.warn(message, category, stacklevel=1)


def test_warning_capture_records_instead_of_printing(capsys):
    with DoclingWarningCapture() as cap:
        _warn("Provenance bbox coordinate t on page 3 is outside page bounds")

    assert cap.messages == [
        "UserWarning: Provenance bbox coordinate t on page 3 is outside page bounds"
    ]
    assert capsys.readouterr().err == ""


def test_warning_capture_sanitizes_and_counts_repeats():
    with DoclingWarningCapture() as cap:
        for _ in range(3):
            _warn("bad \x1b[31mbox\nsecond line")

    assert cap.messages == ["UserWarning: bad [31mbox second line"] * 3


def test_warning_capture_restores_the_callers_filters():
    with warnings.catch_warnings():
        warnings.simplefilter("error", UserWarning)
        before = list(warnings.filters)

        with DoclingWarningCapture() as cap:
            # Inside, the caller's "error" filter does not abort the conversion.
            _warn("inside")

        assert list(warnings.filters) == before
        assert cap.messages == ["UserWarning: inside"]
        with pytest.raises(UserWarning):
            _warn("outside")


def test_warning_capture_reissues_library_deprecations():
    with pytest.warns(DeprecationWarning, match="old API"):
        with DoclingWarningCapture() as cap:
            _warn("old API", DeprecationWarning)
            _warn("counted")

    assert cap.messages == ["UserWarning: counted"]
