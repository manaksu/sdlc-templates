# sdlc-templates

Central, reusable SDLC pipeline for all of my projects. **The rules live here once.**
Fix or improve the pipeline in this repo and every project that references it picks
up the change on its next run — no per-project edits.

## How it works

```
   sdlc-templates  (this repo — the rules, defined ONCE)
        │
        │  uses: manaksu/sdlc-templates/.github/workflows/standard-sdlc.yml@v1
        ▼
   any-project/.github/workflows/ci.yml   (5-line caller)
        +
   any-project/Makefile                   (maps generic verbs → that project's tools)
```

Every job runs **in parallel** except where `needs:` declares a dependency:

```
push feature/**
   ├── lint ─────────┐
   ├── format-check ─┤
   ├── typecheck ────┤ (parallel)
   ├── unit-tests ───┼── integration-tests   (needs unit-tests)
   ├── secret-scan ──┤
   ├── dependency-scan
   └── sast (optional CodeQL)
        lint+typecheck+format ──► build
```

## Use it in a project

`.github/workflows/ci.yml`:

```yaml
name: CI
on:
  push:
    branches: ['feature/**', 'feat/**', 'main']
  pull_request:

jobs:
  sdlc:
    uses: manaksu/sdlc-templates/.github/workflows/standard-sdlc.yml@v1
    # optional, for CodeQL-supported languages only:
    # with:
    #   enable_codeql: true
    #   codeql_languages: python
```

The project must provide a `Makefile` with these targets (the
`project-template` repo gives you an auto-detecting one for free):

| Target              | Purpose                          |
|---------------------|----------------------------------|
| `lint`              | Static bug/pattern checks        |
| `format-check`      | Formatting consistency           |
| `typecheck`         | Type checking (no-op if N/A)     |
| `test-unit`         | Unit tests                       |
| `test-integration`  | Integration tests                |
| `build`             | Compile/package the project      |

Targets that don't apply to a project should be harmless no-ops, not errors.

## Versioning

Projects pin a tag (`@v1`). Make changes here, then move the tag forward:

```bash
git tag -f v1 && git push -f origin v1     # patch within v1
# or cut a new major and bump callers to @v2
```
