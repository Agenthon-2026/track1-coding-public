"""Synthetic Track 1 unit shared by cross-repository scorer tests, not a task solution."""

import json
from pathlib import Path


def write_unit(unit: Path, output: Path) -> None:
    (unit / "checks").mkdir(parents=True)
    output.mkdir(parents=True)
    (unit / "card.toml").write_text('schema_version = "2.0"\n[task]\nsplit = "public-dev"\n')
    (unit / "manifest.json").write_text(json.dumps({"files": []}))
    (unit / "checks/test_outputs.py").write_text(
        'import json, os, pathlib\n'
        'OUTPUT_DIR = pathlib.Path(os.environ["OUTPUT_DIR"])\n'
        'def test_result():\n'
        '    path = OUTPUT_DIR / "results.json"\n'
        '    assert path.is_file()\n'
        '    assert json.loads(path.read_text()) == {"synthetic": 42}\n'
    )
    (output / "results.json").write_text('{"synthetic": 42}')
    (output / "reward.json").write_text('{"reward": 1.0}')
