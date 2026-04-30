#!/usr/bin/env bash
# scripts/validate-phase1.sh
# Manual validation against test_docs/ before tagging 1.0.0a1.
# This script is not run in CI -- it's for the maintainer.

set -euo pipefail

OUT_DIR="$(mktemp -d)"
echo "Output directory: $OUT_DIR"

run_one() {
    local input="$1"
    echo "=== $input ==="
    python -m any2md -o "$OUT_DIR" --force "$input" || {
        echo "FAIL: $input" >&2
        return 1
    }
}

[[ -f test_docs/COMP4441-FinalProject-SafetyAlignmentEffectiveness-LLM-RockLambros.docx ]] \
    && run_one "test_docs/COMP4441-FinalProject-SafetyAlignmentEffectiveness-LLM-RockLambros.docx"

[[ -f "test_docs/ISO_IEC_27002_2022(en).pdf" ]] \
    && run_one "test_docs/ISO_IEC_27002_2022(en).pdf"

run_one "https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing"

echo
echo "Outputs:"
ls -la "$OUT_DIR"
echo
echo "Inspect each for: SAGE frontmatter, content_hash present, body NFC + LF, no garbled chars."
