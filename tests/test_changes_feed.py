"""Offline checks for the changes feed. No test here touches the network."""

from datetime import date
import importlib.util
import io
import json
from pathlib import Path
import urllib.error

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_changes_feed.py"
spec = importlib.util.spec_from_file_location("build_changes_feed", SCRIPT)
feed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(feed)

TODAY = date(2026, 11, 20)
NOW = "2026-11-20T05:17:00Z"


def record(source_id, **changes):
    base = {
        "id": source_id,
        "verified": True,
        "signal": "green",
        "linking": "permitted",
        "attribution_line": f"Credit line for {source_id}.",
        "licence": {"name": "Example Open Licence 1.0", "url": "https://example.org/licence"},
        "status_lines": ["Extract only."],
        "conditions": [],
        "date_read": "2026-11-20",
        "review_by": "2027-05-20",
        "source": {"name": "Example statutes", "country": "XX", "url": "https://example.org"},
    }
    base.update(changes)
    return base


def dated(items):
    return {"collect": lambda fetcher, today: items() if callable(items) else items, "hosts": ("example.org",), "dated": True}


def undated(items, seed=2):
    return {
        "collect": lambda fetcher, today: items() if callable(items) else items,
        "hosts": ("example.org",),
        "dated": False,
        "seed": {"eli/{year}/act": seed},
    }


def act(number, year=2026, title=None, form="html"):
    return {
        "id": f"eli/{year}/act/{number}",
        "kind": "act",
        "title": title or f"Example Act No. {number}",
        "date": None,
        "url": f"https://example.org/eli/{year}/act/{number}/enacted/en/{form}",
    }


def consolidated(celex, day, title="Example Regulation"):
    return {"id": celex, "kind": "consolidated_version", "title": title, "date": day, "url": "https://example.org/" + celex}


def build(collectors, records, previous=None, today=TODAY, now=NOW):
    log = []
    result, succeeded = feed.build_feed(
        {r["id"]: r for r in records}, previous or {}, today, now, lambda hosts: None, collectors=collectors, log=log.append
    )
    return result, succeeded, log


# ---------------------------------------------------------------- the gate


class TestWhichSourcesAreRead:
    @pytest.mark.parametrize(
        "changes, reason",
        [
            ({"verified": False}, "not been read"),
            ({"signal": "yellow"}, "not green or double yellow"),
            ({"signal": "red"}, "not green or double yellow"),
            ({"linking": "homepage_only"}, "does not allow links"),
            ({"linking": "unknown"}, "does not allow links"),
            ({"attribution_line": " "}, "no credit line"),
            ({"attribution_line": None}, "no credit line"),
            ({"review_by": "2026-11-19"}, "overdue"),
            ({"review_by": None}, "overdue"),
        ],
    )
    def test_a_record_that_is_not_open_is_never_read(self, changes, reason):
        called = []
        collectors = {"XX/Statutes": dated(lambda: called.append(1) or [])}
        result, succeeded, _ = build(collectors, [record("XX/Statutes", **changes)])
        assert called == []
        assert reason in result["skipped"]["XX/Statutes"]
        assert result["sources"] == {} and result["items"] == [] and succeeded == 0

    def test_a_source_with_no_record_is_never_read(self):
        called = []
        result, _, _ = build({"XX/Statutes": dated(lambda: called.append(1) or [])}, [])
        assert called == [] and "no record" in result["skipped"]["XX/Statutes"]

    def test_double_yellow_is_read_and_its_conditions_travel_with_it(self):
        rec = record("XX/Statutes", signal="double_yellow", conditions=["Some documents are title and link only."])
        result, succeeded, _ = build({"XX/Statutes": dated([consolidated("02020R0001-20261101", "2026-11-01")])}, [rec])
        assert succeeded == 1
        assert result["sources"]["XX/Statutes"]["conditions"] == ["Some documents are title and link only."]
        assert result["sources"]["XX/Statutes"]["attribution_line"] == "Credit line for XX/Statutes."

    def test_items_from_a_source_that_has_closed_are_dropped(self):
        collectors = {"XX/Statutes": dated([consolidated("02020R0001-20261101", "2026-11-01")])}
        first, _, _ = build(collectors, [record("XX/Statutes")])
        assert first["items_count"] == 1
        second, _, _ = build(collectors, [record("XX/Statutes", signal="red")], previous=first)
        assert second["items"] == [] and second["sources"] == {} and second["state"] == {}

    def test_the_real_collectors_are_only_for_sources_in_the_real_register(self):
        records = feed.load_register(feed.DEFAULT_REGISTER)
        assert set(feed.COLLECTORS) <= set(records)
        # Today's register opens these two. A source that is added here and is not open is skipped, not read.
        assert sorted(s for s in feed.COLLECTORS if feed.closed_reason(records[s], TODAY) is None) == [
            "EU/ConsolidatedLegislation",
            "IE/Acts",
        ]

    def test_a_register_in_another_format_stops_the_run(self, tmp_path):
        path = tmp_path / "register.json"
        path.write_text(json.dumps({"schema_version": 2, "records": []}))
        with pytest.raises(feed.FeedError):
            feed.load_register(path)
        path.write_text("not json")
        with pytest.raises(feed.FeedError):
            feed.load_register(path)


