#!/usr/bin/env python3
"""Validate the verified terms records and export them as one JSON file.

Each record under ``verified/sources/<CC>/<Source>.yaml`` states what a named
person found when they read a source's own terms on a given date. The licence
labels in ``manifest.yaml``, ``docs/licenses.json`` and the ``config.yaml``
files are leads only; nothing here is inferred from them.

    python3 scripts/build_verified_register.py            # validate and write
    python3 scripts/build_verified_register.py --check    # validate, compare, write nothing

Format, signal rules and the review routine: ``verified/README.md``.

Copyright (C) 2026 Fraser Matcham.
Licensed under the GNU Affero General Public License, version 3 or any later
version. Added to this fork of legal-sources on 20 November 2026.
"""

import argparse
from datetime import date, timedelta
import json
from pathlib import Path
import re
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECORDS = ROOT / "verified" / "sources"
DEFAULT_MANIFEST = ROOT / "manifest.yaml"
DEFAULT_OUTPUT = ROOT / "verified" / "register.json"
SCHEMA_VERSION = 1
MAX_REVIEW_DAYS = 366

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")
SIGNALS = ("green", "double_yellow", "yellow", "red")
COMMERCIAL = ("allowed", "not_allowed", "unknown")
READING = ("permitted", "not_granted", "unknown")
STORING = ("permitted", "not_permitted", "unknown")
LINKING = ("permitted", "homepage_only", "consent_required", "unknown")
FIELDS = {
    "id", "terms", "date_read", "read_by", "licence", "commercial_use",
    "assistant_reading", "storing_text", "linking", "attribution_line",
    "status_lines", "conditions", "not_covered", "signal", "review_by",
    "evidence", "notes",
}
# What the reader takes from manifest.yaml for convenience. These are facts
# about the source, not licence claims; the manifest's licence labels are
# deliberately not copied.
MANIFEST_FIELDS = ("name", "country", "url", "data_types")

NOTICE = {
    "title": "Verified terms register for official legal sources",
    "what_this_is": (
        "Each record states what a named person found when they read the "
        "source's own terms on the date given. It is information, not legal "
        "advice. Terms change: check the terms page before relying on a record "
        "past its review_by date."
    ),
    "licence": "GNU Affero General Public License, version 3 or any later version",
    "licence_url": "https://www.gnu.org/licenses/agpl-3.0.html",
    "copyright": [
        "Source ids, names, countries, addresses and types: Copyright (C) 2025 "
        "World Wide Law Contributors (legal-sources, https://github.com/worldwidelaw/legal-sources).",
        "Verification records: Copyright (C) 2026 Fraser Matcham.",
    ],
    "source": "https://github.com/matchamfraser/legal-sources",
    "modified": "This fork of legal-sources was modified by Fraser Matcham from 20 November 2026.",
}


class RecordError(ValueError):
    """A record that must not be published."""


def _need(condition, message):
    if not condition:
        raise RecordError(message)


def _text(record, field, required):
    value = record.get(field)
    if value is None and not required:
        return
    _need(isinstance(value, str) and value.strip() == value and value != "",
          f"{field} must be a non-empty string with no surrounding space")


def _texts(record, field):
    value = record.get(field, [])
    _need(isinstance(value, list) and all(isinstance(v, str) and v.strip() for v in value),
          f"{field} must be a list of non-empty strings")
    return value


def _https(value, field):
    _need(isinstance(value, str) and value.startswith("https://") and " " not in value,
          f"{field} must be an https address")


def _day(record, field):
    value = record.get(field)
    if isinstance(value, date) and not hasattr(value, "hour"):
        return value
    _need(False, f"{field} must be a date written as YYYY-MM-DD")


def _choice(record, field, allowed):
    value = record.get(field, "unknown")
    _need(value in allowed, f"{field} must be one of: {', '.join(allowed)}")
    return value


