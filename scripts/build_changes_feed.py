#!/usr/bin/env python3
"""Build the daily changes feed: titles, identifiers, dates and links only.

The feed lists legislation that an official publisher has newly published or
newly consolidated. It never holds the text of a document, and it never asks a
publisher for one. A source is read only while its record in the verified
terms register is open (green or double yellow), verified, in date, allows
links and carries a credit line. Anything else is skipped, and items already
in the feed from a source that has closed are dropped.

    python3 scripts/build_changes_feed.py --out out/verified/changes.json
    python3 scripts/build_changes_feed.py --previous old.json --out new.json

The scheduled workflow ``.github/workflows/changes-feed.yml`` runs this once a
day and commits the result to the ``data`` branch, never to ``main``.
Format and rules: ``verified/README.md``.

Copyright (C) 2026 Fraser Matcham.
Licensed under the GNU Affero General Public License, version 3 or any later
version. Added to this fork of legal-sources on 20 November 2026.
"""

import argparse
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTER = ROOT / "verified" / "register.json"

SCHEMA_VERSION = 1
REGISTER_SCHEMA_VERSION = 1
WINDOW_DAYS = 90
MAX_ITEMS_PER_SOURCE = 400
MAX_BYTES = 1_000_000
MAX_TITLE = 400
OPEN_SIGNALS = ("green", "double_yellow")

# The page that explains this job is its public repository. legislation.gov.uk's fair use policy refuses
# anonymous clients and asks for a contact or such a page; no email address or person's name is sent.
DEFAULT_USER_AGENT = (
    "changes-feed/1.0 (+https://github.com/matchamfraser/legal-sources; "
    "legislation titles, dates and links only; one request a second at most)"
)
USER_AGENT_ENV = "CHANGES_FEED_USER_AGENT"
MIN_INTERVAL_SECONDS = 1.0
REQUEST_TIMEOUT_SECONDS = 60
MAX_RESPONSE_BYTES = 5_000_000

ITEM_FIELDS = ("source", "id", "kind", "title", "date", "first_seen", "url", "seeded")

NOTICE = {
    "title": "Changes feed for official legal sources",
    "what_this_is": (
        "Titles, identifiers, dates and links for legislation an official "
        "publisher has newly published or newly consolidated. It holds no "
        "text of any document. It is information, not legal advice, and it is "
        "not a complete or official list: follow the link and rely on the "
        "publisher."
    ),
    "credits": (
        "Titles, identifiers and dates are each publisher's. Show the "
        "attribution_line given under sources for every source whose items "
        "you show. No publisher endorses this feed."
    ),
    "licence": "GNU Affero General Public License, version 3 or any later version",
    "licence_url": "https://www.gnu.org/licenses/agpl-3.0.html",
    "copyright": [
        "Source ids and names: Copyright (C) 2025 World Wide Law Contributors "
        "(legal-sources, https://github.com/worldwidelaw/legal-sources).",
        "Verification records and this compilation: Copyright (C) 2026 Fraser Matcham.",
    ],
    "source": "https://github.com/matchamfraser/legal-sources",
    "modified": "This fork of legal-sources was modified by Fraser Matcham from 20 November 2026.",
}


class FeedError(Exception):
    """A problem that stops one source, or the whole run, with a short reason."""


# --------------------------------------------------------------------------
# Fetching: https only, named hosts only, one request a second for each host.
# --------------------------------------------------------------------------