# ------------------------------------------------------------ what is kept


class TestMetadataOnly:
    def test_an_item_has_only_the_listed_fields(self):
        noisy = dict(consolidated("02020R0001-20261101", "2026-11-01"), text="The whole act.", body="<p>…</p>")
        result, _, _ = build({"XX/Statutes": dated([noisy])}, [record("XX/Statutes")])
        (item,) = result["items"]
        assert set(item) == {"source", "id", "kind", "title", "date", "first_seen", "url"}
        assert set(item) <= set(feed.ITEM_FIELDS)

    def test_a_title_is_one_capped_line_with_no_control_characters(self):
        assert feed.clean_title("  Finance Act\n\t2026\x00\x1b[31m  ") == "Finance Act 2026 [31m"
        assert feed.clean_title("a‮b​c") == "a b c"
        long = feed.clean_title("x" * 5000)
        assert len(long) == feed.MAX_TITLE and long.endswith("…")
        assert feed.clean_title(None) == "" and feed.clean_title(12) == ""

    def test_the_file_stays_under_its_size_cap_by_dropping_the_oldest(self, monkeypatch):
        monkeypatch.setattr(feed, "MAX_BYTES", 6000)
        items = [consolidated(f"02020R{n:04d}-202611{n:02d}", f"2026-11-{n:02d}", "T" * 300) for n in range(1, 21)]
        result, _, _ = build({"XX/Statutes": dated(items)}, [record("XX/Statutes")])
        assert result["truncated"] is True
        assert len(feed.serialise(result).encode()) <= 6000
        assert 0 < result["items_count"] < 20 == len(items)
        assert result["items"][0]["date"] == "2026-11-20"  # the newest survive
        assert result["sources"]["XX/Statutes"]["items_count"] == result["items_count"]

    def test_each_source_is_capped(self, monkeypatch):
        monkeypatch.setattr(feed, "MAX_ITEMS_PER_SOURCE", 3)
        items = [consolidated(f"02020R{n:04d}-202611{n:02d}", f"2026-11-{n:02d}") for n in range(1, 11)]
        result, _, _ = build({"XX/Statutes": dated(items)}, [record("XX/Statutes")])
        assert [i["date"] for i in result["items"]] == ["2026-11-10", "2026-11-09", "2026-11-08"]

    def test_the_notice_names_the_licence_and_both_copyright_holders(self):
        notice = feed.NOTICE
        assert "Affero" in notice["licence"]
        assert any("World Wide Law Contributors" in line for line in notice["copyright"])
        assert any("Fraser Matcham" in line for line in notice["copyright"])
        assert "holds no text" in notice["what_this_is"]


