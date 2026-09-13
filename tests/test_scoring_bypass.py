"""Correctness must come from the grader's checks, never from the submission's own file.

`reward.json` is written by the submission's container. Until 2026-08-28 the gate chain read it and
admitted on its contents: measured on a real unit, an output directory containing nothing but
`{"reward": 1.0}` -- no solution, no deliverable, nothing executed -- was admitted with score 1.0,
identical to a genuinely correct submission. `checks_dir`, the documented "harness re-runs pytest"
path, appeared only in a docstring and was never read.

`reward.json` is OPTIONAL since 2026-09-02: it is written by `checks/test.sh`, and `checks/` is
stripped from every mounted tree, so a participant container normally cannot write it. Requiring
it at g1 made every real Track 1 submission inadmissible before the grader ran. It never decided
anything; now it is not needed either.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import stat
import textwrap

import pytest

from qfbench2_common.contracts import OrganizerFault

from qfbench2_track_coding import scoring
from qfbench2_track_coding.scoring import _g3_domain_semantics

CHECKS = textwrap.dedent(
    """
    import os, pathlib
    OUTPUT_DIR = pathlib.Path(os.environ.get("OUTPUT_DIR") or "/app/output")

    def test_deliverable():
        p = OUTPUT_DIR / "answer.txt"
        assert p.exists(), f"no deliverable at {p}"
        assert p.read_text().strip() == "42"
    """
)


@pytest.fixture
def unit(tmp_path: pathlib.Path) -> pathlib.Path:
    u = tmp_path / "unit"
    (u / "checks").mkdir(parents=True)
    (u / "checks" / "test_outputs.py").write_text(CHECKS, encoding="utf-8")
    (u / "card.toml").write_text('schema_version = "2.0"\n[task]\nsplit = "public-dev"\n', encoding="utf-8")
    (u / "manifest.json").write_text(json.dumps({"files": []}), encoding="utf-8")
    return u


def _verdict(unit: pathlib.Path, out: pathlib.Path):
    return _g3_domain_semantics({"unit_dir": str(unit), "output_dir": str(out)})


def _out(tmp_path: pathlib.Path, *, deliverable: str | None, reward) -> pathlib.Path:
    o = tmp_path / "out"
    o.mkdir(exist_ok=True)
    if deliverable is not None:
        (o / "answer.txt").write_text(deliverable, encoding="utf-8")
    if reward is not None:
        (o / "reward.json").write_text(
            reward if isinstance(reward, str) else json.dumps({"reward": reward}), encoding="utf-8"
        )
    return o


class TestTheSubmissionCannotScoreItself:
    def test_a_forged_reward_with_no_deliverable_is_refused(self, unit, tmp_path):
        """The bypass, as it was. This is the whole point of the file."""
        r = _verdict(unit, _out(tmp_path, deliverable=None, reward=1.0))
        assert not r.passed

    def test_a_forged_reward_over_a_wrong_deliverable_is_refused(self, unit, tmp_path):
        r = _verdict(unit, _out(tmp_path, deliverable="99", reward=1.0))
        assert not r.passed

    def test_a_correct_submission_that_under_reports_itself_still_passes(self, unit, tmp_path):
        """Admission comes from the checks, so the claim cannot lower it either."""
        r = _verdict(unit, _out(tmp_path, deliverable="42", reward=0.0))
        assert r.passed


class TestGenuineOutcomes:
    def test_a_genuinely_correct_submission_passes(self, unit, tmp_path):
        r = _verdict(unit, _out(tmp_path, deliverable="42", reward=1.0))
        assert r.passed
        assert r.detail["trusted_checks"] == "ran"

    def test_failed_checks_are_refused(self, unit, tmp_path):
        assert not _verdict(unit, _out(tmp_path, deliverable="wrong", reward=1.0)).passed

    def test_missing_output_is_refused(self, unit, tmp_path):
        o = tmp_path / "empty"
        o.mkdir()
        assert not _verdict(unit, o).passed

    def test_malformed_reward_json_is_refused(self, unit, tmp_path):
        assert not _verdict(unit, _out(tmp_path, deliverable="42", reward="NOT-JSON")).passed


class TestAGateThatCannotRunDoesNotPass:
    """Global rule 7: a required check that cannot execute fails, it never reports green.

    Since 2026-09-10 "fails" means an `OrganizerFault` when the reason is ours. A unit that ships
    no checks, or checks the scorer cannot point at the output, cannot judge anybody; the old
    `trusted_checks="absent"` / `"not_redirectable"` returns were filed by g3 as the
    participant's `T1_WRONG_NUMERIC`.
    """

    def test_absent_checks_are_an_organizer_fault(self, unit, tmp_path):
        (unit / "checks" / "test_outputs.py").unlink()
        with pytest.raises(OrganizerFault):
            _verdict(unit, _out(tmp_path, deliverable="42", reward=1.0))

    def test_checks_that_read_neither_the_env_nor_a_bound_path_are_an_organizer_fault(
        self, unit, tmp_path
    ):
        """Genuinely non-executable: no OUTPUT_DIR, no path the harness binds. Nothing the
        scorer can present would make these read the submission's output."""
        (unit / "checks" / "test_outputs.py").write_text(
            'import pathlib\nOUTPUT_DIR = pathlib.Path("/srv/somewhere-else")\n'
            "def test_x():\n    assert (OUTPUT_DIR / 'answer.txt').exists()\n",
            encoding="utf-8",
        )
        with pytest.raises(OrganizerFault):
            _verdict(unit, _out(tmp_path, deliverable="42", reward=1.0))


