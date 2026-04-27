"""Integration test: TXT converter end-to-end."""

import yaml

from any2md.converters.txt import convert_txt
from any2md.pipeline import PipelineOptions


def test_txt_end_to_end_writes_ssrm_compat_output(fixture_dir, tmp_output_dir):
    ok = convert_txt(
        fixture_dir / "ligatures_and_softhyphens.txt",
        tmp_output_dir,
        options=PipelineOptions(),
        force=True,
    )
    assert ok
    out_files = list(tmp_output_dir.glob("*.md"))
    assert len(out_files) == 1
    out = out_files[0].read_text(encoding="utf-8")
    # Frontmatter shape
    assert out.startswith("---\n")
    end = out.index("\n---\n", 4)
    fm = yaml.safe_load(out[4:end])
    body = out[end + 5 :]
    assert fm["status"] == "draft"
    assert fm["extracted_via"] == "heuristic"
    assert fm["source_file"].endswith(".txt")
    assert fm["content_hash"]
    # Cleanup applied
    assert "­" not in body  # soft hyphen stripped
    assert "ﬁ" not in body  # ligature expanded
    assert "“" not in body  # smart quote normalized