# ------------------------------------------------------------ dated sources


class TestDatedSources:
    def test_only_the_last_ninety_days_and_nothing_dated_ahead(self):
        payload = {
            "results": {
                "bindings": [
                    {"celex": {"value": "02015L2302-20290329"}, "date": {"value": "2029-03-29"}, "title": {"value": "Ahead"}},
                    {"celex": {"value": "02020R0001-20261120"}, "date": {"value": "2026-11-20"}, "title": {"value": "Today"}},
                    {"celex": {"value": "02020R0002-20260822"}, "date": {"value": "2026-08-22"}, "title": {"value": "Edge"}},
                    {"celex": {"value": "02020R0003-20260821"}, "date": {"value": "2026-08-21"}, "title": {"value": "Too old"}},
                    {"celex": {"value": "02020R0004-20261101"}, "date": {"value": "2026-11-01"}},
                    {"celex": {"value": "32020R0005"}, "date": {"value": "2026-11-01"}, "title": {"value": "Not consolidated"}},
                    {"celex": {"value": "02020R0006-20261101\n<script>"}, "date": {"value": "2026-11-01"}, "title": {"value": "Bad id"}},
                    {"celex": {"value": "02020R0001-20261120"}, "date": {"value": "2026-11-20"}, "title": {"value": "Duplicate"}},
                    {"celex": {"value": "02020R0007-20261101"}, "date": {"value": "1 November"}, "title": {"value": "Bad date"}},
                    "junk",
                ]
            }
        }
        items = feed.parse_eu_results(payload, TODAY)
        assert [i["title"] for i in items] == ["Today", "Edge"]
        assert items[0] == {
            "id": "02020R0001-20261120",
            "kind": "consolidated_version",
            "title": "Today",
            "date": "2026-11-20",
            "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:02020R0001-20261120",
        }

    @pytest.mark.parametrize("payload", [{}, {"results": {}}, {"results": {"bindings": "x"}}, None, []])
    def test_an_unexpected_answer_is_a_failure_not_an_empty_feed(self, payload):
        with pytest.raises(feed.FeedError):
            feed.parse_eu_results(payload, TODAY)

    def test_the_query_asks_for_metadata_inside_the_window_from_one_host(self):
        asked = []

        class Recorder:
            def get(self, url):
                asked.append(url)
                return json.dumps({"results": {"bindings": []}}).encode()

        assert feed.collect_eu_consolidated(Recorder(), TODAY) == []
        (url,) = asked
        assert url.startswith("https://publications.europa.eu/webapi/rdf/sparql?")
        assert "2026-08-22" in url and "2026-11-20" in url
        assert feed.COLLECTORS["EU/ConsolidatedLegislation"]["hosts"] == ("publications.europa.eu",)

    def test_first_seen_is_kept_from_one_day_to_the_next(self):
        items = [consolidated("02020R0001-20261101", "2026-11-01")]
        collectors = {"XX/Statutes": dated(lambda: items)}
        first, _, _ = build(collectors, [record("XX/Statutes")])
        items.append(consolidated("02020R0002-20261119", "2026-11-19"))
        second, _, _ = build(collectors, [record("XX/Statutes")], previous=first, today=date(2026, 11, 21))
        seen = {i["id"]: i["first_seen"] for i in second["items"]}
        assert seen == {"02020R0001-20261101": "2026-11-20", "02020R0002-20261119": "2026-11-21"}
        assert [i["id"] for i in second["items"]] == ["02020R0002-20261119", "02020R0001-20261101"]


# ---------------------------------------------------------- undated sources

