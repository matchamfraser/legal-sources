# About this fork

This repository is a fork of
[worldwidelaw/legal-sources](https://github.com/worldwidelaw/legal-sources)
("World Wide Law"), which is licensed under the GNU Affero General Public
License, version 3 or any later version. `LICENSE` is upstream's file,
unchanged.

**This is a modified version. It was modified by Fraser Matcham, beginning
20 November 2026.** Everything not listed below is upstream's work, Copyright
(C) 2025 World Wide Law Contributors.

## What this fork adds

| Path | What it is |
| --- | --- |
| `verified/` | The verified terms register: what a named person found when they read each source's own terms. See [`verified/README.md`](verified/README.md). |
| `scripts/build_verified_register.py` | Validates the records and writes `verified/register.json`. |
| `tests/test_verified_register.py` | Offline tests for it. |
| `.github/workflows/test-verified-register.yml` | Runs those tests on changes to the register. |
| `FORK.md` and the note at the top of `README.md` | This notice. |

The additions are Copyright (C) 2026 Fraser Matcham and are under the same
licence as the rest of the repository.

This fork is not affiliated with or endorsed by World Wide Law. The names
"World Wide Law" and "Legal Data Hunter" are used here only to say where the
work came from.

## Rules for changes here

1. **Add, do not edit.** New work goes in new files and directories. Upstream's
   files are left alone wherever that is possible, so that taking upstream's
   changes stays a clean merge. The one edit to an upstream file is the short
   note at the top of `README.md`.
2. **`LICENSE` is never altered or removed.**
3. **Upstream's licence labels are leads.** Nothing in `verified/` is copied or
   inferred from `manifest.yaml`, `docs/licenses.json` or a `config.yaml`.
4. **Upstream's workflows are left as they are.** `refresh-dashboard.yml` runs
   on a schedule and pushes to `main`; GitHub does not run scheduled workflows
   in a fork unless someone turns them on. Leave it off here: it would add
   commits to `main` that upstream does not have. `cla.yml` asks contributors
   to sign upstream's contributor agreement and does not apply to this fork.

## Taking upstream's changes

`upstream-main` is a mirror of upstream's `main`. Nothing is committed to it.

```sh
git remote add upstream https://github.com/worldwidelaw/legal-sources.git   # once
git fetch upstream main
git push origin upstream/main:refs/heads/upstream-main     # fast-forward only
git checkout main && git merge upstream-main
python3 scripts/build_verified_register.py --check
```

After a merge, run the check: a source that upstream has removed or renamed
makes its record fail, because every record's id must exist in
`manifest.yaml`.
