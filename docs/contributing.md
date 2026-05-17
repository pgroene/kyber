# Contributing to Kyber

## Branching Strategy

Kyber uses a simple **feature-branch workflow** against a single protected `main` branch.

```
main
 ├── feature/<slug>   — new features
 ├── fix/<slug>       — bug fixes
 └── docs/<slug>      — documentation-only changes
```

### Rules

- **Never push directly to `main`** — always open a Pull Request
- Every feature, fix, or doc update gets its own branch
- Branches are created from the latest `main`
- Use **squash-merge** when merging PRs (one clean commit per feature)

---

## Branch Naming

| Type | Pattern | Example |
|---|---|---|
| Feature | `feature/<slug>` | `feature/plan-card-undo` |
| Bug fix | `fix/<slug>` | `fix/execute-button-label` |
| Docs only | `docs/<slug>` | `docs/contributing` |

Use lowercase kebab-case. Keep slugs short but descriptive.

---

## PR Lifecycle

```
1. Branch    git checkout -b feature/my-feature
2. Implement Follow the TDD workflow (docs → tests → code)
3. Push      git push -u origin feature/my-feature
4. PR        Open PR on GitHub targeting main
5. CI        All 3 checks must pass (python-tests, js-tests, ui-tests)
6. Review    At least 1 approval required
7. Merge     Squash-merge into main
8. Tag       git checkout main && git pull origin main && git tag vX.Y.Z && git push origin vX.Y.Z
9. Clean up  Delete the feature branch after merge
```

---

## Commit Conventions

Use the format: `type: short description`

| Type | When to use |
|---|---|
| `feat` | New feature |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `test` | Adding or updating tests |
| `refactor` | Code restructure, no behaviour change |
| `chore` | Dependency updates, CI config, tooling |

Examples:
```
feat: add undo button to plan card
fix: execute button shows correct label after confirm
docs: add branching strategy to contributing guide
test: add Playwright spec for command card cancel flow
```

---

## TDD Workflow

All new functionality follows this cycle — no exceptions:

```
1. Docs    → Write or update the relevant docs/ file
2. RED     → Write failing tests that assert the documented behaviour
3. GREEN   → Implement until tests pass
4. VERIFY  → Do tests fully cover the docs? Add missing tests.
5. Repeat  → Until docs ↔ tests ↔ implementation all agree
```

See [copilot-instructions.md](../.github/copilot-instructions.md) for full testing details.

---

## CI Requirements

All three CI jobs must pass before a PR can be merged:

| Job | What it runs | How to run locally |
|---|---|---|
| `python-tests` | `pytest tests/ -v` | `docker exec kyber-ha sh -c "cd /config && PYTHONPATH=/config pytest tests/ -v"` |
| `js-tests` | `npm test` (Vitest) | `docker exec kyber-ha sh -c "cd /config/www/kyber && npm test"` |
| `ui-tests` | `npm run test:ui` (Playwright) | `docker exec kyber-ha sh -c "cd /config/www/kyber && PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium-browser npm run test:ui"` |

Screenshots from Playwright are uploaded as the `ui-screenshots` artifact on every CI run.

---

## UI Changes

If your PR changes any visible UI behaviour:

1. Add or update a Playwright spec in `www/kyber/tests/ui/`
2. Run `npm run test:ui` locally and verify screenshots in `www/kyber/screenshots/`
3. Check the screenshot image itself before uploading to confirm it reflects the fix (for example, verify breadcrumb text in the image)
4. Include a screenshot in the PR description (or link the `ui-screenshots` CI artifact)

---

## Branch Protection (main)

The `main` branch is protected:

- Direct pushes are blocked
- PRs require **1 approving review**
- **All 3 CI checks** must pass
- Stale reviews are dismissed when new commits are pushed

---

## Release Tagging

After every PR that bumps `manifest.json` version, create a GitHub Release:

```bash
git checkout main
git pull origin main
git tag vX.Y.Z
git push --no-verify origin vX.Y.Z
```

Then create a GitHub Release on the tag (HACS requires a Release, not just a tag):

```bash
gh release create vX.Y.Z --title "vX.Y.Z" --notes "Summary of changes"
```

Or via the GitHub UI: **Releases → Draft a new release → choose the tag**.

Tags must match the version in `manifest.json` exactly (e.g. `v0.1.66` for `"version": "0.1.66"`).
HACS uses GitHub Releases (not bare tags) to track available versions.
