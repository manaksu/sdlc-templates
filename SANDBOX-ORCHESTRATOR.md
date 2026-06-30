# Parallel-Sandbox SDLC Orchestrator (with Learning Log)

> **Purpose:** the scale-out evolution of [`PLAYBOOK.md`](PLAYBOOK.md). The base playbook
> runs a single **Analyst → Developer → Reviewer** chain per requirement and deliberately
> says: *"don't split further (planner/test-writer/etc.) until a single agent visibly
> struggles."* This document is what to do **when it struggles** — when a requirement is too
> big for one Developer and cleanly splits into independent slices. It adds: a **planner**, a
> fan-out of **parallel sandboxes** (git worktrees), a **per-sandbox test author + learning
> agent**, an **integration + defect-triage** loop, and a persistent **learning log** that
> makes each requirement start smarter than the last.
>
> It reuses every existing rail (`ai-sdlc.yml`, `scripts/triage.py`, the CI/release callers,
> the human gates). Nothing here weakens the non-negotiable human merge/deploy gates.

---

## 1. When to use this (and when NOT to)

Use the orchestrator only when the planner can carve the work into **independent, non-overlapping
slices**. Signals:

- ✅ Distinct modules/directories, mostly additive work, stable interfaces between pieces.
- ✅ The requirement is large enough that one Developer agent would serialize unnecessarily.

Stay on the **base playbook** (single Developer) when:

- ❌ The work centers on one file/module (parallelism buys nothing, costs coordination).
- ❌ One slice's output is another's input (that's *sequential*, not parallel).
- ❌ The design isn't decided yet — decide first, then fan out.

> Cardinal rule, inherited from the worktree model: **no two sandboxes write the same file.**
> If the planner cannot produce a clean file-ownership map, the work is not ready to parallelize.

---

## 2. The learning log — the memory at the center

A repo-versioned store of what we've learned building this project, mirroring the `MEMORY.md`
index pattern.

```
docs/learning-log/
├── INDEX.md                     # one line per entry — cheap to scan/grep
└── entries/
    └── YYYY-MM-DD-<slug>.md      # one learning per file
```

**Entry schema** (each `entries/*.md`):

| Field | Meaning |
|-------|---------|
| `requirement` | what was asked |
| `approach` | how we built it |
| `bottleneck` | what fought us |
| `how_overcome` | the resolution |
| `alternatives` | other options considered + why not |
| `outcome` | result (tests, perf, links to PRs/commits) |
| `tags` | module/area, for matching future requirements |

**Why a repo file, not a database:** every worktree is a full copy of the repo, so **each
sandbox gets the learning log automatically** — no shared mount, no sync. Crucially:

- **Read-only during a run.** All agents only *read* the log while working → zero write
  contention (the same "no shared writes" rule that makes the sandboxes safe).
- **Written once, sequentially, at the end** (Phase 4 consolidation), on the integration
  branch. Never concurrently.

---

## 3. The pipeline (4 phases)

```
Requirement (issue + `requirement` label → ai-sdlc orchestrator)
  │
  ▼  PHASE 1 — analyze (parallel, read-only)
  ├─ Learning-analyst  → queries the log: done before? exists? how different? past bottlenecks
  └─ Code-analyst      → where it fits, modules touched, blast radius   (= today's triage.py)
        └─► PLANNER marries both → dev plan + FILE-OWNERSHIP MAP  ──┐
  │                                                                 │ ownership map decides
  ▼  PHASE 2 — parallel build (N sandboxes = N clean slices)        │ HOW MANY sandboxes
  ├─ Sandbox 1: Developer + Test-author + Learning-agent(→ own file)│
  ├─ Sandbox 2: Developer + Test-author + Learning-agent            │
  └─ Sandbox N: ...        (each "ready" only when ITS unit tests pass)
  │
  ▼  PHASE 3 — integrate & verify
  ├─ merge ready sandboxes smallest-first → integration branch
  ├─ run INTEGRATION test scenarios (catches semantic conflicts unit tests miss)
  └─ Defect-triage → map each failure to its OWNING sandbox → fix · retest · reintegrate (loop)
  │
  ▼  PHASE 4 — ship & learn   (HUMAN GATE before merge/release stays non-negotiable)
  ├─ all green → green signal → Reviewer + human merge → release caller
  └─ consolidate per-sandbox learnings → update the learning log for the next requirement
```

### Phase 1 — Analyze → Plan
Two read-only agents fan out against the requirement:

- **Learning-analyst** (new): searches the learning log. "Have we built this shape before? Does
  it already exist? How different is it? What bottlenecks/alternatives are on record?"
- **Code-analyst**: the existing `scripts/triage.py` Analyst — grounds against `git ls-files`,
  decides where the change fits and its blast radius, and still owns the **needs-human gate**.

The **Planner** (new) merges both into:
- a decomposition into independent slices,
- the **file-ownership map** (who owns what; what is **frozen**: lockfiles, schema, DI/route
  registries, i18n bundles),
- risk flags lifted from the log.

**The ownership map is the source of truth for how many sandboxes to spin up** — one per clean
slice, capped by review bandwidth (start 2–4).

### Phase 2 — Parallel build
Each sandbox is a git worktree (`isolation: "worktree"`) running a small team:

- **Developer** — implements its slice (the existing `claude-code-action` Developer, one per
  sandbox instead of one total).
- **Test-author** — concurrently writes that slice's unit tests: **standard / positive /
  negative / edge**, seeded by the log's known edge cases for similar work. Use a shared
  `test-scenarios` skill (build once via `skill-creator`) so taxonomy is consistent.
- **Learning-agent (per sandbox)** — applies relevant past learnings up front; captures new
  ones into its **own** file `.learnings/sandbox-<id>.md` (no cross-sandbox write collision).

A sandbox is **ready** only when **its own unit tests are green** in its own worktree. Each
sandbox opens a PR, so the existing `ci` + `review` callers run per-branch — that *is* the
per-sandbox gate, for free.

### Phase 3 — Integrate, triage, loop
1. Merge ready sandboxes **smallest-first** onto an integration branch.
2. Pull **integration test scenarios** (log + integration suite) and run on the *integrated*
   result. Per-sandbox unit tests prove each slice; only integration tests catch **semantic
   conflicts** (two slices each correct, wrong together).
3. **Defect-triage agent** maps each failing scenario → the **owning sandbox**, using the
   planner's ownership map + `git blame` on the failing path. *(Note: distinct from the Phase-1
   Analyst, which is also historically called "triage" — name this one `integration-triage` to
   avoid confusion with `scripts/triage.py`.)*