class _SameHostRedirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_hosts):
        self.allowed_hosts = allowed_hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parts = urllib.parse.urlsplit(newurl)
        if parts.scheme != "https" or parts.hostname not in self.allowed_hosts:
            raise FeedError("redirect to a host that is not allowed")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Fetcher:
    """GET a page from an allowed host, never faster than one a second for each host, and slower where a publisher asks."""

    def __init__(self, allowed_hosts, user_agent=None, opener=None, clock=time.monotonic, sleep=time.sleep, min_interval=None):
        self.allowed_hosts = frozenset(allowed_hosts)
        # A publisher's own crawl delay can only lengthen the wait, never shorten it.
        self.min_interval = max(MIN_INTERVAL_SECONDS, min_interval or 0)
        self.user_agent = user_agent or DEFAULT_USER_AGENT
        self.opener = opener or urllib.request.build_opener(_SameHostRedirects(self.allowed_hosts))
        self.clock = clock
        self.sleep = sleep
        self.requests = 0
        self._last = {}

    def get(self, url):
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "https" or parts.hostname not in self.allowed_hosts:
            raise FeedError("address is not on the allowed list")
        last = self._last.get(parts.hostname)
        if last is not None:
            wait = self.min_interval - (self.clock() - last)
            if wait > 0:
                self.sleep(wait)
        self._last[parts.hostname] = self.clock()
        self.requests += 1
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent, "Accept": "*/*"})
        with self.opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise FeedError("response is larger than expected")
        return body


# --------------------------------------------------------------------------
# Text from a publisher is untrusted: one line, no control characters, capped.
# --------------------------------------------------------------------------


def clean_title(value):
    if not isinstance(value, str):
        return ""
    text = unicodedata.normalize("NFC", value)
    text = "".join(" " if unicodedata.category(ch)[0] in ("C", "Z") else ch for ch in text)
    text = re.sub(r" +", " ", text).strip()
    if len(text) > MAX_TITLE:
        text = text[: MAX_TITLE - 1].rstrip() + "…"
    return text


def parse_day(value):
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


# --------------------------------------------------------------------------
# European Union: consolidated versions, from the Publications Office's
# metadata service. One query a run. It returns metadata, never a document.
# --------------------------------------------------------------------------

EU_HOST = "publications.europa.eu"
EU_SPARQL = "https://publications.europa.eu/webapi/rdf/sparql"
EU_LIMIT = 1000
EU_CELEX_RE = re.compile(r"0[0-9]{4}[A-Z]{1,2}[0-9]{4}(?:\([0-9]{1,2}\))?-[0-9]{8}")
EU_QUERY = """
PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
SELECT ?celex ?date ?title WHERE {{
  ?work cdm:resource_legal_id_celex ?celex .
  FILTER(REGEX(STR(?celex), "^0[0-9]{{4}}"))
  ?work cdm:work_date_document ?date .
  FILTER(?date >= "{start}"^^<http://www.w3.org/2001/XMLSchema#date> && ?date <= "{end}"^^<http://www.w3.org/2001/XMLSchema#date>)
  OPTIONAL {{
    ?exp cdm:expression_belongs_to_work ?work ;
         cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/ENG> ;
         cdm:expression_title ?title .
  }}
}}
ORDER BY DESC(?date) ?celex
LIMIT {limit}
"""


def parse_eu_results(payload, today):
    """Rows from the metadata service -> items. Anything unexpected is left out."""
    try:
        rows = payload["results"]["bindings"]
    except (KeyError, TypeError):
        raise FeedError("unexpected answer from the metadata service")
    if not isinstance(rows, list):
        raise FeedError("unexpected answer from the metadata service")
    start = today - timedelta(days=WINDOW_DAYS)
    items = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        celex = (row.get("celex") or {}).get("value")
        day = parse_day((row.get("date") or {}).get("value"))
        title = clean_title((row.get("title") or {}).get("value"))
        if not isinstance(celex, str) or not EU_CELEX_RE.fullmatch(celex):
            continue
        if day is None or not (start <= day <= today) or not title or celex in items:
            continue
        items[celex] = {
            "id": celex,
            "kind": "consolidated_version",
            "title": title,
            "date": day.isoformat(),
            "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:" + urllib.parse.quote(celex, safe=""),
        }
    return list(items.values())


def collect_eu_consolidated(fetcher, today):
    start = today - timedelta(days=WINDOW_DAYS)
    query = EU_QUERY.format(start=start.isoformat(), end=today.isoformat(), limit=EU_LIMIT)
    address = EU_SPARQL + "?" + urllib.parse.urlencode({"query": query, "format": "application/sparql-results+json"})
    try:
        payload = json.loads(fetcher.get(address).decode("utf-8"))
    except ValueError:
        raise FeedError("the metadata service did not answer in JSON")
    return parse_eu_results(payload, today)