ACTS_PAGE = """
<table class="datatable" id="public-acts-dtb"><thead><tr><th>Number</th><th>Hyperlinked Version</th><th>PDF</th></tr></thead>
<tbody>
  <tr><td class="align-center">1</td>
      <td><a href="en/act/pub/0001/index.html">Credit Review Act 2026</a></td>
      <td class="align-center"><a href="../pdf/2026/en.act.2026.0001.pdf" aria-label="Open PDF of Credit Review Act 2026">PDF</a></td></tr>
  <tr><td class="align-center">2</td>
      <td><a href="en/act/pub/0002/index.html">Defamation   (Amendment)
          Act&nbsp;2026</a></td></td>
      <td class="align-center"><a href="../pdf/2026/en.act.2026.0002.pdf">PDF</a></td></tr>
  <tr><td class="align-center">3</td>
      <td>Finance &amp; Budget Act 2026</td>
      <td class="align-center"><a href="../pdf/2026/en.act.2026.0003.pdf">PDF</a></td></tr>
  <tr><td class="align-center">2</td><td><a href="x">A second row numbered two</a></td></tr>
  <tr><td>4</td><td>PDF</td></tr>
  <tr><td>five</td><td><a href="x">Not a numbered row</a></td></tr>
  <tr><td>0</td><td>Number nought Act 2026</td></tr>
</tbody></table>
"""


