"""Integration tests: HTML/URL bodies carry exactly one H1 (v1.2.0).

Fixtures are synthetic and saved under tests/fixtures/docs/; no test
here makes a network call. Each fixture models a page shape seen on
live blogs:

- web_h1_in_hero.html: <h1> in a hero <section> outside the <article>
  trafilatura selects, so trafilatura drops it. og:title differs from
  the visible heading.
- web_page.html: <h1> inside <main>, kept by trafilatura.
- web_bold_title_first_line.html: <h1> dropped, and the first body
  line repeats the title in bold.
- web_no_title.html: no <h1>, no <title>, no og:title.
"""

from __future__ import annotations

import re

import yaml

import any2md.converters.html as html_mod
from any2md.converters import collected_warnings, reset_warnings
from any2md.converters.html import convert_html
from any2md.frontmatter import compute_content_hash
from any2md.pipeline import PipelineOptions

_H1_RE = re.compile(r"^# (.*)$", re.MULTILINE)


def _convert(path, out_dir):
    reset_warnings()
    ok = convert_html(path, out_dir, options=PipelineOptions(), force=True)
    assert ok
    text = next(out_dir.glob("*.md")).read_text(encoding="utf-8")
    end = text.index("\n---\n", 4)
    fm = yaml.safe_load(text[4:end])
    body = text[end + 5 :]
    if body.startswith("\n"):
        body = body[1:]
    return text, fm, body


def _validator_warnings():
    return [w for w in collected_warnings() if w.startswith("validator:")]


# (a) trafilatura drops the <h1>
def test_dropped_h1_restored_from_visible_heading(fixture_dir, tmp_output_dir):
    _, fm, body = _convert(fixture_dir / "web_h1_in_hero.html", tmp_output_dir)
    assert _H1_RE.findall(body) == ["A Read-Only Account Is All It Takes"]
    assert body.startswith("# A Read-Only Account Is All It Takes\n\n")
    assert fm["title"] == "A Read-Only Account Is All It Takes"
    assert fm["seo_title"] == "Gateway CVE: Exploited One Day After Disclosure"
    assert _validator_warnings() == []


def test_body_headings_keep_their_levels(fixture_dir, tmp_output_dir):
    _, _, body = _convert(fixture_dir / "web_h1_in_hero.html", tmp_output_dir)
    levels = [len(m) for m in re.findall(r"^(#{1,6}) ", body, re.MULTILINE)]
    assert levels == [1, 2, 2]


def test_derived_fields_computed_from_final_body(fixture_dir, tmp_output_dir):
    _, fm, body = _convert(fixture_dir / "web_h1_in_hero.html", tmp_output_dir)
    assert fm["content_hash"] == compute_content_hash(body)
    assert fm["token_estimate"] == -(-len(body) // 4)  # ceil(len / 4)
    assert fm["recommended_chunk_level"] == "h2"
    # abstract_for_rag is the first prose paragraph, never the H1.
    abstract = fm["abstract_for_rag"]
    assert abstract.startswith("Attackers increasingly target AI gateways")
    assert "Read-Only Account" not in abstract


# (b) trafilatura keeps the <h1>
def test_kept_h1_not_duplicated(fixture_dir, tmp_output_dir):
    _, fm, body = _convert(fixture_dir / "web_page.html", tmp_output_dir)
    assert _H1_RE.findall(body) == ["Test Article: Markdown Conversion"]
    assert fm["title"] == "Test Article: Markdown Conversion"
    assert "seo_title" not in fm
    assert _validator_warnings() == []


# (c) first body line repeats the title in bold
def test_bold_title_line_promoted_not_duplicated(fixture_dir, tmp_output_dir):
    _, fm, body = _convert(
        fixture_dir / "web_bold_title_first_line.html", tmp_output_dir
    )
    assert _H1_RE.findall(body) == ["Join the Prompt Jar Contest"]
    assert "**Join the Prompt Jar Contest**" not in body
    assert body.count("Join the Prompt Jar Contest") == 1
    assert fm["title"] == "Join the Prompt Jar Contest"
    assert "seo_title" not in fm
    assert _validator_warnings() == []


# (d) no title anywhere
def test_no_title_no_crash_no_empty_heading(fixture_dir, tmp_output_dir):
    _, fm, body = _convert(fixture_dir / "web_no_title.html", tmp_output_dir)
    assert not re.search(r"^#\s*$", body, re.MULTILINE)
    assert _H1_RE.findall(body) == []
    assert fm["title"]  # filename fallback, never empty
    assert "seo_title" not in fm


def test_url_path_gets_same_treatment(fixture_dir, tmp_output_dir, monkeypatch):
    """convert_url hands fetched HTML to convert_html via html_content."""
    monkeypatch.setattr(html_mod, "_http_last_modified", lambda _url: None)
    html = (fixture_dir / "web_h1_in_hero.html").read_text(encoding="utf-8")
    reset_warnings()
    ok = convert_html(
        None,
        tmp_output_dir,
        options=PipelineOptions(),
        force=True,
        source_url="https://example.com/post/gateway",
        html_content=html,
    )
    assert ok
    text = (tmp_output_dir / "example_com_post_gateway.md").read_text("utf-8")
    body = text[text.index("\n---\n", 4) + 5 :]
    assert _H1_RE.findall(body) == ["A Read-Only Account Is All It Takes"]
    assert _validator_warnings() == []


def test_output_is_byte_identical_across_runs(fixture_dir, tmp_path):
    outs = []
    for run in ("one", "two"):
        out_dir = tmp_path / run
        out_dir.mkdir()
        text, _, _ = _convert(fixture_dir / "web_h1_in_hero.html", out_dir)
        outs.append(text)
    assert outs[0] == outs[1]