4. Route the defect back to that sandbox → fix → retest → reintegrate. **Loop until green.**

### Phase 4 — Ship & learn
- All green → **green signal**: Reviewer's independent pass + **human merge** (gate) →
  `release` caller on a version tag. **AI never merges or deploys** (base-playbook principle).
- **Consolidate** every `.learnings/sandbox-*.md`: dedupe, merge, and update
  `docs/learning-log/` — sequentially, on the integration branch (the `consolidate-memory`
  pattern applied to the project). The next requirement starts smarter.

---

## 4. Mapping to the existing infra

| New concept | Existing rail it reuses / extends |
|-------------|-----------------------------------|
| Orchestrator kickoff | `requirement` label → `ai-sdlc.yml` job becomes the orchestrator |
| Code-analyst | `scripts/triage.py` (unchanged — keeps the needs-human gate) |
| Per-sandbox unit-test gate | each sandbox PR runs the `ci` (`standard-sdlc.yml`) caller |
| Per-sandbox review | the `review.yml` Reviewer caller, per PR |
| Integration verify | the same CI on the integration branch |
| Green signal → release | the `release.yml` caller on a `vX.Y.Z` tag |
| Human gates | unchanged: needs-human escalation, PR merge, deploy |

**New components to build** (don't exist yet):
1. `learning-analyst` — log-query agent/prompt.
2. `planner` — produces the slice + ownership map (the orchestration brain).
3. `test-scenarios` skill — shared scenario taxonomy.
4. `learning-agent` — per-sandbox capture + a `consolidate` step.
5. `integration-triage` — failure → owning-sandbox mapping.
6. `docs/learning-log/` scaffold + `INDEX.md`.

---

## 5. Decisions (recommended defaults)

| Decision | Default |
|----------|---------|
| Log format | markdown entries + `INDEX.md` (matches `MEMORY.md`; greppable, diff-friendly) |
| Orchestrator host | the `ai-sdlc` job, kicked by the `requirement` label |
| Test scenarios | one shared `test-scenarios` skill via `skill-creator` |
| Max parallel sandboxes | 2–4 to start — **review/CI bandwidth is the real cap, not agent count** |
| Learning writes | per-sandbox `.learnings/<id>.md` during; one sequential consolidation at end |
| Defect ownership | planner's ownership map + `git blame`; ties go to the larger-diff slice |

---

## 6. Rollout order (don't build it all at once)

1. **Phase 1 fan-out** (learning-analyst + planner) — highest leverage, lowest risk. Get good
   ownership maps before anything writes code.
2. **Phase 2 parallel dev + test** — formalize the manual worktree fan-out already proven.
3. **Learning log** — read-in, then per-sandbox capture, then consolidation.
4. **Phase 3 automated integration + defect-triage** — hardest; add last, once the rest is
   trusted.

---

## 7. Failure modes to watch

- **Hidden shared state** — two sandboxes both add a dependency → lockfile conflict. Freeze
  lockfiles in the ownership map; reconcile deps in one sequential step.
- **Semantic conflicts** — slices individually correct, wrong together. Phase-3 integration
  tests on the merged branch are non-negotiable.
- **`main` drift** — long-running sandboxes fall behind. Keep waves short or rebase before merge.
- **Review bottleneck** — spawning N agents is easy; trusting N diffs is not. Prefer more,
  smaller slices; let CI + Reviewer do the first pass.
- **Over-splitting** — per the base playbook, only split a role once a single agent visibly
  struggles. More agents = more handoffs = more places to leak context.

---

## 8. Governance (inherits PLAYBOOK §7)

Per-stage model choice (cheap for analyst/triage, strong for dev/review), `--max-turns` caps,
label-gated cost, SHA-pinned actions, mandatory branch protection so neither humans nor agents
merge unreviewed. The learning log is project metadata (no source) — confirm it fits your
data-handling policy before enabling on sensitive repos.
