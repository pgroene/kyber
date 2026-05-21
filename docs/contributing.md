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

## Logging

### Adding log statements

Every Kyber module uses a module-level logger:

```python
import logging
_LOGGER = logging.getLogger(__name__)
```

This produces logger names like `custom_components.kyber.http_api`, `custom_components.kyber.knowledge`, etc. — all children of `custom_components.kyber`, which makes them easy to filter in HA's `configuration.yaml` and in the Kyber debug panel.

### Level conventions

| Level | When to use |
|---|---|
| `_LOGGER.error(...)` | Unrecoverable failures the user must act on (API unreachable, config invalid) |
| `_LOGGER.warning(...)` | Recoverable issues worth surfacing (retries, fallbacks, unexpected but handled states) |
| `_LOGGER.info(...)` | Significant background milestones (narrator started/finished, explorer phase change, schema upgraded) |
| `_LOGGER.debug(...)` | Detailed trace data for developers (individual tool calls, token counts, cache hits) |

**Rule of thumb:** anything that changes persistent state (`INFO`+), anything that might confuse a user (`WARNING`+), anything that helps reproduce a bug (`DEBUG`).

### Debug mode

When the **Kyber Debug panel** is enabled, Kyber sets `custom_components.kyber` to `INFO` level automatically — so all `INFO` log statements appear in the **📋 Logs** tab without requiring `configuration.yaml` changes. In production (debug mode off) the logger stays at `WARNING` and only warnings/errors are captured.

To force verbose logging in `configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.kyber: debug
```

### Viewing logs in the debug panel

Open **Kyber Debug → 📋 Logs**. The panel shows the live ring buffer of the last 2,000 Kyber log records since last HA restart. Use the level filter dropdown to focus on `WARNING+` or `ERROR+` entries. Click **📥 Download** to save `kyber-logs.txt` — you can drop it in chat for AI-assisted analysis.

## UI Changes

If your PR changes any visible UI behaviour:

1. Add or update a Playwright spec in `www/kyber/tests/ui/`
2. Run `npm run test:ui` locally and verify screenshots in `www/kyber/screenshots/`
3. Check the screenshot image itself before uploading to confirm it reflects the fix (for example, verify breadcrumb text in the image)
4. Include a screenshot in the PR description (or link the `ui-screenshots` CI artifact)

---

## Settings Documentation

If your PR **adds, renames, or removes any configurable setting** — in `config_flow.py`, `const.py`, `strings.json`, or the debug panel (`debug-mixin.js`) — you **must** update **[docs/settings.md](settings.md)** in the same PR.

Checklist:
- [ ] Config field added/changed in `const.py` → update the relevant table in `settings.md`
- [ ] Section or field changed in `config_flow.py` → update the ASCII sketch **and** the table in `settings.md`
- [ ] Label changed in `strings.json` → update the table in `settings.md`
- [ ] New button or input added to `debug-mixin.js` Status tab → update section 3.x in `settings.md`
- [ ] Default value changed → update the Default column in `settings.md`

See `settings.md` section 4 for the full checklist.

## Branch Protection (main)

The `main` branch is protected via GitHub branch protection rules. **Direct pushes to `main` are blocked** — all changes must go through a Pull Request.

### What is enforced

| Rule | Setting |
|---|---|
| Direct push to `main` | ❌ Blocked |
| Force push to `main` | ❌ Blocked |
| Branch deletion | ❌ Blocked |
| Required CI checks | ✅ All 3 must pass (see below) |
| Required reviews | ✅ 1 approving review |
| Branch must be up-to-date | ✅ Yes (no merge with stale base) |
| Admin bypass | ⚠️ Admins can bypass with `--admin` flag (for hotfixes only) |

### Required CI checks

All three must pass **on the `pull_request` event** before merge is allowed:

- `Tests/Python tests (pull_request)`
- `Tests/JS tests (pull_request)`
- `Tests/UI tests (Playwright) (pull_request)`

The `Hassfest` check is **not** a required check (pre-existing upstream issue).

### Workflow summary

```
git checkout main
git pull origin main
git checkout -b feature/my-thing   # or fix/ or docs/

# ... make changes, commit ...

git push origin feature/my-thing
gh pr create --base main --head feature/my-thing --title "..."
# → wait for CI → get 1 review → squash-merge via GitHub UI or:
gh pr merge <number> --squash
```

### Admin bypass (hotfixes only)

In exceptional cases (e.g. version bumps after a squash-merge) an admin can bypass protection:

```bash
git push --no-verify origin main   # bypasses pre-push hook only — GitHub still enforces branch rules
gh pr merge <number> --squash --admin  # bypasses GitHub branch protection
```

Use sparingly. Prefer PRs for all changes.

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