def validate_record(record, *, expected_id, manifest_ids, today):
    """Check one record. Raises RecordError; returns the normalised record."""
    _need(isinstance(record, dict), "a record must be a mapping")
    unknown = sorted(set(record) - FIELDS)
    _need(not unknown, f"unknown field(s): {', '.join(unknown)}")

    source_id = record.get("id")
    _need(isinstance(source_id, str) and ID_RE.match(source_id), "id must look like CC/SourceName")
    _need(source_id == expected_id, f"id {source_id!r} does not match its path ({expected_id!r})")
    _need(source_id in manifest_ids, f"id {source_id!r} is not in manifest.yaml")

    signal = record.get("signal")
    _need(signal in SIGNALS, f"signal must be one of: {', '.join(SIGNALS)}")
    commercial = _choice(record, "commercial_use", COMMERCIAL)
    reading = _choice(record, "assistant_reading", READING)
    storing = _choice(record, "storing_text", STORING)
    linking = _choice(record, "linking", LINKING)
    conditions = _texts(record, "conditions")
    not_covered = _texts(record, "not_covered")
    status_lines = _texts(record, "status_lines")
    for field in ("attribution_line", "evidence", "notes", "read_by"):
        _text(record, field, required=False)

    terms = record.get("terms", [])
    _need(isinstance(terms, list), "terms must be a list")
    for entry in terms:
        _need(isinstance(entry, dict) and set(entry) <= {"title", "url"} and "url" in entry,
              "each terms entry needs a url and may have a title")
        _https(entry["url"], "terms url")
        _text(entry, "title", required=False)

    licence = record.get("licence")
    if licence is not None:
        _need(isinstance(licence, dict) and set(licence) <= {"name", "url"} and "name" in licence,
              "licence needs a name and may have a url")
        _text(licence, "name", required=True)
        if licence.get("url") is not None:
            _https(licence["url"], "licence url")

    # "Verified" means a person read the terms: where, when and who are all on
    # the record. A record with only some of the three is a mistake, not a draft.
    has = [bool(terms), "date_read" in record, "read_by" in record]
    _need(all(has) or not any(has),
          "terms, date_read and read_by go together: give all three or none")
    verified = all(has)
    date_read = review_by = None
    if verified:
        date_read = _day(record, "date_read")
        _need(date_read <= today, "date_read is in the future")
        review_by = _day(record, "review_by")
        _need(date_read < review_by <= date_read + timedelta(days=MAX_REVIEW_DAYS),
              f"review_by must be after date_read and within {MAX_REVIEW_DAYS} days of it")
        _need(licence is not None, "a verified record names the licence or terms")
        _text(record, "evidence", required=True)
    else:
        _need("review_by" not in record, "review_by belongs on a verified record")
        _need(signal == "yellow", "an unverified record can only be yellow (link only)")
        _need(commercial == "unknown" and reading == "unknown" and storing == "unknown",
              "an unverified record cannot claim what the terms allow")

    if signal in ("green", "double_yellow"):
        _need(commercial == "allowed", f"{signal} needs commercial_use: allowed")
        _need(reading == "permitted", f"{signal} needs assistant_reading: permitted")
        _need(linking in ("permitted", "homepage_only"), f"{signal} needs a linking position")
        _text(record, "attribution_line", required=True)
        if signal == "green":
            _need(not conditions, "a record with conditions is double_yellow, not green")
        else:
            _need(conditions, "double_yellow needs at least one condition")
    if signal == "red":
        _need(commercial == "not_allowed" or linking == "consent_required",
              "red needs commercial_use: not_allowed or linking: consent_required")
    else:
        _need(commercial != "not_allowed", "commercial_use: not_allowed is red")
        _need(linking != "consent_required", "linking: consent_required is red")

    out = {
        "id": source_id,
        "signal": signal,
        "verified": verified,
        "terms": [{k: entry[k] for k in ("title", "url") if k in entry} for entry in terms],
        "date_read": date_read.isoformat() if date_read else None,
        "read_by": record.get("read_by"),
        "review_by": review_by.isoformat() if review_by else None,
        "licence": licence,
        "commercial_use": commercial,
        "assistant_reading": reading,
        "storing_text": storing,
        "linking": linking,
        "attribution_line": record.get("attribution_line"),
        "status_lines": status_lines,
        "conditions": conditions,
        "not_covered": not_covered,
        "evidence": record.get("evidence"),
        "notes": record.get("notes"),
    }
    return out


def load_manifest(path):
    """Return {id: {name, country, url, data_types}} from manifest.yaml."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    sources = data.get("sources") if isinstance(data, dict) else None
    _need(isinstance(sources, list), "manifest.yaml has no sources list")
    return {s["id"]: {f: s.get(f) for f in MANIFEST_FIELDS}
            for s in sources if isinstance(s, dict) and isinstance(s.get("id"), str)}


def build(records_dir=DEFAULT_RECORDS, manifest=DEFAULT_MANIFEST, today=None):
    """Validate every record and return the register as a dict.

    Raises RecordError naming every bad file, so one run shows all of them.
    """
    today = today or date.today()
    known = load_manifest(manifest)
    records_dir = Path(records_dir)
    records, problems = [], []
    for path in sorted(records_dir.rglob("*")):
        if path.is_dir() or path.name == ".gitkeep":
            continue
        relative = path.relative_to(records_dir)
        if path.suffix != ".yaml" or len(relative.parts) != 2:
            problems.append(f"{relative}: records live at <CC>/<Source>.yaml and nowhere else")
            continue
        expected_id = f"{relative.parts[0]}/{path.stem}"
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            record = validate_record(raw, expected_id=expected_id, manifest_ids=known, today=today)
        except (RecordError, yaml.YAMLError, UnicodeError) as error:
            problems.append(f"{relative}: {error}")
            continue
        record["source"] = known[expected_id]
        records.append(record)
    if problems:
        raise RecordError("\n".join(problems))
    read_dates = [r["date_read"] for r in records if r["date_read"]]
    return {
        "_notice": NOTICE,
        "schema_version": SCHEMA_VERSION,
        "records_count": len(records),
        "latest_date_read": max(read_dates) if read_dates else None,
        "signals": {signal: sum(1 for r in records if r["signal"] == signal) for signal in SIGNALS},
        "records": records,
    }


def render(register):
    """The exact bytes of register.json: stable, so a re-run changes nothing."""
    return json.dumps(register, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="validate and fail if register.json is out of date; write nothing")
    parser.add_argument("--records", default=DEFAULT_RECORDS, type=Path)
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST, type=Path)
    parser.add_argument("--output", default=DEFAULT_OUTPUT, type=Path)
    args = parser.parse_args(argv)
    try:
        text = render(build(args.records, args.manifest))
    except RecordError as error:
        print(f"Verified register is not valid:\n{error}", file=sys.stderr)
        return 1
    if args.check:
        current = args.output.read_text(encoding="utf-8") if args.output.exists() else None
        if current != text:
            print(f"{args.output} is out of date: run scripts/build_verified_register.py", file=sys.stderr)
            return 1
        print("Verified register is valid and up to date.")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