class TestChecksThatHardcodeTheOutputPath:
    """The platform scores every unit with `output_dir = res/<unit>`, never `/app/output`, and
    48 of the 87 Development units' checks hardcode `/app/output` (measured 2026-09-10). Until
    this suite existed the scorer refused them as `not_redirectable` and g3 charged the refusal
    to the participant, so on 48 units the verdict did not depend on the submission.

    The scorer now presents the output at the path the checks name for the duration of that
    unit's checks. `/app/output` itself needs root to create, so these tests point
    `_PRESENTABLE_OUTPUT_PATHS` at a temporary tree and write checks that hardcode THAT path;
    the code under test is identical, only the constant differs.
    """

    @pytest.fixture
    def app_output(self, tmp_path: pathlib.Path, monkeypatch) -> pathlib.Path:
        """The stand-in for `/app/output` (first) and `/output` (second). Neither exists yet,
        and `/app` -- the parent -- does not exist either, as on a scoring image that ships
        no `/app`."""
        app = tmp_path / "app" / "output"
        bare = tmp_path / "output"
        monkeypatch.setattr(scoring, "_PRESENTABLE_OUTPUT_PATHS", (str(app), str(bare)))
        return app

    @staticmethod
    def _hardcode(unit: pathlib.Path, path: pathlib.Path, *, body: str | None = None) -> None:
        (unit / "checks" / "test_outputs.py").write_text(
            f"import pathlib\nOUTPUT_DIR = pathlib.Path({str(path)!r})\n"
            + (
                body
                or "def test_deliverable():\n"
                "    p = OUTPUT_DIR / 'answer.txt'\n"
                "    assert p.exists(), f'no deliverable at {p}'\n"
                "    assert p.read_text().strip() == '42'\n"
            ),
            encoding="utf-8",
        )

    def test_a_correct_submission_is_admissible(self, unit, tmp_path, app_output):
        self._hardcode(unit, app_output)
        r = _verdict(unit, _out(tmp_path, deliverable="42", reward=None))
        assert r.passed, r.detail
        assert r.detail["trusted_checks"] == "ran"
        assert r.detail["output_presented_at"] == [str(app_output)]

    def test_a_wrong_submission_gets_the_checks_own_failure(self, unit, tmp_path, app_output):
        """Not a refusal: pytest ran, exit 1, the assertion the unit's author wrote."""
        self._hardcode(unit, app_output)
        r = _verdict(unit, _out(tmp_path, deliverable="wrong", reward=None))
        assert not r.passed
        assert r.detail["trusted_checks"] == "ran"
        assert r.detail["pytest_returncode"] == 1
        assert "assert" in r.detail["tail"]

    def test_the_presented_path_is_gone_afterwards_pass_and_fail(self, unit, tmp_path, app_output):
        self._hardcode(unit, app_output)
        for deliverable in ("42", "wrong"):
            _verdict(unit, _out(tmp_path, deliverable=deliverable, reward=None))
            assert not os.path.lexists(app_output), "the directory outlived the unit's checks"
            assert not app_output.parent.exists(), "the parent we created was left behind"
        # The submission's output itself is untouched by the presentation and its removal.
        assert (tmp_path / "out" / "answer.txt").read_text() == "wrong"

    def test_the_presented_path_is_gone_even_when_the_checks_crash(
        self, unit, tmp_path, app_output
    ):
        self._hardcode(unit, app_output, body="raise RuntimeError('boom at import')\n")
        r = _verdict(unit, _out(tmp_path, deliverable="42", reward=None))
        assert not r.passed
        assert not os.path.lexists(app_output)

    def test_the_presented_path_is_gone_even_when_pytest_itself_faults(
        self, unit, tmp_path, app_output
    ):
        """Exit 4 raises OrganizerFault from inside the `with`; the cleanup still runs."""
        self._hardcode(unit, app_output)
        (unit / "pytest.ini").write_text(
            "[pytest]\naddopts = --this-flag-does-not-exist\n", encoding="utf-8"
        )
        with pytest.raises(OrganizerFault):
            _verdict(unit, _out(tmp_path, deliverable="42", reward=None))
        assert not os.path.lexists(app_output)

    def test_a_pre_existing_directory_that_is_not_ours_is_an_organizer_fault_and_untouched(
        self, unit, tmp_path, app_output
    ):
        app_output.mkdir(parents=True)
        (app_output / "someone-elses-file").write_text("keep me", encoding="utf-8")
        self._hardcode(unit, app_output)
        with pytest.raises(OrganizerFault):
            _verdict(unit, _out(tmp_path, deliverable="42", reward=None))
        assert app_output.is_dir() and not app_output.is_symlink()
        assert (app_output / "someone-elses-file").read_text() == "keep me"

    def test_a_pre_existing_symlink_that_is_not_ours_is_an_organizer_fault_and_untouched(
        self, unit, tmp_path, app_output
    ):
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        app_output.parent.mkdir(parents=True)
        app_output.symlink_to(elsewhere, target_is_directory=True)
        self._hardcode(unit, app_output)
        with pytest.raises(OrganizerFault):
            _verdict(unit, _out(tmp_path, deliverable="42", reward=None))
        assert app_output.is_symlink() and os.readlink(app_output) == str(elsewhere)

    def test_a_parent_that_cannot_be_created_is_an_organizer_fault(
        self, unit, tmp_path, app_output
    ):
        app_output.parent.write_text("a file where /app should be", encoding="utf-8")
        self._hardcode(unit, app_output)
        with pytest.raises(OrganizerFault):
            _verdict(unit, _out(tmp_path, deliverable="42", reward=None))
        assert app_output.parent.is_file()

    def test_the_second_bound_path_is_presented_too(self, unit, tmp_path, app_output):
        """A minority of units name a bare `/output`; the harness binds both, so does this."""
        bare = pathlib.Path(scoring._PRESENTABLE_OUTPUT_PATHS[1])
        self._hardcode(unit, bare)
        r = _verdict(unit, _out(tmp_path, deliverable="42", reward=None))
        assert r.passed, r.detail
        assert r.detail["output_presented_at"] == [str(bare)]
        assert not os.path.lexists(bare)
        assert not os.path.lexists(app_output), "the unnamed path must not be touched"

    def test_output_dir_aware_checks_are_unchanged(self, unit, tmp_path, app_output):
        """The 39 env-aware units keep the env route: nothing is presented, nothing created."""
        r = _verdict(unit, _out(tmp_path, deliverable="42", reward=None))
        assert r.passed, r.detail
        assert r.detail["output_presented_at"] == []
        assert not os.path.lexists(app_output)
        assert not _verdict(unit, _out(tmp_path, deliverable="wrong", reward=None)).passed

    def test_the_value_first_env_spelling_counts_as_redirectable(self, unit, tmp_path, app_output):
        """`d = os.environ.get("OUTPUT_DIR", "/app/output")` was classified as hardcoded by the
        shipped `OUTPUT_DIR[^\\n]*(environ|getenv)`; it reads the env and needs no presenting."""
        (unit / "checks" / "test_outputs.py").write_text(
            "import os, pathlib\n"
            f"d = os.environ.get('OUTPUT_DIR', {str(app_output)!r})\n"
            "def test_deliverable():\n"
            "    assert (pathlib.Path(d) / 'answer.txt').read_text().strip() == '42'\n",
            encoding="utf-8",
        )
        r = _verdict(unit, _out(tmp_path, deliverable="42", reward=None))
        assert r.passed, r.detail
        assert r.detail["output_presented_at"] == []


