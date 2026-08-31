# Implementation Defender — Staged CI / Lock Changes

**Review boundary**: only `git diff --cached` at 2026-07-16. Unstaged retrieval-frontier
changes were excluded. No implementation file was modified by this review.

## Gate Outcome

**BLOCKED for final merge/push, but no new Critical/High implementation defect was found.**

The staged implementation is locally defensible: the installer fixes the target interpreter,
uses frozen hashed exports, scrubs competing source variables, applies a unique first-index policy,
preinstalls the hashed build allowlist, disables build isolation for runtime sync, and enforces a
total timeout (`scripts/sync_locked_deps.sh:75-98,108-139,143-188`). Docker consumes the root npm
workspace lock with an exact Node image and verifies the installed sanitizer and Python image
closure (`Dockerfile:11-22,25-45`; `.github/workflows/docker-api-only.yml`).

The remaining blocker is evidence closure, not a newly observed code failure. The governing
tracking matrix explicitly requires implementation commit fields and applicable same-SHA remote
cold/warm evidence before Critical/High findings can be closed
(`docs/specs/ci-index-routing/review/tracking.md:7-23`). Those fields are still pending, including
three cold runs and runner/image metadata for the hosted workflows. The web sanitizer findings also
remain open until the implementation commit is recorded
(`docs/specs/web-sanitizer-lock-refresh/review/tracking.md:7-11,24-25`).

## Critical / High Disposition

| Findings | Defender decision | Evidence and status |
|---|---|---|
| CIR F-01, F-02 | **accepted** | Explicit target/source/hash controls and torch-less profile/image gates are present locally; keep open until commit and applicable remote evidence are recorded. |
| CIR F-03, N-03, N-07, N-08 | **accepted** | Cold-mode wiring, 300/600 s sync bounds, 1200 s Docker budget, 20/30 minute job bounds, and environment metadata logging exist. Same-SHA hosted cold/warm measurements are still pending, so closure is rejected for now. |
| CIR N-01, N-02, N-04, N-05 | **accepted** | `--python <venv>/bin/python`, hostile source scrubbing, uv 0.11.8 pins, and non-root lock tuple regression checks directly address the findings. Local contract tests pass. |
| CIR N-06 | **accepted with the documented alternative** | The literal isolated-build approach is not required: a frozen hashed `ci-build` allowlist is installed first and runtime sync uses `--no-build-isolation`; the undeclared-build-dependency regression proves no fallback resolution. |
| WSR F-01 | **accepted** | Exact `node:20.20.2-bookworm-slim`, root workspace lock, `npm ci`, installed DOMPurify gate, and Docker path routing address the production-builder defect. Keep open until the implementation commit is recorded. |
| WSR F-02..F-05 | **accepted** | DOMPurify 3.4.12 has official HTTPS provenance and SHA-512 integrity; Playwright injects script/img/event-handler/javascript-URL payloads and asserts removal plus non-execution (`tests/e2e_ui/chat.spec.ts:86-133`). Archived browser evidence is 20 passed; commit/remote workflow evidence remains pending. |

**Rejected Critical/High findings: none.** I reject only premature closure of the accepted findings;
the staged controls are sufficient for remote validation, not sufficient for the repository's final
merge gate without the required evidence records.

## Residual Medium / Low Notes

1. **Medium — controlled frontend toolchain is incomplete in hosted workflows.** The sanitizer
   requirement fixes Node 20.20.2/npm 10.8.2 (`requirements.md:22-23`), while `e2e-ui.yml:49-53` and
   `lock-consistency.yml:45-49` request floating Node `20` and do not pin npm. Docker and lock
   generation are exact, so this is not a current production escape, but audit/install provenance
   can drift on hosted runners. Pin both versions before claiming fully controlled audit evidence.
2. **Medium — unrelated lock metadata drift.** `package-lock.json` removes `libc: ["glibc"]` from the
   Rollup GNU optional package. Package version/resolved/integrity tuples do not drift, and the
   Docker builder is explicitly Debian/glibc, so this is not High; nevertheless it should be
   explained or regenerated with the declared npm 10.8.2 toolchain.
3. **Low — remediation text is not reproducible enough.** `lock-consistency.yml:55-60` recommends
   generic `npm install`; it should name the pinned Node/npm versions, empty userconfig, official
   registry, and workspace-root command.
4. **Low — reused venv interpreter is not revalidated.** The installer only creates a venv when
   `bin/python` is absent (`sync_locked_deps.sh:135-139`). Hosted jobs and Docker begin clean, so the
   reviewed target paths are not triggerable; a future reusable/self-hosted path should assert the
   requested Python major/minor.

## Verification Executed in This Review

- `20 passed in 5.69s` for the three staged contract suites:
  `test_ci_dependency_routing.py`, `test_web_sanitizer_lock_refresh.py`, and
  `test_api_only_docker_contract.py`.
- `bash -n scripts/sync_locked_deps.sh`: passed.
- `git diff --cached --check`: passed.

This defender turn did not rerun the full backend matrix, Docker build, or Playwright. Existing
tracking records local Docker and Playwright success, but the final gate must rely on fresh
same-commit CI/remote evidence before pushing `main`.
