# sdlc-templates — Standardized SDLC for all my projects

The **single source of truth** for the build/test/release process across every
repo. The pipeline rules live here **once**; each project references them in a few
lines. Fix or improve the pipeline here, and every project picks it up on its next
run — no per-project edits.

---

## 1. The big picture

```
┌──────────────────────────────────────────────────────────┐
│  sdlc-templates  (this repo — the rules, defined ONCE)     │
│    • .github/workflows/standard-sdlc.yml  → CI pipeline    │
│    • .github/workflows/release.yml        → release pipeline│
│    pinned at tag @v1                                        │
└───────────────┬───────────────────────┬──────────────────┘
                │ referenced by          │ seeds new repos
                ▼                        ▼
┌────────────────────────┐   ┌──────────────────────────────┐
│ every project repo      │   │ project-template              │
│  • ci.yml (5-line caller)│  │  (GitHub "template" repo)     │
│  • release.yml (caller)  │  │  new repos start compliant    │
│  • Makefile (auto-detect)│  │                                │
└────────────────────────┘   └──────────────────────────────┘
```

- **sdlc-templates** (this repo, public) — the reusable workflows.
- **project-template** — a GitHub *template repo*; new projects are created from
  it and are born wired into the pipeline.

---

## 2. The two pipelines

Different questions, different triggers.

```
CI PIPELINE        trigger: push to feature/** or a pull request
                   question: "Is this change safe?"   (runs constantly)

   push ──► ┌─ lint ──────┐
            ├─ format ────┤
            ├─ typecheck ─┤  these run IN PARALLEL
            ├─ unit-tests ┼─ integration-tests   (waits for unit-tests)
            ├─ secret-scan┤
            └─ dep-scan ──┘
                  lint + typecheck + format ──► build
                  (sast / CodeQL is opt-in)

RELEASE PIPELINE   trigger: pushing a version tag (vMAJOR.MINOR.PATCH)
                   question: "Publish this version"  (runs deliberately)

   git tag v1.0.0 ──► build ──► GitHub Release + auto notes (+ artifacts)
```

Jobs with no `needs:` run in parallel; `needs:` creates a dependency. That DAG is
the only thing the pipeline "designs" — GitHub schedules the concurrency.

---

## 3. Start a NEW project (born compliant)

```bash
gh repo create my-project --private --template manaksu/project-template --clone
# or use the shell shortcut:  newproj my-project
cd my-project
```

On the first push to a `feature/**` branch (or a PR), the CI pipeline runs.

---

## 4. Onboard an EXISTING project

Copy two files + a Makefile from `project-template` into the repo:

```
.github/workflows/ci.yml        # CI caller
.github/workflows/release.yml   # release caller
Makefile                        # maps lint/test/build to the project's tools
```

(Optionally `.gitleaks.toml`, `.editorconfig`.) Then open a PR — the pipeline
runs on it as a merge gate.

---

## 5. Everyday workflow

```bash
git checkout main && git pull        # 1. SYNC first (avoids push rejections)
git checkout -b fix/something        # 2. branch off — never edit main directly
# ...edit...
git commit -am "describe it"         # 3. save
git push -u origin fix/something     # 4. upload  (-u on a branch's FIRST push)
gh pr create --fill                  # 5. open PR → pipeline tests it in parallel
# green checks → merge → delete the branch
```

**Cut a release** when a version is ready (after merging to main):

```bash
git tag v1.0.0 && git push origin v1.0.0    # → release published automatically
```

SemVer: `PATCH` = bug fix, `MINOR` = new feature, `MAJOR` = breaking change.

---

## 6. The Makefile contract

The CI workflow calls `make <target>`, so the same commands run locally and in CI.
The template's Makefile **auto-detects** the language (python / node / pebble /
garmin). Targets that don't apply are harmless no-ops.

| Target              | Purpose                       |
|---------------------|-------------------------------|
| `lint`              | static bug/pattern checks     |
| `format-check`      | formatting consistency        |
| `typecheck`         | type checking                 |
| `test-unit`         | unit tests                    |
| `test-integration`  | integration tests             |
| `build`             | compile/package the project   |

Run the whole pipeline locally before pushing: `make ci`.

---

## 7. Update the pipeline for EVERY project at once

```bash
# edit standard-sdlc.yml or release.yml here, then:
git commit -am "improve pipeline"
git push origin main
git tag -f v1 && git push -f origin v1     # move the @v1 pointer forward
```

Every repo pinned to `@v1` gets the change on its next run.

---

## 8. Prerequisites & setup notes

- **gh token needs `workflow` scope** to push workflow files:
  `gh auth refresh -h github.com -s workflow`.
- **Releases need a read/write token.** Set it once per repo that publishes:
  Settings → Actions → General → Workflow permissions → **Read and write**, or
  `gh api -X PUT repos/OWNER/REPO/actions/permissions/workflow -F default_workflow_permissions=write`.
- **CodeQL (SAST)** is opt-in: set `enable_codeql: true` in the project's `ci.yml`
  *and* raise that repo's default token to read/write.

---

## 9. Gotchas already solved (don't re-learn these)

- A reusable workflow **cannot request more permission than the caller repo's
  default token**. Permissions are validated at workflow **startup**, before `if:`
  — so even a gated/skipped job asking for `…: write` fails a read-only repo with
  `startup_failure`. Keep the default pipeline on a read-only token.
- `trivy-action` tags are **v-prefixed** (`v0.36.0`).
- `gitleaks-action@v2` **breaks on PR events** (needs token + PR write). We run the
  **gitleaks CLI directly** instead — no GitHub API, works on push and PR.
- The template `ci.yml` triggers on **both** `push` and `pull_request`, so an open
  PR produces two runs per push (harmless, redundant).

---

## 10. Status & open items

**Live & proven:** central CI + release pipelines; template + `newproj`; CI proven
on a real PR; releases proven (`Test-SDLC`, `sdlc-demo` → v0.1.0).

**Open (optional):**
- Wire the **Pebble/Garmin SDK** into `make build` for real `.pbw`/`.iq` release
  artifacts.
- **Branch protection** so `main` only changes via a passing PR.
- Onboard more existing repos.