# --------------------------------------------------------------------------
# Ireland: the year's lists of Acts and statutory instruments on the Irish
# Statute Book. Two list pages a run (four in the first weeks of a year). The
# lists give a number and a title and no date, so an item's date is unknown
# and the feed records the day it first saw the item.
# --------------------------------------------------------------------------

IE_HOST = "www.irishstatutebook.ie"
IE_BASE = "https://www.irishstatutebook.ie"
IE_KINDS = {"act": ("act", "enacted"), "si": ("statutory_instrument", "made")}
IE_SEED = {"act": 10, "si": 30}
_IE_NOT_TITLES = {"pdf", "html", "hyperlinked", "print", "not yet available"}


class _ListingRows(HTMLParser):
    """Rows of a list page: the first cell's text, the second cell's text, and whether it is a link."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self._cell = -1
        self._text = None
        self._linked = False

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._close_row()
            self._cell = -1
            self._text = ["", ""]
            self._linked = False
        elif tag == "td" and self._text is not None:
            self._cell += 1
        elif tag == "a" and self._text is not None and self._cell == 1:
            self._linked = True

    def handle_endtag(self, tag):
        if tag in ("tr", "table", "tbody"):
            self._close_row()

    def handle_data(self, data):
        if self._text is not None and self._cell in (0, 1):
            self._text[self._cell] += data

    def _close_row(self):
        if self._text is not None:
            self.rows.append((self._text[0], self._text[1], self._linked))
        self._text = None

    def close(self):
        super().close()
        self._close_row()


def parse_ie_listing(page, year, kind):
    """A year's list page -> items. ``kind`` is "act" or "si"."""
    label, stage = IE_KINDS[kind]
    parser = _ListingRows()
    parser.feed(page)
    parser.close()
    items = {}
    for first, second, linked in parser.rows:
        number_text = first.strip()
        title = clean_title(second)
        if not re.fullmatch(r"[0-9]{1,4}", number_text):
            continue
        number = int(number_text)
        if number < 1 or len(title) < 5 or title.lower() in _IE_NOT_TITLES or number in items:
            continue
        # A new instrument is often listed as a PDF before its web page exists.
        form = "html" if linked else "pdf"
        items[number] = {
            "id": f"eli/{year}/{kind}/{number}",
            "kind": label,
            "title": title,
            "date": None,
            "url": f"{IE_BASE}/eli/{year}/{kind}/{number}/{stage}/en/{form}",
        }
    return [items[number] for number in sorted(items)]


def ie_years(today):
    years = [today.year]
    if (today - date(today.year, 1, 1)).days < WINDOW_DAYS:
        years.append(today.year - 1)
    return years


def collect_ie_statute_book(fetcher, today):
    items = []
    for year in ie_years(today):
        for kind in IE_KINDS:
            try:
                page = fetcher.get(f"{IE_BASE}/eli/{year}/{kind}/").decode("utf-8", errors="replace")
            except urllib.error.HTTPError as error:
                if error.code == 404:  # nothing published yet this year
                    continue
                raise
            items.extend(parse_ie_listing(page, year, kind))
    return items


# --------------------------------------------------------------------------
# United Kingdom: legislation.gov.uk's own feed of newly published
# legislation, which its fair use policy points to in place of crawling. It
# is read a page of 20 at a time, newest first, five seconds apart as the
# site's robots.txt asks, and only until a page holds nothing new. The feed
# also carries each item's explanatory note; that is text, and is not kept.
# --------------------------------------------------------------------------

UK_HOST = "www.legislation.gov.uk"
UK_FEED = "https://www.legislation.gov.uk/new/data.feed"
UK_CRAWL_DELAY_SECONDS = 5.0
UK_MAX_PAGES = 5
UK_PAGE_SIZE = 20
UK_ID_RE = re.compile(r"https?://www\.legislation\.gov\.uk/id/([a-z]{2,8})/([0-9]{4})/([0-9]{1,13})")
UK_ACTS = {"ukpga", "ukla", "asp", "asc", "anaw", "mwa", "nia", "ukcm"}
UK_DRAFTS = {"ukdsi", "sdsi", "nidsr"}
_ATOM = "{http://www.w3.org/2005/Atom}"
_UKM = "{http://www.legislation.gov.uk/namespaces/metadata}"
_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


