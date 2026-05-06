# Security Policy

## Supported versions

| Version | Status |
|---|---|
| 1.0.x   | ✅ Supported (current stable). Patch releases for security and quality fixes are published as needed. |
| 0.7.x   | ⚠️ Receives critical security fixes only until 2026-10-26 (six months after the v1.0.0 GA on 2026-04-26). |
| < 0.7   | ❌ Not supported. Please upgrade. |

## Reporting a vulnerability

**Please do not file public issues for security vulnerabilities.** Public
disclosure before a fix is published puts users at risk.

Email security disclosures to **rock@rockcyber.com** with the subject line
`any2md security disclosure`. Encrypted email is welcome — request a
public key in your initial message and one will be provided.

Include in your report:

- A description of the issue and the affected component.
- Affected version(s) — e.g., `pip show any2md` output, or commit SHA.
- Reproduction steps (smallest possible repro is ideal).
- Any proof-of-concept (please redact sensitive data).
- Whether you intend to publish your own write-up; if so, a proposed
  embargo date so we can coordinate.

### Response timeline

- **Acknowledgement** within 5 business days.
- **Triage and severity assessment** within 10 business days.
- **Critical issues** (remote code execution, data exfiltration via
  crafted input, supply-chain compromise of a published wheel): patched
  and released within 30 days of confirmation, with a coordinated public
  advisory.
- **High** (denial-of-service, information disclosure with limited blast
  radius): patched within 60 days.
- **Medium / low** issues are tracked in private until a fix lands in a
  scheduled release, then disclosed publicly via the GitHub Security
  Advisories page.

## Scope

In scope:

- The `any2md` library and CLI.
- The published wheels and sdists on PyPI.
- The release pipeline (`.github/workflows/publish.yml`) and any
  side-effects of running the workflow.
- The default conversion pipeline (PDF / DOCX / HTML / URL / TXT) and
  the optional Docling backend integration.
- The arxiv API enrichment path (network call + XML parsing).
- The SSRF guards in the URL fetcher.

Out of scope:

- Vulnerabilities in third-party dependencies (please file directly with
  the upstream — Docling, PyMuPDF, mammoth, trafilatura, BeautifulSoup,
  lxml, etc.). We monitor upstream advisories via Dependabot.
- Issues that require local filesystem access already granted to the
  running Python process.
- Local timing attacks against your own machine.
- Content correctness issues in converted Markdown (those are
  conversion-quality reports — please use the
  [Conversion quality issue template](.github/ISSUE_TEMPLATE/conversion_quality.md)
  instead).

## Hardening reference

If you operate any2md in a hardened environment:

- Pass `--no-arxiv-lookup` to disable the arxiv API call.
- Pass `--max-file-size` with a budget appropriate for your workload.
- Run conversions in a sandbox that cannot reach private networks
  (the SSRF guard validates resolved IPs, but defense in depth is best).
- Pin `any2md` and its extras (`any2md[high-fidelity]==<exact-version>`)
  to a verified version and audit the lockfile.

## Disclosure history

No publicly disclosed vulnerabilities to date. Future advisories will
appear at https://github.com/rocklambros/any2md/security/advisories.

## Trust boundaries

`any2md` is an operator-trusted CLI distributed via PyPI for desktop and CI use.

**Trusted:** the operator, their filesystem, their `--output-dir`, and the Python interpreter they invoke. CLI flags and `--meta key=val` arguments are operator-controlled.

**Untrusted:**
- URLs passed to `any2md` (may resolve to internal IPs, redirect, or carry credentials in userinfo/query).
- Documents (PDF/DOCX/HTML) passed for conversion (may embed crafted images, control characters, malicious metadata).
- `.any2md.toml` config files discovered via cwd-walking (an attacker who can drop a file in any ancestor directory can inject frontmatter overrides).
- HTTP responses from URLs (may carry hostile redirects, oversized bodies, control characters in headers).

**Out of scope:** multi-tenant service hosting; running `any2md` against attacker-supplied output directories; supply-chain compromise of pinned dependencies; protection against an operator who has chosen `--output-dir` pointing at a shared/symlinked directory.

## Dependency-drift policy

If `pip-audit` reports a NEW HIGH/CRITICAL vulnerability between baseline and release-cut, the policy is:

1. Bump the dep within its compatible range (regenerate `.devcontainer/requirements.lock` and `requirements.txt`) and re-cut the rc.
2. If no compatible fix exists, document in CHANGELOG `## Known issues` and ship only if the codepath is mitigated by other code (e.g., XXE blocked by `defusedxml`).
3. If neither is possible, hold the release until upstream lands a fix.