class TestUndatedSources:
    def test_a_list_page_gives_number_title_and_a_link_built_here(self):
        items = feed.parse_ie_listing(ACTS_PAGE, 2026, "act")
        assert [(i["id"], i["title"]) for i in items] == [
            ("eli/2026/act/1", "Credit Review Act 2026"),
            ("eli/2026/act/2", "Defamation (Amendment) Act 2026"),
            ("eli/2026/act/3", "Finance & Budget Act 2026"),
        ]
        assert items[0]["url"] == "https://www.irishstatutebook.ie/eli/2026/act/1/enacted/en/html"
        # No web page yet, so the link is to the PDF. No address is copied from the page.
        assert items[2]["url"] == "https://www.irishstatutebook.ie/eli/2026/act/3/enacted/en/pdf"
        assert all(i["date"] is None and i["kind"] == "act" for i in items)
        (si,) = feed.parse_ie_listing("<tr><td>7</td><td><a href='/2026/en/si/0007.html'>Example Order 2026.</a></td></tr>", 2026, "si")
        assert si["kind"] == "statutory_instrument"
        assert si["url"] == "https://www.irishstatutebook.ie/eli/2026/si/7/made/en/html"

    def test_the_first_run_takes_only_the_latest_few_and_marks_them(self):
        collectors = {"XX/Statutes": undated([act(n) for n in range(1, 11)], seed=2)}
        result, _, _ = build(collectors, [record("XX/Statutes")])
        assert [(i["id"], i.get("seeded")) for i in result["items"]] == [
            ("eli/2026/act/10", True),
            ("eli/2026/act/9", True),
        ]
        assert result["state"] == {"XX/Statutes": {"seen": {"eli/2026/act": "1-10"}}}

    def test_later_runs_add_what_is_new_including_a_gap_filled_late(self):
        listed = [act(n) for n in (1, 2, 4, 5)]
        collectors = {"XX/Statutes": undated(lambda: listed, seed=1)}
        first, _, _ = build(collectors, [record("XX/Statutes")])
        assert first["state"]["XX/Statutes"]["seen"] == {"eli/2026/act": "1-2,4-5"}
        listed.extend([act(3), act(6, form="pdf")])
        second, _, _ = build(collectors, [record("XX/Statutes")], previous=first, today=date(2026, 11, 21))
        got = {i["id"]: (i["first_seen"], i.get("seeded", False)) for i in second["items"]}
        assert got == {
            "eli/2026/act/5": ("2026-11-20", True),
            "eli/2026/act/3": ("2026-11-21", False),
            "eli/2026/act/6": ("2026-11-21", False),
        }
        assert second["state"]["XX/Statutes"]["seen"] == {"eli/2026/act": "1-6"}
        # Running again the same day changes nothing but the times.
        third, _, _ = build(collectors, [record("XX/Statutes")], previous=second, today=date(2026, 11, 21))
        assert third["items"] == second["items"] and third["state"] == second["state"]

    def test_a_corrected_title_or_link_replaces_the_old_one_and_keeps_the_day(self):
        listed = [act(1, form="pdf")]
        collectors = {"XX/Statutes": undated(lambda: listed, seed=1)}
        first, _, _ = build(collectors, [record("XX/Statutes")])
        listed[0] = act(1, title="Example Act No. 1 (corrected)", form="html")
        second, _, _ = build(collectors, [record("XX/Statutes")], previous=first, today=date(2026, 12, 1))
        (item,) = second["items"]
        assert item["title"].endswith("(corrected)") and item["url"].endswith("/html")
        assert item["first_seen"] == "2026-11-20"

    def test_an_item_leaves_after_ninety_days_and_is_not_mistaken_for_new(self):
        collectors = {"XX/Statutes": undated([act(1)], seed=1)}
        first, _, _ = build(collectors, [record("XX/Statutes")])
        kept, _, _ = build(collectors, [record("XX/Statutes")], previous=first, today=date(2027, 2, 18))
        assert kept["items_count"] == 1
        gone, _, _ = build(collectors, [record("XX/Statutes")], previous=kept, today=date(2027, 2, 19))
        assert gone["items"] == []
        again, _, _ = build(collectors, [record("XX/Statutes")], previous=gone, today=date(2027, 2, 20))
        assert again["items"] == [] and again["state"]["XX/Statutes"]["seen"] == {"eli/2026/act": "1"}

    def test_a_new_year_is_all_new_and_old_years_are_forgotten(self):
        listed = [act(1, year=2026)]
        collectors = {"XX/Statutes": undated(lambda: listed, seed=1)}
        first, _, _ = build(collectors, [record("XX/Statutes")])
        listed[:] = [act(1, year=2027), act(2, year=2027)]
        second, _, _ = build(collectors, [record("XX/Statutes")], previous=first, today=date(2027, 1, 10))
        new = [i["id"] for i in second["items"] if i["first_seen"] == "2027-01-10"]
        assert sorted(new) == ["eli/2027/act/1", "eli/2027/act/2"]
        assert all("seeded" not in i for i in second["items"] if i["id"].startswith("eli/2027"))
        later, _, _ = build(collectors, [record("XX/Statutes", review_by="2029-01-01")], previous=second, today=date(2028, 1, 5))
        assert set(later["state"]["XX/Statutes"]["seen"]) == {"eli/2027/act"}

    def test_the_previous_year_is_listed_only_in_the_first_ninety_days(self):
        assert feed.ie_years(date(2026, 11, 20)) == [2026]
        assert feed.ie_years(date(2027, 1, 1)) == [2027, 2026]
        assert feed.ie_years(date(2027, 3, 31)) == [2027, 2026]
        assert feed.ie_years(date(2027, 4, 1)) == [2027]

    def test_a_year_with_nothing_published_yet_is_empty_not_a_failure(self):
        class Fetcher:
            def get(self, url):
                if "/2027/" in url:
                    raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b""))
                return ACTS_PAGE.encode() if url.endswith("/act/") else b"<table></table>"

        items = feed.collect_ie_statute_book(Fetcher(), date(2027, 1, 2))
        assert [i["id"] for i in items] == ["eli/2026/act/1", "eli/2026/act/2", "eli/2026/act/3"]

    def test_ranges_round_trip_and_ignore_nonsense(self):
        assert feed.pack_ranges([5, 1, 2, 3, 9, 10, 2]) == "1-3,5,9-10"
        assert feed.unpack_ranges("1-3,5,9-10") == {1, 2, 3, 5, 9, 10}
        assert feed.unpack_ranges("1-3,x,7-2,,4") == {1, 2, 3, 4}
        assert feed.unpack_ranges("1-99999999") == set() and feed.unpack_ranges(None) == set()