class TestTheClassifierOverTheRoster:
    """Every published unit must be one the scorer can execute outside its container: either
    its checks read OUTPUT_DIR, or they name a path the scorer presents. A unit that does
    neither is an organizer fault on the leaderboard, so it must be an error here first.
    Counts only; no unit content is printed."""

    def test_every_public_unit_is_executable_by_the_platform_scorer(self):
        units_dir = pathlib.Path(__file__).resolve().parent.parent / "units"
        units = sorted(p for p in units_dir.iterdir() if p.is_dir())
        assert units, "no units found; refusing to pass an empty scan"
        redirectable = hardcoded = 0
        for u in units:
            source = (u / "checks" / "test_outputs.py").read_text(errors="replace")
            if scoring._REDIRECTABLE_RE.search(source):
                redirectable += 1
            else:
                assert scoring._static_output_paths(source), (
                    f"{u.name}: checks read neither OUTPUT_DIR nor a bound path"
                )
                hardcoded += 1
        print(f"\nroster census: env-aware={redirectable} hardcoded={hardcoded} of {len(units)}")
        assert redirectable + hardcoded == len(units)

    def test_no_public_unit_executes_code_from_the_output_location(self):
        """The precondition `_present_output_at` documents and cannot enforce: the checks read
        the submission's output, they never run it. A check that imports, `exec`s or spawns
        what the submission wrote would hand that code the presentation directory, and the
        "organizer material" reasoning behind every `OrganizerFault` there stops holding.
        Measured 2026-09-10: 0 of 87. Keep it 0. Counts only; no unit content is printed."""
        units_dir = pathlib.Path(__file__).resolve().parent.parent / "units"
        units = sorted(p for p in units_dir.iterdir() if p.is_dir())
        assert units, "no units found; refusing to pass an empty scan"
        offenders = []
        for u in units:
            source = (u / "checks" / "test_outputs.py").read_text(errors="replace")
            if scoring._calls_executing_from_output(source):
                offenders.append(u.name)
        assert not offenders, f"checks that execute from the output location: {offenders}"
        print(f"\nroster census: {len(units)} units, 0 execute code from the output location")

    @pytest.mark.parametrize(
        "source",
        [
            'subprocess.run([sys.executable, str(OUTPUT_DIR / "solve.py")])',
            'subprocess.run(\n    ["python",\n     "/app/output/solve.py"],\n)',
            'sys.path.insert(0, "/output")',
            'importlib.util.spec_from_file_location("m", output_dir / "m.py")',
            'exec(open(OUTPUT_DIR / "x.py").read())',
            'runpy.run_path(str(OUTPUT_DIR / "x.py"))',
            'Popen(["bash", str(OUTPUT_DIR / "run.sh")])',
            'os.system(f"python {OUTPUT_DIR}/x.py")',
            'eval((OUTPUT_DIR / "expr.txt").read_text())',
        ],
    )
    def test_the_execution_detector_sees_each_planted_shape(self, source):
        """A guard whose detector matches nothing would pass the roster test vacuously."""
        assert scoring._calls_executing_from_output(source) == [1]

    @pytest.mark.parametrize(
        "source",
        [
            "sys.path.insert(0, str(Path(__file__).parent))",  # the 11 helper importers
            'subprocess.run(["bash", str(solve_sh)], check=True, cwd=task_root, env=env)',
            'df = pd.read_csv(OUTPUT_DIR / "a.csv")',
            'x = open("/app/output/a.txt").read()',
            'json.loads((OUTPUT_DIR / "a.json").read_text())',
            "for p in OUTPUT_DIR.rglob('*.csv'):\n    pass",
        ],
    )
    def test_the_execution_detector_leaves_reading_shapes_alone(self, source):
        assert scoring._calls_executing_from_output(source) == []

    def test_an_unparseable_checks_file_is_a_roster_defect_not_a_pass(self):
        with pytest.raises(SyntaxError):
            scoring._calls_executing_from_output("def broken(:\n    pass\n")


