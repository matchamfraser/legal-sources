"""The fork keeps no upstream sample text for sources whose terms forbid republishing it (TEC-826).

CI checks out only part of the tree, so the test asks git which folders HEAD holds
rather than looking at the working directory.
"""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIST = json.loads((ROOT / "verified" / "samples-removed.json").read_text())["removed"]
REGISTER = {r["id"]: r for r in json.loads((ROOT / "verified" / "register.json").read_text())["records"]}


def _in_head(path: str) -> bool:
    out = subprocess.run(["git", "ls-tree", "--name-only", "HEAD", path],
                         cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return bool(out.strip())


def test_removed_samples_stay_removed():
    # An upstream merge can bring a folder back; resolve it by deleting the folder again.
    back = [s for s in LIST if _in_head(f"sources/{s}/sample")]
    assert not back, f"upstream sample folders came back: {back}"


def test_every_removed_source_is_red():
    # Only a source whose own terms forbid republishing is removed; anything else stays as upstream's.
    assert all(REGISTER[s]["signal"] == "red" for s in LIST)


def test_list_has_no_duplicates():
    assert len(LIST) == len(set(LIST))
