"""Tests for URL credential + sensitive query-param scrubbing."""

from __future__ import annotations

from any2md.utils import scrub_url_credentials, url_to_filename


def test_strips_userinfo():
    scrubbed, warns = scrub_url_credentials(
        "https://alice:s3cret@example.com/blog/post"
    )
    assert scrubbed == "https://example.com/blog/post"
    assert warns == ["credentials"]


def test_no_userinfo_round_trips():
    scrubbed, warns = scrub_url_credentials("https://example.com/blog/post?q=hi")
    assert scrubbed == "https://example.com/blog/post?q=hi"
    assert warns == []


def test_strips_sensitive_query_param():
    scrubbed, warns = scrub_url_credentials("https://example.com/path?api_key=abc&q=hi")
    assert scrubbed == "https://example.com/path?q=hi"
    assert warns == ["api_key"]


def test_strips_multiple_sensitive_params():
    url = "https://example.com/?token=t&password=p&q=hi"
    scrubbed, warns = scrub_url_credentials(url)
    assert "token=t" not in scrubbed
    assert "password=p" not in scrubbed
    assert scrubbed.endswith("q=hi")
    assert set(warns) == {"token", "password"}


def test_strips_userinfo_and_query_together():
    url = "https://user:pw@example.com/?Token=xyz&aws_session_token=stf"
    scrubbed, warns = scrub_url_credentials(url)
    assert "user" not in scrubbed and "pw" not in scrubbed
    assert "xyz" not in scrubbed and "stf" not in scrubbed
    assert "credentials" in warns
    assert any(w == "Token" or w == "token" for w in warns)
    assert any(w.lower() == "aws_session_token" for w in warns)


def test_ipv6_brackets_preserved():
    scrubbed, warns = scrub_url_credentials("https://user:pw@[::1]:8080/x")
    assert scrubbed == "https://[::1]:8080/x"
    assert warns == ["credentials"]


def test_ipv6_no_userinfo_unchanged():
    scrubbed, warns = scrub_url_credentials("https://[::1]:8080/x?q=1")
    assert scrubbed == "https://[::1]:8080/x?q=1"
    assert warns == []


def test_url_to_filename_does_not_leak_userinfo():
    fn = url_to_filename("https://alice:s3cret@example.com/blog/post")
    assert "alice" not in fn
    assert "s3cret" not in fn
    assert fn == "example_com_blog_post.md"


def test_case_insensitive_param_match():
    scrubbed, warns = scrub_url_credentials("https://example.com/?API_KEY=abc")
    assert scrubbed == "https://example.com/"
    assert warns == ["API_KEY"]


def test_unknown_param_passes_through():
    scrubbed, warns = scrub_url_credentials("https://example.com/?username=alice&q=hi")
    # username is operator-controlled identity, not a credential — passes through
    assert scrubbed == "https://example.com/?username=alice&q=hi"
    assert warns == []
