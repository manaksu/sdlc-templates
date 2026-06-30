# SDLC Automation Playbook

> **Purpose:** a self-contained guide to stand up an automated, multi-agent SDLC
> on GitHub — from a filed requirement to a tested, reviewed pull request, with
> human gates. Hand this file to Claude Code (or an engineer) in a new repo/org
> and say: *"Implement this SDLC system here."* It also lists every gotcha we hit
> so you don't rediscover them.
>
> **Reference implementation (public, copy from these):**
> - `ManaksAI/sdlc-templates` — the central reusable workflows + triage script
> - `ManaksAI/project-template` — the starter template repo
> Replace `ManaksAI` with your org throughout.

---

## 1. What you get

```
Requirement (GitHub issue + `requirement` label)
   → 🤖 ANALYST  : reads the repo, writes a structured analysis, decides if a human is needed
   → 🚦 GATE     : needs-human?  → alert + pause (human reviews, adds `approved` to proceed)
   → 🤖 DEVELOPER: branch → implement → write tests → run CI → open PR ("Closes #N")
   → 🤖 REVIEWER : independent review of the PR diff, posts findings (advises only)
   → 👤 HUMAN    : reviews + merges                       ← gate
   → 🏷️  RELEASE  : tag vX.Y.Z → build + GitHub Release    ← human-tagged
   → 🚀 DEPLOY   : separate, human-gated step
```

Plus a standard **parallel CI pipeline** (lint / format / typecheck / unit / integration /
secret-scan / dependency-scan / optional SAST / build) on every push & PR.

**Design principles**
- **Rules defined once** in a central repo; every project references them (`uses: ORG/sdlc-templates/...@v1`). Fix once → all repos get it.
- **Multi-agent, but minimal**: Analyst, Developer, Reviewer — each justified by a distinct role + clean handoff. Don't split further (planner/test-writer/etc.) until a single agent visibly struggles. When it does — large requirements that split into independent slices — see the scale-out design in [`SANDBOX-ORCHESTRATOR.md`](SANDBOX-ORCHESTRATOR.md) (parallel git-worktree sandboxes + a learning log).
- **Human-in-the-loop gates** at: needs-review escalation, PR merge, and deploy. AI never merges or deploys.
- **Everything event-driven & label-gated** → zero cost until a requirement is actually filed.

---

## 2. Architecture

```
ORG/sdlc-templates  ★ MASTER — the rules, defined ONCE, pinned at tag @v1
   .github/workflows/
     standard-sdlc.yml   (reusable: parallel CI)
     release.yml         (reusable: build + GitHub Release on vX.Y.Z tag)
     ai-sdlc.yml         (reusable: Analyst + Developer)
     code-review.yml     (reusable: independent Reviewer)
   scripts/triage.py     (the Analyst logic)
        ▲ referenced via `uses:` (works cross-owner if master is public)
        │
   each project repo carries tiny CALLER workflows + a Makefile:
     .github/workflows/{ci,release,ai-sdlc,review}.yml   (5-line callers)
     Makefile                                            (maps lint/test/build → tools)
        ▲ seeded automatically from:
   ORG/project-template  (a GitHub "template repo"; new repos start compliant)
```

- The **master holds the logic**; each repo holds a **doorbell** (caller) because GitHub events fire only in the repo where they happen.
- **CI work is delegated to `make <target>`** so the same commands run locally and in CI. A language-agnostic `Makefile` auto-detects the project type, so one pipeline serves many stacks.

---

## 3. The components (copy from the reference repos)

All exact file contents are in `ORG/sdlc-templates` and `ORG/project-template`. Key shapes:

**Reusable CI** (`standard-sdlc.yml`): `on: workflow_call`; one job per check, **no `needs:`** = parallel; `integration-tests` `needs: [unit-tests]`; `build` `needs: [lint,typecheck,format-check]`. Each step runs `make <target>`. **No top-level `permissions`** (runs on the read-only default token).

**Reusable Release** (`release.yml`): `on: workflow_call`; `make build` then `gh release create "$TAG" --generate-notes` (+ optional `artifact_glob` files). Needs a read/write token.

**Reusable AI SDLC** (`ai-sdlc.yml`): two jobs.
- `triage`: checkout caller repo + checkout `ORG/sdlc-templates@v1` into `.sdlc/` for the script; `pip install anthropic`; run `scripts/triage.py`; output `proceed`.
- `implement` (`if: auto_implement && proceed=='true'`): `anthropics/claude-code-action@v1` with a prompt to branch → implement → test → open PR; **never merge/deploy**; escalate on blockers.

