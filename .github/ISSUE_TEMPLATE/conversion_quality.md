---
name: Conversion quality
about: Report incorrect output (garbled text, lost tables, broken layout)
title: ''
labels: 'conversion-quality'
---

Conversion-quality reports are unfixable without a concrete snippet of the
bad output and a description of what the source looks like at that
location. Please fill in every section below.

## Source

- **Format:** PDF / DOCX / HTML / TXT / URL (delete the others)
- **File size:** (e.g. 2.4 MB, 350 KB)
- **Docling version:** output of `pip show docling | grep Version`, or
  "not installed" if you're on the lightweight install path.
- **any2md version:** output of `any2md --version` or `pip show any2md`.

## Command run

The full `any2md ...` command, including all flags. Paste it verbatim:

```
any2md ...
```

## Bad output snippet

A 5-line snippet of the produced Markdown that demonstrates the artifact.
Pick the smallest excerpt that still shows the problem:

```markdown
paste 5 lines of the bad output here
```

## What the source looks like at that location

Describe what the corresponding region of the input file looks like. If
the source isn't confidential, paste a text excerpt or attach a
screenshot (cropped to the relevant region):

```
paste source text here, or describe the layout / attach a screenshot
```

## What the output should look like

In your judgment, what's the correct Markdown for that region? Write it
out as you'd expect it:

```markdown
expected output here
```

## Additional context

Anything else worth knowing — does the artifact only appear with certain
flags, only with Docling, only on the fallback path, only on this one
file, only on multi-column pages, etc.
