#!/usr/bin/env python3
"""Planning stage of the parallel-sandbox SDLC pipeline.

Runs after triage opens the gate. Decomposes a requirement into INDEPENDENT slices
(no two slices write the same file), grounded in the repo file list and the project
learning log. Emits a machine-readable file-ownership map for downstream fan-out +
defect-triage, posts a plan comment on the issue, and writes the matrix source to
$GITHUB_OUTPUT.

This is the automation counterpart of docs/learning-log/prompts/planner.md.

Env in: ANTHROPIC_API_KEY, GH_TOKEN, REPO, MODEL, ISSUE_NUMBER, ISSUE_TITLE,
        ISSUE_BODY, MAX_SANDBOXES (optional, default 4).
Outputs ($GITHUB_OUTPUT): parallelizable=true|false, count=<n>, slices=<compact JSON array>.
Writes: .wave/ownership.json  (consumed by scripts/triage-owner.mjs in Phase 3).
"""
import json
import os
import re
import subprocess

import anthropic

REPO = os.environ["REPO"]
ISSUE = os.environ["ISSUE_NUMBER"]
MODEL = os.environ.get("MODEL", "claude-opus-4-8")
MAX_SANDBOXES = int(os.environ.get("MAX_SANDBOXES", "4"))
title = os.environ.get("ISSUE_TITLE", "")
body = os.environ.get("ISSUE_BODY", "") or "(no description provided)"

try:
    files = subprocess.check_output(["git", "ls-files"], text=True).splitlines()
except Exception:
    files = []
tree = "\n".join(files[:400]) or "(empty repository)"

# Ground the plan in what we've learned before (read-only).
log_index = ""
for path in ("docs/learning-log/INDEX.md",):
    if os.path.exists(path):
        with open(path) as f:
            log_index = f.read()
log_index = log_index or "(no learning log yet)"

SCHEMA = {
    "type": "object",
    "properties": {
        "parallelizable": {"type": "boolean"},
        "reason": {"type": "string"},
        "slices": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "slug": {"type": "string"},
                    "goal": {"type": "string"},
                    "owns": {"type": "array", "items": {"type": "string"}},
                    "done": {"type": "string"},
                },
                "required": ["name", "slug", "goal", "owns", "done"],
                "additionalProperties": False,
            },
        },
        "frozen": {"type": "array", "items": {"type": "string"}},
        "integration_notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["parallelizable", "reason", "slices", "frozen", "integration_notes"],
    "additionalProperties": False,
}

PROMPT = f"""You are the Planner stage of an automated, parallel-sandbox SDLC pipeline.
A requirement was filed as a GitHub issue. Produce a development plan.

REQUIREMENT
Title: {title}
Body:
{body}

REPOSITORY FILES (truncated):
{tree}

LEARNING LOG INDEX (what we've built/learned before — reuse, avoid known bottlenecks):
{log_index}

Decide whether this work can be parallelized across isolated sandboxes. The HARD rule:
two slices may NEVER write the same file. A slice owns an exact set of file globs; all other
slices treat those files as read-only.

- If it splits cleanly into independent slices: parallelizable=true. Give at most {MAX_SANDBOXES}
  slices. For each: name, a short kebab `slug`, the `goal`, the exact `owns` globs it may write,
  and `done` (which tests must pass). Owns sets across slices must NOT overlap.
- If it does NOT split cleanly (one module, tightly coupled, or output-of-one-feeds-another):
  parallelizable=false, explain in `reason`, and return an empty `slices` array — the pipeline
  will fall back to the single-Developer path.
- `frozen`: shared surfaces NO slice may edit (lockfiles, package.json, shared config/data).
  Note in integration_notes how shared additions (e.g. a new dependency) get reconciled.
- integration_notes: semantic conflicts to watch for when slices merge, and which integration
  scenarios to run."""

client = anthropic.Anthropic()
resp = client.messages.create(
    model=MODEL,
    max_tokens=4000,
    thinking={"type": "adaptive"},
    output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
    messages=[{"role": "user", "content": PROMPT}],
)
text = next(b.text for b in resp.content if b.type == "text")
plan = json.loads(text)


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "slice"


# Normalize slices: stable branch names + dedup slugs. Cap at MAX_SANDBOXES.
slices = plan["slices"][:MAX_SANDBOXES] if plan["parallelizable"] else []
seen = set()
for s in slices:
    slug = slugify(s.get("slug") or s["name"])
    while slug in seen:
        slug += "x"
    seen.add(slug)
    s["slug"] = slug
    s["branch"] = f"ai/issue-{ISSUE}/{slug}"

# Safety: detect any literal file claimed by two slices (globs can't be fully resolved here,
# but exact-path collisions are a clear planning error worth blocking).
owned = {}
collisions = []
for s in slices:
    for g in s["owns"]:
        if "*" not in g and g in owned and owned[g] != s["slug"]:
            collisions.append(f"`{g}` claimed by both **{owned[g]}** and **{s['slug']}**")
        owned[g] = s["slug"]

parallelizable = bool(plan["parallelizable"]) and len(slices) >= 2 and not collisions

# Write the machine-readable ownership map (Phase-3 triage consumes this).
os.makedirs(".wave", exist_ok=True)
ownership = {
    "issue": ISSUE,
    "slices": [{"name": s["name"], "branch": s["branch"], "owns": s["owns"]} for s in slices],
    "frozen": plan["frozen"],
}
with open(".wave/ownership.json", "w") as f:
    json.dump(ownership, f, indent=2)


def md(items):
    return "\n".join(f"- {x}" for x in items) if items else "- (none)"


if parallelizable:
    rows = "\n".join(
        f"| `{s['slug']}` | {s['goal']} | {', '.join(f'`{g}`' for g in s['owns'])} |"
        for s in slices
    )
    plan_md = f"""## 🤖 Parallel plan

{plan['reason']}

**Slices ({len(slices)} sandbox{'es' if len(slices) != 1 else ''})**

| slice | goal | owns (write-fenced) |
|-------|------|---------------------|
{rows}

**Frozen (no slice may edit):** {', '.join(f'`{x}`' for x in plan['frozen']) or '(none)'}

**Integration watch-outs**
{md(plan['integration_notes'])}

_Plan for human review — model `{MODEL}`. Ownership map written to `.wave/ownership.json`._"""
else:
    why = "; ".join(collisions) if collisions else plan["reason"]
    plan_md = f"""## 🤖 Plan: single-Developer path

This requirement is **not cleanly parallelizable** — {why}

Recommend the standard single-Developer flow (see `PLAYBOOK.md`) rather than a sandbox fan-out.

_Plan for human review — model `{MODEL}`._"""


def gh(*args, check=True):
    subprocess.run(["gh", *args, "--repo", REPO], check=check)


gh("issue", "comment", ISSUE, "--body", plan_md)

with open(os.environ["GITHUB_OUTPUT"], "a") as f:
    f.write(f"parallelizable={'true' if parallelizable else 'false'}\n")
    f.write(f"count={len(slices)}\n")
    # Compact JSON array for a downstream `strategy.matrix` via fromJSON.
    f.write("slices=" + json.dumps(slices, separators=(",", ":")) + "\n")

print(f"parallelizable={parallelizable} slices={len(slices)} collisions={len(collisions)}")
