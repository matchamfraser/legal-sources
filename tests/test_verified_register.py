"""Offline checks for the verified terms register (fictional sources only)."""

from datetime import date
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_verified_register.py"
spec = importlib.util.spec_from_file_location("build_verified_register", SCRIPT)
register = importlib.util.module_from_spec(spec)
spec.loader.exec_module(register)

TODAY = date(2026, 11, 20)
MANIFEST_IDS = {"XX/Statutes", "XX/Court"}


def verified(**changes):
    record = {
        "id": "XX/Statutes",
        "terms": [{"title": "Reuse terms", "url": "https://example.org/terms"}],
        "date_read": date(2026, 11, 20),
        "read_by": "A Reader",
        "review_by": date(2027, 5, 20),
        "licence": {"name": "Example Open Licence 1.0", "url": "https://example.org/licence"},
        "commercial_use": "allowed",
        "assistant_reading": "permitted",
        "storing_text": "permitted",
        "linking": "permitted",
        "attribution_line": "Contains Example State information, Example Open Licence 1.0.",
        "status_lines": ["Extract only."],
        "not_covered": ["State emblems"],
        "signal": "green",
        "evidence": "Copy of the terms page filed with the compliance records.",
    }
    record.update(changes)
    return {key: value for key, value in record.items() if value is not None}


def check(record, expected_id="XX/Statutes"):
    return register.validate_record(record, expected_id=expected_id, manifest_ids=MANIFEST_IDS, today=TODAY)


def rejected(record, message, **kwargs):
    with pytest.raises(register.RecordError, match=message):
        check(record, **kwargs)


def test_a_complete_green_record_passes():
    out = check(verified())
    assert out["verified"] is True and out["signal"] == "green"
    assert out["date_read"] == "2026-11-20" and out["review_by"] == "2027-05-20"


def test_an_unverified_record_is_link_only():
    out = check({"id": "XX/Statutes", "signal": "yellow", "linking": "permitted"})
    assert out["verified"] is False and out["commercial_use"] == "unknown"
    rejected({"id": "XX/Statutes", "signal": "green"}, "unverified record can only be yellow")
    rejected({"id": "XX/Statutes", "signal": "yellow", "commercial_use": "allowed"},
             "cannot claim what the terms allow")
    rejected({"id": "XX/Statutes", "signal": "yellow", "review_by": date(2027, 1, 1)},
             "review_by belongs on a verified record")


@pytest.mark.parametrize("missing", ["terms", "date_read", "read_by"])
def test_where_when_and_who_go_together(missing):
    rejected(verified(**{missing: None}), "give all three or none")


def test_green_needs_everything_the_product_relies_on():
    rejected(verified(commercial_use="unknown"), "green needs commercial_use: allowed")
    rejected(verified(assistant_reading="not_granted"), "green needs assistant_reading: permitted")
    rejected(verified(linking="unknown"), "green needs a linking position")
    rejected(verified(attribution_line=None), "attribution_line must be a non-empty string")
    rejected(verified(licence=None), "names the licence or terms")
    rejected(verified(evidence=None), "evidence must be a non-empty string")


def test_conditions_decide_between_green_and_double_yellow():
    conditions = ["Documents listed in exclusions.yaml are title and link only."]
    rejected(verified(conditions=conditions), "double_yellow, not green")
    assert check(verified(conditions=conditions, signal="double_yellow"))["signal"] == "double_yellow"
    rejected(verified(signal="double_yellow"), "double_yellow needs at least one condition")


def test_a_verified_source_the_assistant_may_not_read_is_yellow():
    out = check(verified(assistant_reading="not_granted", signal="yellow"))
    assert out["verified"] is True and out["assistant_reading"] == "not_granted"


def test_red_is_for_restrictions_and_restrictions_are_red():
    assert check(verified(commercial_use="not_allowed", signal="red"))["signal"] == "red"
    assert check(verified(linking="consent_required", signal="red"))["signal"] == "red"
    rejected(verified(signal="red"), "red needs")
    rejected(verified(commercial_use="not_allowed", assistant_reading="unknown", signal="yellow"),
             "not_allowed is red")
    rejected(verified(linking="consent_required", assistant_reading="unknown", signal="yellow"),
             "consent_required is red")


