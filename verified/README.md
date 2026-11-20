# Verified terms register

This directory is an addition in this fork. It records, source by source, what
a named person found when they read the source's **own terms** on a given date.

The licence labels elsewhere in this repository (`manifest.yaml`,
`docs/licenses.json`, each `config.yaml`) are leads, not findings. They are
never copied into a record. A record exists only because someone opened the
publisher's terms page and read it.

It is information, not legal advice.

## Layout

```
verified/
  sources/<CC>/<Source>.yaml   one record per source, named by its manifest id
  register.json                every record in one file, built by the script
```

Build and check:

```sh
python3 scripts/build_verified_register.py           # validate, write register.json
python3 scripts/build_verified_register.py --check   # validate, fail if register.json is stale
python3 -m pytest tests/test_verified_register.py -q
```

Never edit `register.json` by hand. `docs/licenses.json` and the `config.yaml`
files are upstream's and are not touched by this work.

## A record

```yaml
id: XX/Statutes                      # must match the path and exist in manifest.yaml
terms:                               # the page(s) that were read
  - title: Reuse terms
    url: https://example.org/terms
date_read: 2026-11-20
read_by: A Reader
review_by: 2027-05-20                # within 366 days of date_read
licence:
  name: Example Open Licence 1.0
  url: https://example.org/licence
commercial_use: allowed              # allowed | not_allowed | unknown
assistant_reading: permitted         # permitted | not_granted | unknown
storing_text: permitted              # permitted | not_permitted | unknown
linking: permitted                   # permitted | homepage_only | consent_required | unknown
attribution_line: Contains Example State information, Example Open Licence 1.0.
status_lines:                        # shown with the text, e.g. authenticity or "not in force"
  - Extract only.
conditions: []                       # anything that changes handling: share-alike, excluded documents
not_covered:                         # outside the licence but not a handling change: emblems, logos
  - State emblems
signal: green
evidence: Where the copy of the terms is filed.
notes: Optional.
```

`terms`, `date_read` and `read_by` go together: a record has all three (it is
**verified**) or none (it is not). A verified record also needs `review_by`,
`licence` and `evidence`.

`assistant_reading` is its own question. A licence can allow commercial reuse
and still not allow automated or AI analysis of the text, so "commercial use is
allowed" never implies "an assistant may read it".

## Signals

A signal says what may be done with the source's text.

| Signal | Meaning | The record must show |
| --- | --- | --- |
| `green` | Text may be read, shown and used commercially, with attribution | Verified; commercial use allowed; assistant reading permitted; a linking position; an attribution line; no conditions |
| `double_yellow` | As green, with conditions that change handling | As green, with at least one entry in `conditions` |
| `yellow` | Link only | Either not verified at all, or verified and the text may not be read |
| `red` | Restricted: do not use | Verified; commercial use not allowed, or linking needs consent |

The script enforces the table. A record that says commercial use is not
allowed, or that linking needs consent, cannot be anything but red. An
unverified record cannot claim anything about what the terms allow.

## Review

Terms change. Each verified record carries a `review_by` date no more than a
year after it was read. To review: open the terms page, read it again, update
the record and both dates, and rebuild.

## What the first records found

The register was seeded on 20 November 2026 with the sources the Legal
Workflows pilot uses. Reading the terms changed the picture in three places:

- **`IE/Acts`.** legal-sources labels the Irish Statute Book "Irish Open
  Government Licence". The site says its data is under the Oireachtas (Open
  Data) PSI Licence, which incorporates CC BY 4.0. Commercial reuse is allowed
  either way, but the credit the licence asks for is different.
- **`EU/ConsolidatedLegislation`.** legal-sources cites Commission Decision
  2011/833/EU as the licence. That decision covers Commission documents. The
  page that governs EUR-Lex content is the EUR-Lex legal notice, which puts
  consolidated texts under CC BY 4.0 and excludes documents with special
  conditions, such as the international accounting standards.
- **Commercial use is not the whole answer.** `EU/EUR-Lex` is verified and
  allows commercial reuse, and is still link only here, because no attribution
  line is approved for it and its case law names people.

Four sources the product uses have no id in `manifest.yaml` (Companies House,
GLEIF, the UK sanctions list and the gov.uk bank holidays feed), so they
cannot have a record here.

## Licence and credit

The register is part of this fork and is under the GNU Affero General Public
License, version 3 or any later version, like the rest of the repository.
`register.json` carries that notice inside it.

- Source ids, names, countries, addresses and types come from legal-sources,
  Copyright (C) 2025 World Wide Law Contributors.
- The verification records are Copyright (C) 2026 Fraser Matcham.