class TestThePlatformTopology:
    """The CodaBench case, which review round 1 showed the first version of the fix aborted on.

    The vendored compute worker binds the scoring program's own output directory at
    `/app/output` for every scoring container (`compute_worker.py`, `volumes_config` ->
    `{"bind": "/app/output"}`), so on the platform the first presentable path ALREADY EXISTS,
    as an empty directory, when the scorer starts; `score.py` writes nothing into it until the
    unit loop is over. "Exists -> refuse" therefore raised `OrganizerFault` on the first
    hardcoded unit and the whole evaluation exited 3 with no `scores.json` -- worse than the
    defect being fixed. The reviewer reproduced it through the hub's real `score.py`; the last
    test here re-runs that reproduction when a hub checkout is available.

    `app_output` below is created EMPTY before the scorer runs, exactly what the bind provides.
    """

    @pytest.fixture
    def app_output(self, tmp_path: pathlib.Path, monkeypatch) -> pathlib.Path:
        app = tmp_path / "app" / "output"
        app.mkdir(parents=True)
        (app.parent / "program.py").write_text("", encoding="utf-8")  # /app is the workdir
        monkeypatch.setattr(
            scoring, "_PRESENTABLE_OUTPUT_PATHS", (str(app), str(tmp_path / "output"))
        )
        return app

    @staticmethod
    def _hardcode(unit: pathlib.Path, path: pathlib.Path, body: str | None = None) -> None:
        TestChecksThatHardcodeTheOutputPath._hardcode(unit, path, body=body)

    @staticmethod
    def _found_empty(app_output: pathlib.Path) -> None:
        assert app_output.is_dir() and not app_output.is_symlink(), "the bind mount is gone"
        assert list(app_output.iterdir()) == [], "the scoring output root was left populated"
        assert (app_output.parent / "program.py").exists(), "/app itself was touched"

    def test_a_pre_existing_empty_output_root_is_populated_then_emptied(
        self, unit, tmp_path, app_output
    ):
        self._hardcode(unit, app_output)
        r = _verdict(unit, _out(tmp_path, deliverable="42", reward=None))
        assert r.passed, r.detail
        assert r.detail["output_presented_at"] == [str(app_output)]
        self._found_empty(app_output)

    def test_a_wrong_submission_on_the_platform_gets_the_checks_own_failure(
        self, unit, tmp_path, app_output
    ):
        self._hardcode(unit, app_output)
        r = _verdict(unit, _out(tmp_path, deliverable="wrong", reward=None))
        assert not r.passed
        assert r.detail["trusted_checks"] == "ran"
        assert r.detail["pytest_returncode"] == 1
        self._found_empty(app_output)

    def test_a_second_unit_in_the_same_process_sees_only_its_own_output(
        self, tmp_path, app_output
    ):
        """`score.py` scores every unit of a submission in one process, one after another."""
        for name, answer in (("a", "A"), ("b", "B")):
            u = tmp_path / f"unit-{name}"
            (u / "checks").mkdir(parents=True)
            (u / "checks" / "test_outputs.py").write_text(
                f"import pathlib\nOUTPUT_DIR = pathlib.Path({str(app_output)!r})\n"
                "def test_only_mine():\n"
                "    assert sorted(p.name for p in OUTPUT_DIR.iterdir()) == ['answer.txt']\n"
                f"    assert (OUTPUT_DIR / 'answer.txt').read_text() == {answer!r}\n",
                encoding="utf-8",
            )
            o = tmp_path / "res" / name
            o.mkdir(parents=True)
            (o / "answer.txt").write_text(answer, encoding="utf-8")
            assert _verdict(u, o).passed, name
            self._found_empty(app_output)

    def test_subdirectories_are_presented_and_rglob_sees_them(self, unit, tmp_path, app_output):
        """One public unit rglobs its output; per-entry symlinks would have hidden nested
        files from `Path.rglob` and `os.walk`. A copy does not."""
        self._hardcode(
            unit,
            app_output,
            body="def test_nested():\n"
            "    assert sorted(p.name for p in OUTPUT_DIR.rglob('*.txt')) "
            "== ['answer.txt', 'deep.txt']\n",
        )
        out = _out(tmp_path, deliverable="42", reward=None)
        (out / "sub" / "dir").mkdir(parents=True)
        (out / "sub" / "dir" / "deep.txt").write_text("deep", encoding="utf-8")
        r = _verdict(unit, out)
        assert r.passed, r.detail
        self._found_empty(app_output)

    def test_what_the_checks_write_next_to_the_output_does_not_outlive_them(
        self, unit, tmp_path, app_output
    ):
        """The worker refuses an output root that already holds a `metadata` file, and
        `scores.json` is written there after the loop: the root must be empty again."""
        self._hardcode(
            unit,
            app_output,
            body="def test_writes():\n"
            "    (OUTPUT_DIR / 'metadata').write_text('stray')\n"
            "    (OUTPUT_DIR / 'answer.txt').write_text('edited in place')\n",
        )
        out = _out(tmp_path, deliverable="42", reward=None)
        assert _verdict(unit, out).passed
        self._found_empty(app_output)
        # A copy, not a link: the checks' writes never reach the submission's tree.
        assert (out / "answer.txt").read_text() == "42"
        assert not (out / "metadata").exists()

    def test_a_populated_output_root_is_still_an_organizer_fault_and_untouched(
        self, unit, tmp_path, app_output
    ):
        """Empty is what the platform provides; content there is something else's."""
        (app_output / "someone-elses-file").write_text("keep me", encoding="utf-8")
        self._hardcode(unit, app_output)
        with pytest.raises(OrganizerFault):
            _verdict(unit, _out(tmp_path, deliverable="42", reward=None))
        assert (app_output / "someone-elses-file").read_text() == "keep me"
        assert sorted(p.name for p in app_output.iterdir()) == ["someone-elses-file"]

    def test_a_check_that_removes_the_root_is_its_own_failure_and_the_root_is_restored(
        self, unit, tmp_path, app_output
    ):
        """Off the platform the directory can be removed (a bind mount cannot); the checks fail
        on their own `rmtree` verdict, and the scorer puts back what it was given."""
        self._hardcode(
            unit,
            app_output,
            body="import shutil\ndef test_rm():\n    shutil.rmtree(OUTPUT_DIR)\n    assert False\n",
        )
        r = _verdict(unit, _out(tmp_path, deliverable="42", reward=None))
        assert not r.passed and r.detail["trusted_checks"] == "ran"
        self._found_empty(app_output)

    def test_a_root_replaced_by_a_symlink_is_an_organizer_fault_left_in_place(
        self, unit, tmp_path, app_output
    ):
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        self._hardcode(
            unit,
            app_output,
            body="import os, shutil\ndef test_swap():\n"
            "    shutil.rmtree(OUTPUT_DIR)\n"
            f"    os.symlink({str(elsewhere)!r}, str(OUTPUT_DIR))\n",
        )
        with pytest.raises(OrganizerFault, match="replaced"):
            _verdict(unit, _out(tmp_path, deliverable="42", reward=None))
        assert app_output.is_symlink() and os.readlink(app_output) == str(elsewhere)

    @pytest.mark.parametrize("pre_existing", [True, False])
    def test_an_output_tree_that_cannot_be_copied_stays_with_the_submission(
        self, unit, tmp_path, app_output, pre_existing
    ):
        """A FIFO in the output would block a copy forever. The tree is the submission's, so
        this is a non-"ran" verdict against it, never an organizer fault, and nothing is
        presented or touched -- in either topology."""
        if not pre_existing:
            app_output.rmdir()
        self._hardcode(unit, app_output)
        out = _out(tmp_path, deliverable="42", reward=None)
        os.mkfifo(out / "pipe")
        r = _verdict(unit, out)
        assert not r.passed
        assert r.detail["trusted_checks"] == "unpresentable_output"
        assert "pipe" in r.detail["reason"]
        assert r.detail["output_presented_at"] == []
        if pre_existing:
            self._found_empty(app_output)
        else:
            assert not os.path.lexists(app_output)

    def test_env_aware_checks_never_touch_the_output_root(self, unit, tmp_path, app_output):
        """The 39 env-aware units: the pre-existing root is not even looked at."""
        r = _verdict(unit, _out(tmp_path, deliverable="42", reward=None))
        assert r.passed and r.detail["output_presented_at"] == []
        self._found_empty(app_output)

    @pytest.mark.skipif(os.geteuid() == 0, reason="root can write into a 0500 directory")
    def test_a_failed_copy_is_an_organizer_fault_that_names_no_source_path(
        self, unit, tmp_path, app_output
    ):
        """Review round 2: the copy-failure message used to embed `str(exc)`, and
        `shutil.Error` lists every failed entry by SOURCE path -- the run's output directory,
        `res/<unit>`, whose last component is the unit's handle. Reproduced the way the
        platform could produce it: the pre-existing empty output root is not writable."""
        handle = "t1-sealed-unit-handle"
        out = tmp_path / "res" / handle
        out.mkdir(parents=True)
        (out / "answer.txt").write_text("42", encoding="utf-8")
        self._hardcode(unit, app_output)
        app_output.chmod(0o500)
        try:
            with pytest.raises(OrganizerFault, match="could not copy") as caught:
                _verdict(unit, out)
        finally:
            app_output.chmod(0o755)
        message = str(caught.value)
        assert str(out) not in message and handle not in message
        assert str(app_output) in message, "the target path is the useful part; keep it"
        assert "1 of the output's entries" in message, message
        # Control: the exception the message was built from DOES carry the handle.
        assert handle in str(caught.value.__cause__)
        self._found_empty(app_output)

    def test_the_copy_failure_summary_carries_no_path(self):
        """The helper behind that message, over both shapes `copytree` raises: the collected
        `shutil.Error` becomes a count, a bare `OSError` keeps errno and strerror only."""
        src, dst = "/res/t1-sealed-unit-handle/answer.txt", "/app/output/answer.txt"
        collected = shutil.Error([(src, dst, f"[Errno 13] Permission denied: '{dst}'")] * 2)
        summary = scoring._copy_failure_summary(collected)
        assert "2 of the output's entries" in summary
        assert "t1-sealed" not in summary and dst not in summary
        bare = scoring._copy_failure_summary(OSError(28, "No space left on device", src))
        assert bare == "OSError: [Errno 28] No space left on device"
        assert scoring._copy_failure_summary(OSError("no errno at all")) == "OSError"

    @pytest.mark.skipif(os.geteuid() == 0, reason="root can empty a 0500 directory")
    @pytest.mark.parametrize("origin", ["output_tree", "left_by_the_checks"])
    def test_a_read_only_subdirectory_does_not_stop_the_restoration(
        self, unit, tmp_path, app_output, origin
    ):
        """Review round 2: `copytree` copies modes, so a `0500` directory in the submission's
        output arrives as one in the presentation, and a check may leave one. A file inside it
        could not be unlinked, the restoration reported a fault, the root stayed populated,
        and the NEXT hardcoded unit would have been an organizer fault too. The submission's
        own tree, including its mode, is untouched either way."""
        out = _out(tmp_path, deliverable="42", reward=None)
        body = None
        if origin == "output_tree":
            (out / "locked").mkdir()
            (out / "locked" / "inner.txt").write_text("x", encoding="utf-8")
            (out / "locked").chmod(0o500)
        else:
            body = (
                "import os\n"
                "def test_leaves_a_locked_dir():\n"
                "    sub = OUTPUT_DIR / 'locked'\n"
                "    sub.mkdir()\n"
                "    (sub / 'inner.txt').write_text('x')\n"
                "    os.chmod(sub, 0o500)\n"
            )
        self._hardcode(unit, app_output, body=body)
        try:
            r = _verdict(unit, out)
            assert r.passed, r.detail
            self._found_empty(app_output)
            if origin == "output_tree":
                assert stat.S_IMODE(os.stat(out / "locked").st_mode) == 0o500
                assert (out / "locked" / "inner.txt").read_text() == "x"
        finally:
            if origin == "output_tree":
                (out / "locked").chmod(0o700)

    def test_through_the_hubs_real_score_py(self, tmp_path):
        """Review round 1's reproduction, kept runnable: the hub's `score.py` over a signed
        C1/C2 case, one hardcoded unit, the platform topology (the presentable path IS the
        scorer's pre-existing output root). Opt-in: needs a hub checkout, which CI does not
        have -- set AGENTHON_HUB_CHECKOUT to its `common/` directory. Set and unusable is a
        failure, not a skip."""
        raw = os.environ.get("AGENTHON_HUB_CHECKOUT")
        if not raw:
            pytest.skip("set AGENTHON_HUB_CHECKOUT=<hub>/common to run the hub end-to-end case")
        hub = pathlib.Path(raw)
        score_py = hub / "codabench" / "scoring_program" / "score.py"
        builders = hub / "tests" / "test_fixed_denominator.py"
        assert score_py.is_file() and builders.is_file(), f"not a hub common/ checkout: {hub}"
        import subprocess
        import sys

        pkg_root = pathlib.Path(scoring.__file__).resolve().parent.parent
        for answer, expect in (("42", (1.0, 1, 0)), ("wrong", (0.0, 0, 1))):
            work = tmp_path / answer
            driver = work / "driver.py"
            work.mkdir()
            driver.write_text(
                textwrap.dedent(
                    f"""
                    import json, os, pathlib, runpy, sys
                    os.environ["QFBENCH_TRACK"] = "coding"
                    sys.path.insert(0, {str(hub / "tests")!r})
                    import test_fixed_denominator as tfd
                    import qfbench2_track_coding.scoring as s
                    work = pathlib.Path({str(work)!r})
                    plan = tfd.make_plan(["uh-hard"], track="coding")
                    inp, outp = tfd.write_case(work, plan)
                    outp.mkdir(parents=True, exist_ok=True)   # the bind: exists, empty
                    unit = inp / "ref" / "uh-hard"
                    (unit / "checks").mkdir()
                    (unit / "card.toml").write_text(
                        'schema_version = "2.0"\\n[task]\\nsplit = "public-dev"\\n')
                    (unit / "manifest.json").write_text(
                        json.dumps({{"manifest_version": "2.0", "files": []}}))
                    (unit / "checks" / "test_outputs.py").write_text(
                        "import pathlib\\nOUTPUT_DIR = pathlib.Path(" + repr(str(outp)) + ")\\n"
                        "def test_deliverable():\\n"
                        "    assert (OUTPUT_DIR / 'answer.txt').read_text().strip() == '42'\\n")
                    (inp / "res" / "uh-hard" / "answer.txt").write_text({answer!r} + "\\n")
                    s._PRESENTABLE_OUTPUT_PATHS = (str(outp),)
                    sys.argv = [{str(score_py)!r}, str(inp), str(outp)]
                    runpy.run_path({str(score_py)!r}, run_name="__main__")
                    """
                ),
                encoding="utf-8",
            )
            proc = subprocess.run(
                [sys.executable, str(driver)],
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONPATH": str(pkg_root), "PYTHONDONTWRITEBYTECODE": "1"},
                check=False,
            )
            assert proc.returncode == 0, proc.stderr[-2000:]
            outp = work / "output"
            scores = json.loads((outp / "scores.json").read_text())
            primary, n_scored, n_fail = expect
            assert scores["primary"] == primary, scores
            assert scores["n_scored"] == n_scored and scores["n_participant_failure"] == n_fail
            assert scores["n_organizer_failure"] == 0
            # `failure_map.jsonl` is written only when a unit failed; nothing else may be there.
            left = {p.name for p in outp.iterdir()}
            assert {"details.jsonl", "scores.json"} <= left
            assert left <= {"details.jsonl", "failure_map.jsonl", "scores.json"}, (
                "the scorer left something in the scoring output root"
            )