def _uk_title(entry):
    """The entry's title. A Welsh instrument gives it in English and Welsh; the English is taken."""
    title = entry.find(_ATOM + "title")
    if title is None:
        return ""
    english = [node for node in title.iter() if node.get(_XML_LANG) == "en"]
    return clean_title("".join((english[0] if english else title).itertext()))


def parse_uk_feed(page, today):
    """One page of the feed -> (items, entries on the page). Anything unexpected is left out."""
    if "<!DOCTYPE" in page or "<!ENTITY" in page:
        raise FeedError("the feed declares entities, which a feed should not")
    try:
        root = ElementTree.fromstring(page)
    except ElementTree.ParseError:
        raise FeedError("the feed is not well-formed XML")
    if root.tag != _ATOM + "feed":
        raise FeedError("the answer is not an Atom feed")
    start = today - timedelta(days=WINDOW_DAYS)
    entries = root.findall(_ATOM + "entry")
    items = {}
    for entry in entries:
        match = UK_ID_RE.fullmatch((entry.findtext(_ATOM + "id") or "").strip())
        day = parse_day((entry.findtext(_ATOM + "published") or "")[:10])
        title = _uk_title(entry)
        if not match or day is None or not (start <= day <= today) or not title:
            continue
        code, year, number = match.groups()
        # A made instrument can also list the draft it came from, so it is a draft only if every type says so.
        types = [node.get("Value") or "" for node in entry.findall(_UKM + "DocumentMainType")]
        draft = code in UK_DRAFTS or (bool(types) and all("Draft" in value for value in types))
        identifier = f"{code}/{year}/{number}"
        if identifier in items:
            continue
        kind = "draft_statutory_instrument" if draft else "act" if code in UK_ACTS else "statutory_instrument"
        items[identifier] = {
            "id": identifier,
            "kind": kind,
            "title": title,
            "date": day.isoformat(),  # the day legislation.gov.uk published it, not the day it was made
            "url": f"https://www.legislation.gov.uk/{identifier}",
        }
    return list(items.values()), len(entries)


def collect_uk_legislation(fetcher, today, known=frozenset()):
    """Newest first, stopping at the first page that holds nothing the feed has not already seen."""
    items = {}
    for page_number in range(1, UK_MAX_PAGES + 1):
        address = UK_FEED if page_number == 1 else f"{UK_FEED}?page={page_number}"
        found, on_page = parse_uk_feed(fetcher.get(address).decode("utf-8", errors="replace"), today)
        fresh = [item for item in found if item["id"] not in known and item["id"] not in items]
        for item in found:
            items.setdefault(item["id"], item)
        if not fresh or on_page < UK_PAGE_SIZE:
            break
    return list(items.values())


# --------------------------------------------------------------------------
# The sources this script knows how to read. A source is read only when its
# register record is open; being listed here gives no permission by itself.
# "dated" sources give each item a date. For the others the feed remembers
# which identifiers it has seen and dates an item by when it first saw it.
# An "incremental" source is read newest first and only as far as needed, so
# what it returns adds to what the feed already holds and does not replace it.
# --------------------------------------------------------------------------

COLLECTORS = {
    "EU/ConsolidatedLegislation": {
        "collect": collect_eu_consolidated,
        "hosts": (EU_HOST,),
        "dated": True,
    },
    "UK/LegislationGovUK": {
        "collect": collect_uk_legislation,
        "hosts": (UK_HOST,),
        "dated": True,
        "incremental": True,
        "min_interval": UK_CRAWL_DELAY_SECONDS,
    },
    "IE/Acts": {
        "collect": collect_ie_statute_book,
        "hosts": (IE_HOST,),
        "dated": False,
        "seed": {"eli/{year}/act": IE_SEED["act"], "eli/{year}/si": IE_SEED["si"]},
    },
}


