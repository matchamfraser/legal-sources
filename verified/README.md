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

Three United Kingdom sources were read later the same day:

- **`UK/LegislationGovUK`** (and `UK/Legislation`, the same site listed twice).
  The Open Government Licence v3.0 applies, as labelled, but "except where
  otherwise stated": legislation originating from the EU needs a second
  acknowledgement, and two contributed collections carry their own
  attributions. Automated access has a fair use policy. Double yellow.
- **`UK/FindCaseLaw`.** The Open Justice Licence v2.0 allows commercial reuse
  and does not cover computational analysis, which the publisher says includes
  using AI or large language models. Verified, and link only.
- **`UK/SRA`.** legal-sources labels it "ogl-3.0". The SRA's pages do not
  mention the Open Government Licence, and its terms of service say website
  material may not be used for commercial purposes. Red. It is the first
  record where the label was not merely imprecise but pointed the wrong way.

Twenty-eight more United Kingdom sources are fetched from GOV.UK, so one set
of terms covers them: GOV.UK's terms and conditions, its page on reusing
content, the Open Government Licence v3.0 and the Content API's page.

- **Seventeen are guidance and publications** (HMRC manuals, HM Land Registry
  practice guides, the Charity Commission, the Competition and Markets
  Authority and others). Double yellow: open, but only what GOV.UK publishes
  under the licence, and content credited to another author is left out.
- **Eleven are tribunal and regulator decisions** (employment tribunals,
  teacher misconduct panels, asylum support and others). The licence allows
  commercial reuse, but the decisions name people and personal data is outside
  it. Verified, and link only, until the data protection check is done.
- Several of these bodies (Ofcom, Ofgem, Ofwat, the Office of Rail and Road,
  the National Crime Agency, the Food Standards Agency) publish most of their
  work on their own websites. Those terms were not read; each record covers
  only what GOV.UK publishes.

The remaining United Kingdom sources labelled "ogl-3.0" each have their own
website, and reading those is where the label failed most often:

- **Six are red.** The Competition Appeal Tribunal, the Financial Conduct
  Authority, the Gambling Commission, the National Audit Office, the Bank of
  England (for the Prudential Regulation Authority) and The Pensions Regulator
  each publish under their own terms: private study, personal or internal
  use, non-commercial use, or copying only with approval. None of those pages
  applies the Open Government Licence to the website as a whole. The FCA
  Handbook and the PRA Rulebook have separate terms, which were not read.
- **Two are open, with their own acknowledgements.** The Information
  Commissioner's Office and the Office for Nuclear Regulation apply the Open
  Government Licence and each says how to credit it. Neither says anything
  about links to its site; linking is recorded as permitted on that basis,
  and the records say so.
- **Seven hold decisions and are link only.** The five Welsh tribunals and the
  Judiciary of Northern Ireland publish under the Open Government Licence, and
  the Privy Council decisions sit on Find Case Law under the Open Justice
  Licence. All name people.
- **One publisher contradicts itself.** The Valuation Tribunal Service's
  copyright page points to the Open Government Licence; its terms of use say
  non-commercial, personal use only. Commercial use is not recorded as
  allowed.
- **Seven could not be read** and have a record that says only that: a site
  that refused the request, or no terms page that could be found.

Four sources the product uses have no id in `manifest.yaml` (Companies House,
GLEIF, the UK sanctions list and the gov.uk bank holidays feed), so they
cannot have a record here.

## The changes feed

`scripts/build_changes_feed.py` builds `verified/changes.json`: titles,
identifiers, dates and links for legislation an official publisher has newly
published or newly consolidated. A scheduled workflow runs it once a day and
commits the file to the `data` branch. The file is never on `main`.

```sh
python3 scripts/build_changes_feed.py --out out/verified/changes.json
```

**It reads a source only while the register says it may.** A source is read
when its record is verified, green or double yellow, allows links, has a
credit line and is not past its `review_by` date. Otherwise it is left out and
named under `skipped` with the reason, and any of its items already in the
feed are dropped. Knowing how to read a source gives the script no permission
to read it: the UK sources stay out until their records are verified.

**It holds no text, and asks for none.**

| Source | What is asked for, each run | What an item is |
| --- | --- | --- |
| `EU/ConsolidatedLegislation` | One query to the Publications Office's metadata service for consolidated versions dated in the last 90 days. | A consolidated version: CELEX number, the act's title, the consolidation date, a EUR-Lex link. |
| `IE/Acts` | The year's two list pages on the Irish Statute Book, Acts and statutory instruments. In the first 90 days of a year, last year's two as well. | An Act or an instrument: year and number, title, a link to the Statute Book. |

- **Rate.** Never more than one request a second to a host, and at most five
  requests a run today.
- **Client name.** The default names the job and gives no person, address or
  contact. To send one, set the repository variable
  `CHANGES_FEED_USER_AGENT`.
- **Addresses.** `https` only, to the named host only, and a redirect anywhere
  else is refused. A link in the feed is built from the identifier, never
  copied from a page.
- **Titles** are treated as untrusted: one line, no control characters, at
  most 400 characters.

**Dates.** The EU service gives each consolidated version a date, and the feed
keeps the ones from the last 90 days up to today. The Irish list pages give a
number and a title and no date, so `date` is `null` and `first_seen` is the
day the feed first saw the item. The feed remembers which numbers it has seen
(`state`), so a number that appears late is still picked up. On its first run
for such a source it takes only the latest few (10 Acts, 30 instruments) and
marks them `seeded`, because everything already on the list was published
before the feed began.

**Limits.** 90 days of items, at most 400 for a source, and the file stays
under 1 MB by dropping the oldest.

**When a publisher fails.** That source keeps the items it had, and its entry
under `sources` says `"ok": false` with a short reason and the time it last
worked. A list that comes back empty after a full one is treated as a failure.
The run fails only when every open source failed.

**If you show the feed,** show each source's `attribution_line` with its
items, say that a consolidated EU text is not the authentic version, and do
not present a `first_seen` day as the day an Irish Act was signed or an
instrument was made.

## Licence and credit

The register is part of this fork and is under the GNU Affero General Public
License, version 3 or any later version, like the rest of the repository.
`register.json` carries that notice inside it.

- Source ids, names, countries, addresses and types come from legal-sources,
  Copyright (C) 2025 World Wide Law Contributors.
- The verification records are Copyright (C) 2026 Fraser Matcham.
- `changes.json` carries the same notice. The titles, identifiers and dates
  in it are each publisher's, reused on the terms in that source's record.