class TestOurOwnBrokenEnvironmentIsNotChargedToTheSubmission:
    """Failing closed is right only while the fault could be the submission's.

    `_run_trusted_checks` shells out to ``{sys.executable} -m pytest``. Measured 2026-08-29 in a
    clean venv holding exactly this package's then-declared dependencies (`qfbench2-common` and
    nothing else, so no pytest), against unit `t1-option-put-call-parity-forward-audit` and a
    submission whose four deliverables pass that unit's own checks: `python -m pytest` exited
    **1** with "No module named pytest" -- pytest's own "tests failed" code -- and g3 returned
    ``passed=False``, ``trusted_checks="ran"``, ``T1_WRONG_NUMERIC``. Every Track 1 submission
    would have been scored zero and told its answer was wrong. `pyproject.toml` now declares the
    runner; these tests are what keeps an environment that cannot judge from judging anyway.
    """

    def _shim(self, tmp_path: pathlib.Path, script: str) -> str:
        shim = tmp_path / "fake-interpreter"
        shim.write_text(script, encoding="utf-8")
        shim.chmod(0o755)
        return str(shim)

    def test_no_importable_pytest_is_an_organizer_fault_not_a_wrong_answer(
        self, unit, tmp_path, monkeypatch
    ):
        """An interpreter that runs but cannot import pytest scores nobody."""
        monkeypatch.setattr(
            scoring.sys, "executable", self._shim(tmp_path, "#!/bin/sh\nexit 1\n")
        )
        with pytest.raises(OrganizerFault):
            _verdict(unit, _out(tmp_path, deliverable="42", reward=1.0))

    def test_an_interpreter_that_cannot_be_launched_is_an_organizer_fault(
        self, unit, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(scoring.sys, "executable", str(tmp_path / "no-such-interpreter"))
        with pytest.raises(OrganizerFault):
            _verdict(unit, _out(tmp_path, deliverable="42", reward=1.0))

    def test_a_pytest_usage_error_is_an_organizer_fault(self, unit, tmp_path):
        """Exit 4 means pytest rejected OUR argv and never looked at the submission.

        Planted here the way it happens in the field: an ini file in the unit directory --
        which is the scorer's cwd -- carrying an option this pytest does not have.
        """
        (unit / "pytest.ini").write_text(
            "[pytest]\naddopts = --this-flag-does-not-exist\n", encoding="utf-8"
        )
        with pytest.raises(OrganizerFault):
            _verdict(unit, _out(tmp_path, deliverable="42", reward=1.0))

    def test_the_same_unit_without_the_planted_ini_still_scores_normally(self, unit, tmp_path):
        """The negative control: none of the above fires on a healthy environment."""
        assert _verdict(unit, _out(tmp_path, deliverable="42", reward=1.0)).passed
        assert not _verdict(unit, _out(tmp_path, deliverable="wrong", reward=1.0)).passed


class TestRewardJsonIsOptional:
    """The file g1 demanded is produced by the grader g3 runs; no participant can write it.

    Measured 2026-09-02 on the public scorer: `_g1_schema` returned SCHEMA_INVALID_OUTPUT for
    every output directory without `reward.json`, and `checks/` -- where `test.sh` writes it --
    is in the hub's STRIP_DIRS for coding. So a correct deliverable with no claim was refused at
    g1 on every real unit, indistinguishably from a wrong one.
    """

    def test_a_correct_deliverable_with_no_claim_is_admitted(self, unit, tmp_path):
        r = _verdict(unit, _out(tmp_path, deliverable="42", reward=None))
        assert r.passed, r.detail
        assert r.detail["trusted_checks"] == "ran"
        assert r.detail.get("claimed_reward") is None

    def test_a_wrong_deliverable_with_no_claim_is_still_refused(self, unit, tmp_path):
        assert not _verdict(unit, _out(tmp_path, deliverable="wrong", reward=None)).passed

    def test_g1_admits_deliverables_without_a_claim_and_refuses_an_empty_output(self, tmp_path):
        out = _out(tmp_path, deliverable="42", reward=None)
        g1 = scoring._g1_schema({"output_dir": str(out)})
        assert g1.passed, g1.detail
        assert g1.detail["deliverables"] == ["answer.txt"]
        empty = tmp_path / "empty"
        empty.mkdir()
        assert not scoring._g1_schema({"output_dir": str(empty)}).passed
        assert not scoring._g1_schema({"output_dir": str(tmp_path / "absent")}).passed

    def test_g1_still_refuses_a_malformed_or_out_of_range_claim(self, tmp_path):
        assert not scoring._g1_schema({"output_dir": str(_out(tmp_path, deliverable="42", reward="NOT-JSON"))}).passed
        assert not scoring._g1_schema({"output_dir": str(_out(tmp_path, deliverable="42", reward=0.5))}).passed
        assert scoring._g1_schema({"output_dir": str(_out(tmp_path, deliverable="42", reward=1.0))}).passed

    def test_a_claim_alone_is_not_a_deliverable(self, tmp_path):
        """`reward.json` and `pytest_report.json` are the grader's artifacts; an output that holds
        nothing else wrote nothing the checks could examine."""
        assert not scoring._g1_schema({"output_dir": str(_out(tmp_path, deliverable=None, reward=1.0))}).passed