def closed_reason(record, today):
    """Why a source may not be read, or None when its record is open."""
    if not isinstance(record, dict):
        return "no record in the register"
    if record.get("verified") is not True:
        return "its terms have not been read for the register"
    if record.get("signal") not in OPEN_SIGNALS:
        return "its signal is not green or double yellow"
    if record.get("linking") != "permitted":
        return "its record does not allow links to documents"
    if not isinstance(record.get("attribution_line"), str) or not record["attribution_line"].strip():
        return "its record has no credit line"
    review_by = parse_day(record.get("review_by"))
    if review_by is None or review_by < today:
        return "its terms are overdue for re-reading"
    return None


def load_register(path):
    try:
        register = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise FeedError("the register could not be read")
    if not isinstance(register, dict) or register.get("schema_version") != REGISTER_SCHEMA_VERSION:
        raise FeedError("the register is not in the format this script reads")
    records = register.get("records")
    if not isinstance(records, list):
        raise FeedError("the register has no records")
    return {r["id"]: r for r in records if isinstance(r, dict) and isinstance(r.get("id"), str)}


# --------------------------------------------------------------------------
# Remembering what has been seen, as ranges: {"eli/2026/si": "1-588"}.
# --------------------------------------------------------------------------


def split_id(identifier):
    prefix, _, number = identifier.rpartition("/")
    if not prefix or not re.fullmatch(r"[0-9]{1,6}", number):
        raise FeedError("identifier is not in the form prefix/number")
    return prefix, int(number)


def pack_ranges(numbers):
    parts = []
    run = []
    for number in sorted(set(numbers)):
        if run and number == run[-1] + 1:
            run.append(number)
            continue
        if run:
            parts.append(run)
        run = [number]
    if run:
        parts.append(run)
    return ",".join(str(r[0]) if len(r) == 1 else f"{r[0]}-{r[-1]}" for r in parts)


def unpack_ranges(text):
    numbers = set()
    if not isinstance(text, str) or not text:
        return numbers
    for part in text.split(","):
        match = re.fullmatch(r"([0-9]{1,6})(?:-([0-9]{1,6}))?", part)
        if not match:
            continue
        low = int(match.group(1))
        high = int(match.group(2) or low)
        if low <= high and high - low <= 100_000:
            numbers.update(range(low, high + 1))
    return numbers


# --------------------------------------------------------------------------
# Putting a run together with the run before it.
# --------------------------------------------------------------------------


def _previous_items(previous, source_id):
    items = previous.get("items") if isinstance(previous, dict) else None
    kept = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and item.get("source") == source_id and isinstance(item.get("id"), str):
            if parse_day(item.get("first_seen")) is not None and clean_title(item.get("title")):
                kept.append(item)
    return kept


def _shown_day(item):
    """The day an item is filed under: the publisher's date, else the day the feed first saw it."""
    return item.get("date") or item["first_seen"]


def _number(item):
    match = re.search(r"([0-9]+)(?:-[0-9]{8})?$", item["id"])
    return int(match.group(1)) if match else 0


def _order(items):
    return sorted(items, key=lambda i: (_shown_day(i), i["source"], _number(i), i["id"]), reverse=True)


def merge_dated(source_id, collected, earlier, today, incremental=False):
    """Dated sources: the feed is what the publisher lists inside the window.

    An incremental source is only read as far back as it needs to be, so the
    items it did not return this time are kept from the run before.
    """
    first_seen = {item["id"]: item["first_seen"] for item in earlier}
    merged = [
        {"source": source_id, **item, "first_seen": first_seen.get(item["id"], today.isoformat())}
        for item in collected
    ]
    if incremental:
        returned = {item["id"] for item in collected}
        merged += [
            {"source": source_id, **{k: item.get(k) for k in ("id", "kind", "title", "date", "url", "first_seen")}}
            for item in earlier
            if item["id"] not in returned and parse_day(item.get("date")) is not None
        ]
    return merged


