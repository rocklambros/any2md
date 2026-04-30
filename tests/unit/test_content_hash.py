"""Tests for content_hash determinism (SAGE §5.1)."""

from any2md.frontmatter import compute_content_hash


def test_hash_is_64_lowercase_hex():
    h = compute_content_hash("hello\n")
    assert len(h) == 64
    assert h == h.lower()
    assert all(c in "0123456789abcdef" for c in h)


def test_hash_is_lf_normalized():
    crlf = compute_content_hash("a\r\nb\r\n")
    lf = compute_content_hash("a\nb\n")
    assert crlf == lf


def test_hash_is_nfc_normalized():
    decomposed = compute_content_hash("café")
    composed = compute_content_hash("café")
    assert decomposed == composed


def test_hash_differs_on_content_change():
    a = compute_content_hash("alpha")
    b = compute_content_hash("beta")
    assert a != b


def test_hash_stable_across_calls():
    text = "stable content\n"
    assert compute_content_hash(text) == compute_content_hash(text)


def test_known_vector_empty_string():
    # SHA-256 of empty string
    assert compute_content_hash("") == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )
