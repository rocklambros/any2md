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

# Where docling-core raises its bbox warning. The capture counts only
# warnings raised from Docling's own packages.
_DOCLING_FILE = "/venv/lib/python3.12/site-packages/docling_core/types/doc/document.py"


def _warn(message, category=UserWarning, filename=_DOCLING_FILE):
    """Raise a warning as if from ``filename``, the way Docling's code would."""
    module = "docling_core.types.doc.document" if "docling" in filename else "torch.nn"
    warnings.warn_explicit(message, category, filename, 333, module=module)


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
        shown_before = warnings.showwarning

        with DoclingWarningCapture() as cap:
            # Inside, the caller's "error" filter does not abort the conversion.
            _warn("inside")

        assert list(warnings.filters) == before
        assert warnings.showwarning is shown_before
        assert cap.messages == ["UserWarning: inside"]
        with pytest.raises(UserWarning):
            _warn("outside")


def test_uncounted_categories_go_through_the_callers_machinery_untouched():
    """A deprecation reaches the caller's own handling during the
    conversion, with its own file and line, and nothing is replayed after."""
    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always")
        with DoclingWarningCapture() as cap:
            _warn("old API", DeprecationWarning)
            _warn("counted")
            during = [(w.category, w.filename) for w in seen]

    assert during == [(DeprecationWarning, _DOCLING_FILE)]
    assert [(w.category, w.filename) for w in seen] == during
    assert cap.messages == ["UserWarning: counted"]


def test_error_filter_cannot_fail_a_conversion_after_it_succeeds():
    """With -W error, leaving the capture raises nothing."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with DoclingWarningCapture() as cap:
            _warn("counted, not raised")

    assert cap.messages == ["UserWarning: counted, not raised"]


def test_warnings_from_other_libraries_are_not_counted():
    """torch, transformers, numpy, or PIL warnings during model loading or
    conversion are not document problems. They meet the caller's own
    filters untouched."""
    torch_file = "/venv/lib/python3.12/site-packages/torch/nn/modules/module.py"
    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always")
        with DoclingWarningCapture() as cap:
            _warn("weights loaded in float16", UserWarning, filename=torch_file)
            _warn("bbox outside page")

    assert cap.messages == ["UserWarning: bbox outside page"]
    assert [(w.category, w.filename) for w in seen] == [(UserWarning, torch_file)]


def test_a_caller_error_filter_still_applies_to_other_libraries():
    torch_file = "/venv/lib/python3.12/site-packages/torch/nn/modules/module.py"
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with DoclingWarningCapture():
            with pytest.raises(UserWarning):
                _warn("not ours", UserWarning, filename=torch_file)


def test_notes_join_the_counted_messages():
    cap = DoclingWarningCapture()
    with cap:
        _warn("first")
    cap.note("alt text: could not read the package")

    assert cap.messages == [
        "UserWarning: first",
        "alt text: could not read the package",
    ]