def merge_undated(source_id, collected, earlier, seen_state, seed, today):
    """Undated sources: an item is new when its identifier has not been seen before."""
    listed = {item["id"]: item for item in collected}
    seen = {prefix: unpack_ranges(text) for prefix, text in (seen_state or {}).items() if isinstance(prefix, str)}
    first_run = not seen
    out = []
    for item in earlier:
        current = listed.get(item["id"])
        kept = {"source": source_id, **{k: item.get(k) for k in ("id", "kind", "title", "date", "url")}}
        if current:  # the title or the link may have been corrected since
            kept.update(current)
        kept["first_seen"] = item["first_seen"]
        if item.get("seeded") is True:
            kept["seeded"] = True
        out.append(kept)
    have = {item["id"] for item in out}

    by_prefix = {}
    for identifier in listed:
        prefix, number = split_id(identifier)
        by_prefix.setdefault(prefix, []).append(number)

    for prefix, numbers in by_prefix.items():
        known = seen.get(prefix, set())
        fresh = sorted(n for n in numbers if n not in known)
        seeded = first_run
        if first_run:
            # The first time, take only the latest few: the rest were published before the feed began.
            pattern = re.sub(r"/[0-9]{4}/", "/{year}/", prefix + "/", count=1).rstrip("/")
            fresh = fresh[-seed.get(pattern, 0):] if seed.get(pattern, 0) else []
        for number in fresh:
            identifier = f"{prefix}/{number}"
            if identifier in have:
                continue
            item = {"source": source_id, **listed[identifier], "first_seen": today.isoformat()}
            if seeded:
                item["seeded"] = True
            out.append(item)
        seen[prefix] = known | set(numbers)

    oldest_year = today.year - 1
    state = {}
    for prefix, numbers in sorted(seen.items()):
        year = re.search(r"/([0-9]{4})/", prefix + "/")
        if year and int(year.group(1)) < oldest_year:
            continue
        if numbers:
            state[prefix] = pack_ranges(numbers)
    return out, state


def _in_window(items, today):
    start = (today - timedelta(days=WINDOW_DAYS)).isoformat()
    return [item for item in items if start <= _shown_day(item) <= today.isoformat()]


def _tidy(item):
    return {key: item[key] for key in ITEM_FIELDS if key in item and not (key == "seeded" and item[key] is not True)}


def _source_summary(record):
    source = record.get("source") if isinstance(record.get("source"), dict) else {}
    return {
        "name": source.get("name"),
        "country": source.get("country"),
        "signal": record["signal"],
        "attribution_line": record["attribution_line"],
        "licence": record.get("licence"),
        "status_lines": record.get("status_lines") or [],
        "conditions": record.get("conditions") or [],
        "date_read": record.get("date_read"),
        "review_by": record.get("review_by"),
    }


