# Contributing to Kyber

Thank you for helping make Kyber better! These guidelines keep the codebase healthy and releases predictable.

---

## 🔒 Branch protection — no direct pushes to `main`

**`main` is a protected branch.** All changes — including from maintainers — must go through a Pull Request.

| Rule | Setting |
|---|---|
| Direct pushes to `main` | ❌ Blocked (enforced for admins too) |
| Required approvals | 1 |
| Required CI checks | Python tests · JS tests · UI tests (Playwright) |
| Merge style | Squash merge preferred |

### Workflow

```bash
# 1. Create a branch
git checkout main && git pull
git checkout -b fix/my-bug-description   # or feature/, docs/

# 2. Make your changes, commit
git add . && git commit -m "fix: describe the fix"

# 3. Push and open a PR
git push -u origin fix/my-bug-description
gh pr create --title "fix: describe the fix" --body "Closes #123"

# 4. After CI passes + 1 approval → squash merge via GitHub UI or:
gh pr merge --squash
```

### Branch naming

| Type | Pattern | Example |
|---|---|---|
| Bug fix | `fix/<slug>` | `fix/copy-button-crash` |
| Feature | `feature/<slug>` | `feature/i18n-translations` |
| Docs | `docs/<slug>` | `docs/api-reference` |
| Chore | `chore/<slug>` | `chore/bump-deps` |

---

## 🧪 Running tests

```bash
# Python (backend)
pytest tests/ -v

# JS unit + component + integration
cd www/kyber && npm test

# UI (Playwright — requires a running HA instance)
cd www/kyber && npm run test:ui
```

All three must pass before a PR can merge.

---

## 📝 JS version bump

Every time you change a file in `www/kyber/src/`, you must bump its `?v=N` in `www/kyber/kyber-panel.js` **and** copy the changed files to `custom_components/kyber/www/`:

```bash
# Bump version in kyber-panel.js import line, then:
cp www/kyber/src/my-mixin.js   custom_components/kyber/www/src/my-mixin.js
cp www/kyber/kyber-panel.js    custom_components/kyber/www/kyber-panel.js
```

The full workflow is documented in `.github/copilot-instructions.md`.

---

## 🚀 Releases

**Do NOT set the version in PRs** — the release pipeline handles it automatically.

### Continuous deployment

Every merge to `main` automatically triggers the **Do Release** pipeline which:

1. Runs all tests (Python · JS unit · Playwright) in parallel
2. Only if **all tests pass**: bumps the version (patch by default), updates `manifest.json`, `__init__.py` (JS cache-bust), `www/` mirror, and `CHANGELOG.md`
3. Commits, creates a git tag, pushes
4. Creates a GitHub Release with notes from `CHANGELOG.md`
5. Updates the roadmap issue (#204)

### Manual release (minor / major / explicit version)

Go to **Actions → Do Release → Run workflow** and choose the bump type or enter an explicit version.

HACS picks up the new version via the GitHub Release automatically.

---

## 💬 Issues and feature requests

- Use [GitHub Issues](https://github.com/pgroene/kyber/issues) for bugs and features
- Include HA version, Kyber version, and browser console output for bugs
- Check existing issues before opening a duplicate
