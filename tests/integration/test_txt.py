"""Integration test: TXT converter end-to-end."""

import yaml

from any2md.converters.txt import convert_txt
from any2md.pipeline import PipelineOptions


def test_txt_end_to_end_writes_sage_compat_output(fixture_dir, tmp_output_dir):
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


_BODY = "The co-\noperation was good. Our cooperation helps.\n"


def _convert(tmp_path, tmp_output_dir, name: str, text: str) -> tuple[dict, str]:
    src = tmp_path / name
    src.write_text(text, encoding="utf-8")
    assert convert_txt(src, tmp_output_dir, options=PipelineOptions(), force=True)
    out = next(tmp_output_dir.glob("*.md")).read_text(encoding="utf-8")
    end = out.index("\n---\n", 4)
    return yaml.safe_load(out[4:end]), out[end + 5 :]


def test_short_first_line_becomes_h1_and_title(tmp_path, tmp_output_dir):
    # T10 used to drop this line as a web-extraction fragment, so it was
    # neither the title nor body text.
    fm, body = _convert(tmp_path, tmp_output_dir, "doc.txt", "Title Line\n\n" + _BODY)
    assert fm["title"] == "Title Line"
    assert body.lstrip().startswith("# Title Line\n")
    assert "The cooperation was good. Our cooperation helps." in body


def test_first_line_without_blank_line_stays_in_body(tmp_path, tmp_output_dir):
    _fm, body = _convert(tmp_path, tmp_output_dir, "doc.txt", "Title Line\n" + _BODY)
    assert "Title Line" in body
    assert "cooperation was good" in body


def test_all_caps_first_line_becomes_h1_and_title(tmp_path, tmp_output_dir):
    fm, body = _convert(tmp_path, tmp_output_dir, "doc.txt", "TITLE LINE\n\n" + _BODY)
    assert fm["title"] == "Title Line"
    assert body.lstrip().startswith("# Title Line\n")


def test_long_first_line_becomes_h1_and_title(tmp_path, tmp_output_dir):
    title = "A Much Longer Title Line for This Plain Text Document"
    fm, body = _convert(tmp_path, tmp_output_dir, "doc.txt", title + "\n\n" + _BODY)
    assert fm["title"] == title
    assert body.lstrip().startswith(f"# {title}\n")


def test_first_line_matching_filename_is_kept_once(tmp_path, tmp_output_dir):
    fm, body = _convert(
        tmp_path, tmp_output_dir, "title_line.txt", "Title Line\n\n" + _BODY
    )
    assert fm["title"] == "Title Line"
    assert body.count("Title Line") == 1


def test_lowercase_short_first_line_stays_in_body(tmp_path, tmp_output_dir):
    # Not a title by the structurizer's rules, so it stays a paragraph.
    fm, body = _convert(tmp_path, tmp_output_dir, "doc.txt", "doc\n\n" + _BODY)
    assert fm["title"] == "doc"
    assert "doc" in body.split()