def build_feed(records, previous, today, now, fetch_factory, collectors=None, log=print):
    """Read every open source and return the feed. A source that fails keeps what it had."""
    collectors = COLLECTORS if collectors is None else collectors
    previous = previous if isinstance(previous, dict) else {}
    previous_sources = previous.get("sources") if isinstance(previous.get("sources"), dict) else {}
    previous_state = previous.get("state") if isinstance(previous.get("state"), dict) else {}
    sources, skipped, state, items = {}, {}, {}, []
    succeeded = 0

    for source_id in sorted(collectors):
        collector = collectors[source_id]
        record = records.get(source_id)
        reason = closed_reason(record, today)
        if reason:
            skipped[source_id] = reason
            log(f"skipped {source_id}: {reason}")
            continue

        earlier = _previous_items(previous, source_id)
        earlier_state = previous_state.get(source_id) if isinstance(previous_state.get(source_id), dict) else {}
        before = previous_sources.get(source_id) if isinstance(previous_sources.get(source_id), dict) else {}
        summary = _source_summary(record)
        error = None
        try:
            incremental = bool(collector.get("incremental"))
            fetcher = fetch_factory(collector)
            if incremental:
                collected = collector["collect"](fetcher, today, frozenset(item["id"] for item in earlier))
            else:
                collected = collector["collect"](fetcher, today)
            if not collected and (earlier or earlier_state):
                raise FeedError("the publisher listed nothing, which is not believable")
            if collector["dated"]:
                merged, new_state = merge_dated(source_id, collected, earlier, today, incremental), {}
            else:
                merged, new_state = merge_undated(
                    source_id, collected, earlier, earlier_state.get("seen"), collector.get("seed", {}), today
                )
                new_state = {"seen": new_state}
        except Exception as problem:  # one source failing must not lose the others
            error = _describe(problem)
            merged = [{"source": source_id, **item} for item in earlier]
            new_state = earlier_state
            log(f"failed {source_id}: {error}")
        else:
            succeeded += 1

        merged = _order(_in_window(merged, today))[:MAX_ITEMS_PER_SOURCE]
        items.extend(merged)
        if new_state:
            state[source_id] = new_state
        summary.update(
            ok=error is None,
            error=error,
            checked_at=now,
            last_success=now if error is None else before.get("last_success"),
            items_count=len(merged),
        )
        sources[source_id] = summary

    items = [_tidy(item) for item in _order(items)]
    feed = {
        "_notice": NOTICE,
        "schema_version": SCHEMA_VERSION,
        "generated_at": now,
        "window_days": WINDOW_DAYS,
        "sources": sources,
        "skipped": skipped,
        "truncated": False,
        "items_count": len(items),
        "items": items,
        "state": state,
    }
    while len(serialise(feed).encode("utf-8")) > MAX_BYTES and feed["items"]:
        feed["items"] = feed["items"][: max(0, len(feed["items"]) * 9 // 10)]  # the oldest go first
        feed["truncated"] = True
        feed["items_count"] = len(feed["items"])
        for source_id, summary in feed["sources"].items():
            summary["items_count"] = sum(1 for item in feed["items"] if item["source"] == source_id)
    return feed, succeeded


def _describe(problem):
    if isinstance(problem, FeedError):
        return str(problem)
    if isinstance(problem, urllib.error.HTTPError):
        return f"the publisher answered with status {problem.code}"
    if isinstance(problem, (urllib.error.URLError, TimeoutError, OSError)):
        return "the publisher could not be reached"
    return f"unexpected problem ({type(problem).__name__})"


def serialise(feed):
    return json.dumps(feed, ensure_ascii=False, indent=1) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--register", type=Path, default=DEFAULT_REGISTER)
    parser.add_argument("--previous", type=Path, help="yesterday's feed, if there is one")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--today", help="YYYY-MM-DD, for tests; the default is today in UTC")
    args = parser.parse_args(argv)

    moment = datetime.now(timezone.utc).replace(microsecond=0)
    today = parse_day(args.today) if args.today else moment.date()
    if today is None:
        parser.error("--today must be YYYY-MM-DD")
    now = moment.strftime("%Y-%m-%dT%H:%M:%SZ")

    previous = {}
    if args.previous and args.previous.is_file() and args.previous.stat().st_size:
        try:
            previous = json.loads(args.previous.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            print("The previous feed could not be read. Stopping, so it is not replaced by a first run.", file=sys.stderr)
            return 1
        if not isinstance(previous, dict) or previous.get("schema_version") != SCHEMA_VERSION:
            print("The previous feed is not in this script's format. Stopping.", file=sys.stderr)
            return 1

    try:
        records = load_register(args.register)
    except FeedError as problem:
        print(f"Stopping: {problem}.", file=sys.stderr)
        return 1

    user_agent = os.environ.get(USER_AGENT_ENV, "").strip() or DEFAULT_USER_AGENT
    in_actions = os.environ.get("GITHUB_ACTIONS") == "true"

    def log(message):
        print(f"::warning::{message}" if in_actions and message.startswith("failed") else message)

    feed, succeeded = build_feed(records, previous, today, now, lambda collector: Fetcher(collector["hosts"], user_agent, min_interval=collector.get("min_interval")), log=log)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(serialise(feed), encoding="utf-8")
    print(f"{feed['items_count']} items from {succeeded} of {len(feed['sources'])} open sources -> {args.out}")
    # Red only when every open source failed, so one bad day at one publisher is a warning.
    return 1 if feed["sources"] and not succeeded else 0


if __name__ == "__main__":
    sys.exit(main())