def test_dates_are_real_and_reviews_are_due_within_a_year():
    rejected(verified(date_read=date(2026, 11, 21)), "date_read is in the future")
    rejected(verified(review_by=date(2026, 11, 20)), "review_by must be after date_read")
    rejected(verified(review_by=date(2027, 11, 22)), "within 366 days")
    rejected(verified(date_read="20 November 2026"), "date_read must be a date")


def test_ids_addresses_and_fields_are_checked():
    rejected(verified(id="XX/Other"), "does not match its path")
    rejected(verified(id="XX/Missing"), "is not in manifest.yaml", expected_id="XX/Missing")
    rejected(verified(terms=[{"url": "http://example.org/terms"}]), "terms url must be an https address")
    rejected(verified(license_id="ogd"), "unknown field")
    rejected(verified(signal="amber"), "signal must be one of")
    rejected(verified(commercial_use=True), "commercial_use must be one of")


def write_tree(tmp_path, records):
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(yaml.safe_dump({"sources": [
        {"id": "XX/Statutes", "name": "Example Statute Book", "country": "XX",
         "url": "https://example.org", "data_types": ["legislation"],
         "license_id": "ogd", "commercial_use": True},
        {"id": "XX/Court", "name": "Example Court", "country": "XX",
         "url": "https://court.example.org", "data_types": ["case_law"]},
    ]}), encoding="utf-8")
    folder = tmp_path / "sources"
    for relative, record in records.items():
        path = folder / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(record if isinstance(record, str) else yaml.safe_dump(record), encoding="utf-8")
    folder.mkdir(exist_ok=True)
    return folder, manifest


def test_build_exports_records_with_source_facts_but_no_manifest_licence_labels(tmp_path):
    folder, manifest = write_tree(tmp_path, {
        "XX/Statutes.yaml": verified(),
        "XX/Court.yaml": {"id": "XX/Court", "signal": "yellow"},
    })
    out = register.build(folder, manifest, today=TODAY)
    assert out["records_count"] == 2 and out["latest_date_read"] == "2026-11-20"
    assert out["signals"] == {"green": 1, "double_yellow": 0, "yellow": 1, "red": 0}
    assert [r["id"] for r in out["records"]] == ["XX/Court", "XX/Statutes"]
    statutes = out["records"][1]
    assert statutes["source"] == {"name": "Example Statute Book", "country": "XX",
                                  "url": "https://example.org", "data_types": ["legislation"]}
    text = register.render(out)
    assert "ogd" not in text and "license_id" not in text
    assert "World Wide Law Contributors" in text and "Fraser Matcham" in text
    assert text == register.render(register.build(folder, manifest, today=TODAY))


def test_build_reports_every_bad_file_at_once(tmp_path):
    folder, manifest = write_tree(tmp_path, {
        "XX/Statutes.yaml": verified(commercial_use="unknown"),
        "XX/Court.yaml": "id: [unclosed",
        "XX/deep/Extra.yaml": {"id": "XX/Extra", "signal": "yellow"},
        "notes.txt": "stray",
    })
    with pytest.raises(register.RecordError) as error:
        register.build(folder, manifest, today=TODAY)
    message = str(error.value)
    for name in ("XX/Statutes.yaml", "XX/Court.yaml", "XX/deep/Extra.yaml", "notes.txt"):
        assert name in message


def test_check_mode_fails_on_a_stale_export_and_writes_nothing(tmp_path):
    folder, manifest = write_tree(tmp_path, {"XX/Statutes.yaml": verified()})
    output = tmp_path / "register.json"
    args = ["--records", str(folder), "--manifest", str(manifest), "--output", str(output)]
    assert register.main(["--check", *args]) == 1 and not output.exists()
    assert register.main(args) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["records_count"] == 1
    assert register.main(["--check", *args]) == 0
    output.write_text("{}\n", encoding="utf-8")
    assert register.main(["--check", *args]) == 1 and output.read_text(encoding="utf-8") == "{}\n"


def test_the_committed_register_is_valid_and_up_to_date():
    done = subprocess.run([sys.executable, str(SCRIPT), "--check"], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
