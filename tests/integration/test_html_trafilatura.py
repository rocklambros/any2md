"""Integration test: HTML converter end-to-end."""

import yaml

from any2md.converters.html import convert_html
from any2md.pipeline import PipelineOptions


def test_html_local_file_emits_v1_frontmatter(fixture_dir, tmp_output_dir):
    ok = convert_html(
        fixture_dir / "web_page.html",
        tmp_output_dir,
        options=PipelineOptions(),
        force=True,
    )
    assert ok
    out_files = list(tmp_output_dir.glob("*.md"))
    assert len(out_files) == 1
    out = out_files[0].read_text(encoding="utf-8")
    end = out.index("\n---\n", 4)
    fm = yaml.safe_load(out[4:end])
    body = out[end + 5 :]
    assert fm["status"] == "draft"
    assert "trafilatura" in fm["extracted_via"]
    # boilerplate stripped
    assert "Sidebar noise" not in body
    assert "Site footer" not in body
    # body content present
    assert "Test Article" in fm["title"] or "Test Article" in body
