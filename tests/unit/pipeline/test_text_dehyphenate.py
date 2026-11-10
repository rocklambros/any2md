"""Tests for T2 — dehyphenate."""

import pytest

from any2md.pipeline import PipelineOptions, run
from any2md.pipeline import text as text_lane
from any2md.pipeline.text import dehyphenate


def test_dehyphenates_when_joined_word_appears_elsewhere():
    text = "This shows co-\noperation between teams. Successful cooperation matters.\n"
    out = dehyphenate(text, PipelineOptions())
    assert "cooperation between teams" in out


def test_preserves_genuine_compound():
    text = "We use co-pilot integration.\nThe co-pilot is reliable.\n"
    # 'copilot' (joined) does NOT appear elsewhere → keep the hyphen.
    out = dehyphenate(text, PipelineOptions())
    assert "co-pilot integration" in out


def test_does_not_dehyphenate_across_paragraphs():
    text = "co-\n\noperation"
    # Blank line between → not a wrap, don't merge.
    out = dehyphenate(text, PipelineOptions())
    assert out == text


def test_no_hyphens_is_noop():
    text = "Plain text without any hyphenation.\n"
    assert dehyphenate(text, PipelineOptions()) == text


# ---------- v1.2.1: evidence rules, run order, and hardening ----------

OPTS = PipelineOptions()


def test_keeps_hyphen_when_compound_corroborated():
    text = "Use the co-\npilot here. The co-pilot works.\n"
    assert "Use the co-pilot here." in dehyphenate(text, OPTS)


@pytest.mark.parametrize("conj", ["and", "or", "nor", "to"])
def test_suspended_hyphen_left_alone(conj):
    text = f"Both first-\n{conj} second-order effects. firstand first{conj}\n"
    assert f"first-\n{conj}" in dehyphenate(text, OPTS)


def test_uncorroborated_break_left_alone():
    text = "The inter-\nnational standard applies.\n"
    assert dehyphenate(text, OPTS) == text


def test_trailing_space_after_hyphen():
    text = "This shows co- \noperation now. Successful cooperation matters.\n"
    assert "This shows cooperation now." in dehyphenate(text, OPTS)


def test_capitalized_prefix_merges_whole_word():
    text = "The Co-\noperation clause and cooperation.\n"
    assert "The Cooperation clause" in dehyphenate(text, OPTS)


def test_word_boundary_blocks_partial_match():
    # "re"+"lease" = "release" exists, but the broken word is "Pre-lease".
    text = "The Pre-\nlease terms and the release date.\n"
    assert dehyphenate(text, OPTS) == text


def test_uppercase_next_word_left_alone():
    text = "Joint Microsoft-\nGoogle work and microsoftgoogle.\n"
    assert dehyphenate(text, OPTS) == text


def test_non_ascii_words():
    text = "Die Straß-\nenbahn fährt und die Straßenbahn hält.\n"
    assert "Die Straßenbahn fährt" in dehyphenate(text, OPTS)


def test_fenced_code_untouched():
    text = "```\nx = pre-\nprocess\nrun(preprocess)\n```\nOutside pre-\nprocess too.\n"
    out = dehyphenate(text, OPTS)
    assert "x = pre-\nprocess\n" in out
    assert "Outside preprocess too." in out


def test_t2_runs_before_t1():
    names = [s.__name__ for s in text_lane.STAGES]
    assert names.index("dehyphenate") < names.index("repair_line_wraps")


@pytest.mark.parametrize(
    "body, expected",
    [
        (  # corroborated merge (the original bug: came out "co- operation")
            "This shows co-\noperation between teams. Successful cooperation matters.",
            "This shows cooperation between teams.",
        ),
        (  # corroborated compound keeps its hyphen
            "We rely on the co-\npilot for routing. The co-pilot decides.",
            "We rely on the co-pilot for routing.",
        ),
        (  # suspended hyphen keeps its space
            "Both first-\nand second-order effects matter.",
            "Both first- and second-order effects matter.",
        ),
        (  # no evidence: same output as before v1.2.1, no invented word
            "The inter-\nnational standard applies here.",
            "The inter- national standard applies here.",
        ),
    ],
)
def test_text_lane_pipeline(body, expected):
    out, _ = run(f"# T\n\n{body}\n", "text", OPTS)
    assert expected in out