**Analyst** (`scripts/triage.py`): calls the Claude API (`claude-opus-4-8`, adaptive thinking, **structured JSON output**) with the issue + a `git ls-files` listing for grounding; posts an analysis comment; gate = model's `needs_human_review` OR deterministic overrides (risk=high, sensitive labels); honors an `approved` label override; writes `proceed` to `$GITHUB_OUTPUT`.

**Reviewer** (`code-review.yml`): `on: workflow_call`; `claude-code-action@v1` with **read-only tools** (`--allowedTools Bash,Read,Glob,Grep`) and a prompt to review ONLY the diff and post findings; **advises only — never approves/merges/edits**.

**Callers** (in each repo / the template):
- `ci.yml` → `on: push (feature/**, main) + pull_request` → `uses: ORG/sdlc-templates/.github/workflows/standard-sdlc.yml@v1`
- `release.yml` → `on: push: tags: ['v*.*.*']`
- `ai-sdlc.yml` → `on: issues: [labeled]`, `if: label.name == 'requirement' || label.name == 'approved'`, `secrets: inherit`
- `review.yml` → `on: pull_request: [opened, synchronize, reopened]`, `secrets: inherit`

---

## 4. Setup runbook

```bash
# 0. Prereqs: gh CLI authed; org exists. Grant gh token scopes:
gh auth refresh -h github.com -s workflow,admin:org   # workflow files + org settings

# 1. Create the two infra repos from the reference (or copy the files in)
#    Keep sdlc-templates PUBLIC so callers can reference it cross-owner.
#    Put scripts/triage.py + the 4 reusable workflows in sdlc-templates.
#    Tag it:
git -C sdlc-templates tag v1 && git -C sdlc-templates push origin v1

# 2. Mark project-template as a GitHub template repo
gh repo edit ORG/project-template --template

# 3. Org-level config (set ONCE, inherited by all org repos)
gh secret set ANTHROPIC_API_KEY --org ORG --visibility all          # the AI key
gh api -X PUT orgs/ORG/actions/permissions/workflow \
   -F default_workflow_permissions=write -F can_approve_pull_request_reviews=true

# 4. Install the Claude Code GitHub App on the org (for Developer + Reviewer agents)
#    https://github.com/apps/claude  → install on ORG → All repositories

# 5. New project (born compliant):
gh repo create ORG/my-app --template ORG/project-template --clone

# 6. Onboard an EXISTING repo: copy the 4 caller files + Makefile into it.

# 7. Use it:
#    - File an issue, add the `requirement` label → Analyst runs.
#    - If gated, review the analysis, add `approved` → Developer runs (if auto_implement on).
#    - Reviewer comments on the PR. Human merges. Tag vX.Y.Z to release.
```

**Re-trigger analysis after editing a requirement:** toggle the `requirement` label OFF then ON (editing the body alone does nothing; re-adding an already-present label does nothing).

**Update the pipeline for every repo at once:** edit `sdlc-templates`, then `git tag -f v1 && git push -f origin v1`.

---

## 5. Prerequisites checklist

- [ ] `gh` token scopes: `workflow` (push workflow files), `admin:org` (org secrets/settings)
- [ ] `ANTHROPIC_API_KEY` as an **org secret**, visibility ALL — **and the Console account must have credits** (pay-as-you-go, separate from any Claude subscription)
- [ ] Org default workflow token = **Read and write**, and **"Allow Actions to create and approve PRs" = ON**
- [ ] **Claude Code GitHub App** installed on the org/repos (Developer + Reviewer need it)
- [ ] Private repos: **Actions billing/minutes** available (see gotchas) or self-hosted runners
- [ ] `make` targets exist in each repo (lint/format-check/typecheck/test-unit/test-integration/build) — no-ops are fine

---

## 6. Gotchas that cost real time (read before debugging)