# ----------------------------------------------------------------- failures


class TestWhenAPublisherFails:
    def failing(self, error):
        def collect(fetcher, today):
            raise error

        return {"collect": collect, "hosts": ("example.org",), "dated": True}

    def test_a_failed_source_keeps_what_it_had_and_says_so(self):
        good = {"XX/Statutes": dated([consolidated("02020R0001-20261101", "2026-11-01")])}
        first, _, _ = build(good, [record("XX/Statutes")])
        error = urllib.error.HTTPError("https://example.org/secret?token=abc", 503, "Service Unavailable", {}, io.BytesIO(b""))
        second, succeeded, log = build(
            {"XX/Statutes": self.failing(error)}, [record("XX/Statutes")], previous=first, today=date(2026, 11, 21), now="2026-11-21T05:17:00Z"
        )
        source = second["sources"]["XX/Statutes"]
        assert succeeded == 0 and source["ok"] is False
        assert source["error"] == "the publisher answered with status 503"
        assert source["last_success"] == NOW and source["checked_at"] == "2026-11-21T05:17:00Z"
        assert [i["id"] for i in second["items"]] == ["02020R0001-20261101"]
        assert "token" not in json.dumps(second) and log == ["failed XX/Statutes: the publisher answered with status 503"]

    def test_one_source_failing_does_not_stop_the_other(self):
        collectors = {
            "XX/Court": self.failing(TimeoutError("timed out")),
            "XX/Statutes": dated([consolidated("02020R0001-20261101", "2026-11-01")]),
        }
        result, succeeded, _ = build(collectors, [record("XX/Statutes"), record("XX/Court")])
        assert succeeded == 1 and result["items_count"] == 1
        assert result["sources"]["XX/Court"]["error"] == "the publisher could not be reached"
        assert result["sources"]["XX/Court"]["last_success"] is None

    def test_an_empty_list_after_a_full_one_is_treated_as_a_failure(self):
        first, _, _ = build({"XX/Statutes": undated([act(1), act(2)], seed=2)}, [record("XX/Statutes")])
        second, succeeded, _ = build({"XX/Statutes": undated([], seed=2)}, [record("XX/Statutes")], previous=first)
        assert succeeded == 0 and second["sources"]["XX/Statutes"]["ok"] is False
        assert second["items"] == first["items"] and second["state"] == first["state"]

    def test_an_unexpected_error_reports_its_kind_and_nothing_else(self):
        result, _, _ = build({"XX/Statutes": self.failing(KeyError("/home/runner/secret"))}, [record("XX/Statutes")])
        assert result["sources"]["XX/Statutes"]["error"] == "unexpected problem (KeyError)"

    def test_the_run_fails_only_when_every_open_source_failed(self, tmp_path, monkeypatch):
        register = tmp_path / "register.json"
        register.write_text(json.dumps({"schema_version": 1, "records": [record("XX/Statutes"), record("XX/Court")]}))
        out = tmp_path / "out" / "changes.json"
        both = {"XX/Statutes": self.failing(TimeoutError()), "XX/Court": self.failing(TimeoutError())}
        monkeypatch.setattr(feed, "COLLECTORS", both)
        assert feed.main(["--register", str(register), "--out", str(out), "--today", "2026-11-20"]) == 1
        assert json.loads(out.read_text())["items"] == []
        monkeypatch.setattr(feed, "COLLECTORS", dict(both, **{"XX/Court": dated([])}))
        assert feed.main(["--register", str(register), "--out", str(out), "--today", "2026-11-20"]) == 0

    def test_an_unreadable_previous_feed_stops_the_run_and_writes_nothing(self, tmp_path, monkeypatch):
        register = tmp_path / "register.json"
        register.write_text(json.dumps({"schema_version": 1, "records": [record("XX/Statutes")]}))
        monkeypatch.setattr(feed, "COLLECTORS", {"XX/Statutes": dated([])})
        out = tmp_path / "changes.json"
        for text in ("{ not json", json.dumps({"schema_version": 99}), json.dumps([1])):
            previous = tmp_path / "previous.json"
            previous.write_text(text)
            code = feed.main(["--register", str(register), "--previous", str(previous), "--out", str(out)])
            assert code == 1 and not out.exists()
        # A missing or empty previous file is a first run.
        (tmp_path / "previous.json").write_text("")
        assert feed.main(["--register", str(register), "--previous", str(tmp_path / "previous.json"), "--out", str(out)]) == 0


