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
| `scripts/build_changes_feed.py` | Builds the changes feed: titles, dates and links of new legislation, from sources whose record is open. No document text. |
| `tests/test_changes_feed.py` | Offline tests for it, run by the same workflow. |
| `.github/workflows/changes-feed.yml` | Runs it twice a day (04:23 and 16:23 UTC) and commits `verified/changes.json` to the `data` branch. See rule 5. |
| `verified/data-branch.md` | The README published on the `data` branch. |
| `FORK.md` and the note at the top of `README.md` | This notice. |
| One condition each in `.github/workflows/cla.yml` and `refresh-dashboard.yml` | Stops upstream's two workflows running in this fork. See rule 4. |

The additions are Copyright (C) 2026 Fraser Matcham and are under the same
licence as the rest of the repository.

This fork is not affiliated with or endorsed by World Wide Law. The names
"World Wide Law" and "Legal Data Hunter" are used here only to say where the
work came from.

## Rules for changes here

1. **Add, do not edit.** New work goes in new files and directories. Upstream's
   files are left alone wherever that is possible, so that taking upstream's
   changes stays a clean merge. The edits to upstream files are the short
   note at the top of `README.md` and the two workflow conditions in rule 4.
2. **`LICENSE` is never altered or removed.**
3. **Upstream's licence labels are leads.** Nothing in `verified/` is copied or
   inferred from `manifest.yaml`, `docs/licenses.json` or a `config.yaml`.
4. **Upstream's two workflows do not run here.** Each carries one added
   condition, `github.repository == 'worldwidelaw/legal-sources'`, and nothing
   else in them is changed.
   - `cla.yml` asks contributors to sign upstream's contributor agreement. It
     ran on this fork's first pull request and failed it, although that
     agreement does not apply to work kept in the fork.
   - `refresh-dashboard.yml` commits to `main` on a schedule and whenever
     `sources/`, `manifest.yaml` or the dashboard scripts change on `main`.
     Here that would fire on every merge from upstream and add commits to
     `main` that upstream does not have.

   If upstream edits either condition line, keep this fork's guard when
   resolving the merge.
5. **Generated data goes to the `data` branch, never to `main`.** The daily
   changes feed is committed there by its workflow, so `main` only ever
   differs from upstream by this fork's own hand-made changes. The branch
   holds `verified/changes.json`, a README and a copy of `LICENSE`, and
   nothing is committed to it by hand.

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

## Sources paused pending the publisher's reply

Nothing from these sources is used by this fork's products until the publisher
answers the reader's question about its terms. Each record in `verified/` says
when the question was sent. Upstream's collectors and sample records for them
stay in `sources/`, unchanged, as upstream's.

| Source | Asked | Record |
| --- | --- | --- |
| Electoral Commission | 24 November 2026 | `verified/sources/UK/EC.yaml` |
| IPSO | 24 November 2026 | `verified/sources/UK/IPSO.yaml` |
| Parliamentary and Health Service Ombudsman | 24 November 2026 | `verified/sources/UK/PHSO.yaml` |

When a reply comes, the record is rewritten from it and the source leaves this
table.