1. **Pushing `.github/workflows/*` needs the `workflow` token scope** — `repo` alone gives `! [remote rejected] ... without 'workflow' scope`.
2. **Reusable-workflow permissions are validated at STARTUP, before `if:`.** A job (even a skipped one) requesting a permission the caller's default token can't grant fails the whole run with the generic *"This run likely failed because of a workflow file issue."* Keep CI on the read-only default token; only request `write`/`id-token` where the default actually allows it.
3. **`claude-code-action` needs `permissions: id-token: write`** (it auths via OIDC) on the implement/review jobs — plus `contents`/`pull-requests`/`issues: write` for the Developer.
4. **`claude-code-action` requires the Claude Code GitHub App installed** — otherwise `App token exchange failed: 401 ... not installed`.
5. **`claude-code-action` denies all tools unless you pass `--allowedTools`** — symptom: job "succeeds", agent runs many turns, but makes NO branch/PR and the log shows `permission_denials_count > 0`. Developer needs `Bash,Edit,Read,Write,Glob,Grep`; Reviewer (read-only) needs `Bash,Read,Glob,Grep`.
6. **PRIVATE repos in a FREE org can't run Actions** until billing/minutes are set up — EVERY workflow startup-fails with 0 jobs and the same generic "workflow file issue" message (a red herring — it's billing). Public repos run free. Enterprise orgs with billing/runners don't hit this.
7. **`gitleaks-action@v2` breaks on `pull_request` events** (needs token + PR perms). Run the **gitleaks CLI directly** instead — no GitHub API, works on push and PR.
8. **`trivy-action` tags are `v`-prefixed** (`@v0.36.0`, not `@0.36.0`).
9. **Re-running a startup-failed run does nothing** — and re-running a *successful* run replays the OLD event payload (won't pick up an edited issue). Always re-trigger via a fresh event (toggle the label).
10. **The Claude API is pay-as-you-go**, billed to the Console org the key belongs to. `400 credit balance too low` = no credits; `401 invalid x-api-key` = wrong/garbled key (often a copy-paste artifact — set it via `gh secret set` stdin prompt).
11. **Platforms CI can't compile** (Garmin Monkey C, etc.): automated tests can only cover extractable logic; rendering/behavior needs a **manual checklist** + human verification (e.g. the device simulator). Have the Developer agent write a manual test plan for those parts.

---

## 7. Enterprise adaptations (the big-project deltas)

Your enterprise project has constraints the personal setup didn't. Layer these on:

**Identity & access**
- You already have a GitHub **Org/Enterprise** — use **org rulesets** and a **`.github` repo** for org-wide defaults (issue/PR templates, CODEOWNERS).
- Enforce **SSO/SAML**; scope the GitHub App + PAT/OIDC minimally.

**Make the gates mandatory (don't rely on convention)**
- **Branch protection / rulesets on `main`**: require ✅ status checks (the CI jobs) + **N approving reviews** + **CODEOWNERS** review + linear history. Now neither humans nor agents can merge unreviewed.
- Keep **`auto_implement: false` (analysis-only)** by default; enable autonomous implementation per-repo, deliberately, on low-risk areas first.
- Consider requiring the **`approved` label by a CODEOWNER** before the Developer agent runs.

**CI/CD at scale**
- **Self-hosted or larger runners** for private-repo Actions volume/cost; concurrency limits.
- **Dependency caching** (`actions/setup-*` `cache:`) and **"only test what changed"** (Nx/Turborepo/Bazel or `paths:` filters) — critical for large monorepos.
- **Environments + deployment approvals** (GitHub Environments with required reviewers) for staging → prod promotion. `main` ≠ production; deploy is a gated promotion.
- Real **SAST/DAST/secret-scanning/SBOM** integrated into the PR gate; tune severity baselines.

**Secrets & supply chain**
- Org/Environment secrets; **OIDC to cloud** (AWS/GCP/Azure) instead of long-lived keys.
- Pin third-party actions to **commit SHAs** (not tags) for supply-chain integrity; enable Dependabot.

**AI agent governance**
- **Cost controls**: pick models per stage (cheap model for triage, strong for implement/review), set `--max-turns`, monitor spend; the pipeline is label-gated so cost is opt-in.
- **Audit**: every agent action lands in Actions logs + PR history. Keep the human merge/deploy gates non-negotiable.
- **Scope the autonomy**: start with Analyst-only across all repos (free, high value), add Developer on a few low-risk services, expand as trust builds.
- **Data sensitivity**: the Analyst sends issue text + a file listing (not full source) to the API; the Developer agent (claude-code-action) runs in your CI and reads the repo. Confirm this matches your data-handling policy; for stricter needs use Claude via your approved cloud (e.g. Bedrock/Vertex) and review the action's data flow.

**Platform/IDP**
- At many-team scale, add a catalog (**Backstage**) with **software templates** = your `project-template`, and **org rulesets** as the enforcement layer. This is the "paved road / golden path / platform engineering" pattern — what you've built is the small version of it.

---

## 8. Rollout strategy (small → large)

1. Stand up the master + template + org config (Section 4).
2. **Analyst-only** (`auto_implement: false`) across a few repos — learn what the analyses look like; cost ≈ cents/requirement.
3. Add **branch protection** so the gates are mandatory.
4. Add the **Reviewer** on all PRs.
5. Enable the **Developer** on one or two low-risk services; expand as trust builds.
6. Wire **environments + deploy approvals**; integrate real security scanners.
7. Add **caching / affected-only testing** once pipelines feel slow.

> Watch for: friction points (automate them before scaling), what you keep skipping (drop it), and where one agent struggles (only then split it).
```
