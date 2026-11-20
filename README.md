# The `data` branch

This branch holds one generated file, [`verified/changes.json`](verified/changes.json):
titles, identifiers, dates and links for legislation that an official publisher
has newly published or newly consolidated. It holds no text of any document.

A scheduled job on `main` rebuilds the file once a day and commits it here.
Nothing else is committed to this branch, and nobody edits the file by hand.

- **What it is not.** It is not a complete or official list, and it is not
  legal advice. Follow each link and rely on the publisher.
- **Which sources.** Only sources whose record in the verified terms register
  is green or double yellow, in date, and allows links. The file names every
  source it read under `sources`, and every source it left out under
  `skipped`, with the reason.
- **Credits.** If you show items from a source, show that source's
  `attribution_line` with them. No publisher endorses this feed.
- **Dates.** `date` is the publisher's date where the publisher gives one.
  Where it is `null`, the publisher's list gave none, and `first_seen` is the
  day this feed first saw the item, not the day it was made. An item marked
  `seeded` was already published when the feed began.
- **Licence.** GNU Affero General Public License, version 3 or any later
  version: see `LICENSE` and the `_notice` inside the file. Titles,
  identifiers and dates are each publisher's.

How it is built, and the rules it follows:
[`verified/README.md` on `main`](https://github.com/matchamfraser/legal-sources/blob/main/verified/README.md#the-changes-feed).
This repository is a modified fork of
[worldwidelaw/legal-sources](https://github.com/worldwidelaw/legal-sources);
see [`FORK.md` on `main`](https://github.com/matchamfraser/legal-sources/blob/main/FORK.md).