# ----------------------------------------------------------------- fetching


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    def __init__(self, body=b"ok"):
        self.body = body
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append((request.full_url, dict(request.header_items()), timeout))
        return FakeResponse(self.body)


class FakeClock:
    def __init__(self):
        self.now = 100.0
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(round(seconds, 3))
        self.now += seconds


class TestFetching:
    def fetcher(self, opener=None, **kwargs):
        clock = FakeClock()
        made = feed.Fetcher(("a.example", "b.example"), opener=opener or FakeOpener(), clock=clock, sleep=clock.sleep, **kwargs)
        return made, clock

    def test_never_faster_than_one_request_a_second_for_a_host(self):
        fetcher, clock = self.fetcher()
        fetcher.get("https://a.example/1")
        clock.now += 0.25
        fetcher.get("https://a.example/2")
        fetcher.get("https://b.example/1")  # another host has its own clock
        clock.now += 5
        fetcher.get("https://a.example/3")
        assert clock.slept == [0.75] and fetcher.requests == 4
        assert feed.MIN_INTERVAL_SECONDS >= 1.0

    @pytest.mark.parametrize(
        "url",
        ["http://a.example/x", "https://c.example/x", "https://a.example.evil.test/x", "file:///etc/passwd", "ftp://a.example/x"],
    )
    def test_only_https_and_only_the_named_hosts(self, url):
        opener = FakeOpener()
        fetcher, _ = self.fetcher(opener)
        with pytest.raises(feed.FeedError):
            fetcher.get(url)
        assert opener.requests == []

    def test_a_redirect_to_another_host_is_refused(self):
        handler = feed._SameHostRedirects(frozenset({"a.example"}))
        with pytest.raises(feed.FeedError):
            handler.redirect_request(None, None, 302, "Found", {}, "https://elsewhere.example/x")
        with pytest.raises(feed.FeedError):
            handler.redirect_request(None, None, 302, "Found", {}, "http://a.example/x")

    def test_the_default_client_name_gives_no_name_address_or_contact(self, monkeypatch):
        opener = FakeOpener()
        fetcher, _ = self.fetcher(opener)
        fetcher.get("https://a.example/1")
        agent = opener.requests[0][1]["User-agent"]
        assert agent == feed.DEFAULT_USER_AGENT
        assert not any(mark in agent.lower() for mark in ("@", "http", "github", "matcham", "signal", "workflows"))
        assert opener.requests[0][2] == feed.REQUEST_TIMEOUT_SECONDS

    def test_an_operator_can_set_the_client_name(self):
        opener = FakeOpener()
        fetcher, _ = self.fetcher(opener, user_agent="example-feed/1.0 (ops@example.org)")
        fetcher.get("https://a.example/1")
        assert opener.requests[0][1]["User-agent"] == "example-feed/1.0 (ops@example.org)"

    def test_an_oversized_answer_is_refused(self, monkeypatch):
        monkeypatch.setattr(feed, "MAX_RESPONSE_BYTES", 10)
        fetcher, _ = self.fetcher(FakeOpener(b"x" * 11))
        with pytest.raises(feed.FeedError):
            fetcher.get("https://a.example/1")
        fetcher, _ = self.fetcher(FakeOpener(b"x" * 10))
        assert fetcher.get("https://a.example/1") == b"x" * 10
