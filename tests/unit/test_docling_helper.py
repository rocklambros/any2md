"""Tests for Docling detection and install-hint helper."""

from any2md._docling import (
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

    _docling._hint_emitted = False
    install_hint()
    install_hint()  # second call should be silent
    captured = capsys.readouterr()
    # The hint should appear in stderr exactly once
    assert captured.err.count("pip install") == 1
