"""The g2 contamination gate must actually run, and must catch a canary anywhere.

Two defects motivated these tests, and each one is pinned by a case below.

The gate used to call `scan_canary`, withdrawn under frozen ruling R-8 and kept as a raising stub.
It sat behind `if registry:`, and the only caller that populates a registry is the private final
scorer -- which could not start. So the gate read as protection in two repositories while being
incapable of running in either.

It also read only files whose suffix was in a six-entry allowlist. A contaminated agent that wrote
its memory to any other name was never scanned.
"""

from __future__ import annotations

import pathlib

import pytest

from qfbench2_common.failure_labels import FailureLabel
from qfbench2_track_coding.scoring import _g2_cutoff_resource

CANARY = "07dcd8ac-19c0-4ec5-a969-b84ea4d283b9"


def ctx_for(out: pathlib.Path, registry=frozenset({CANARY})):
    return {
        "output_dir": str(out),
        "canary_registry": set(registry),
        "elapsed_sec": 1.0,
        "agent_timeout_sec": 1800.0,
    }


class TestTheGateActuallyRuns:
    def test_a_clean_tree_passes(self, tmp_path):
        (tmp_path / "result.json").write_text('{"ok": true}')
        assert _g2_cutoff_resource(ctx_for(tmp_path)).passed is True

    def test_a_canary_in_an_ordinary_file_is_caught(self, tmp_path):
        (tmp_path / "notes.txt").write_text(f"leaked {CANARY} here")
        r = _g2_cutoff_resource(ctx_for(tmp_path))
        assert r.passed is False
        assert r.label is FailureLabel.CONTAMINATION_CANARY

    def test_the_gate_does_not_raise_when_a_registry_is_supplied(self, tmp_path):
        """The whole point. With a registry present the old gate raised NotImplementedError."""
        (tmp_path / "a.json").write_text("{}")
        _g2_cutoff_resource(ctx_for(tmp_path))  # must not raise


class TestTheExtensionHoleIsClosed:
    @pytest.mark.parametrize("name", ["memory.bin", "notes", "state.pkl", "deep/nested/x.dat"])
    def test_a_canary_outside_the_old_allowlist_is_caught(self, tmp_path, name):
        f = tmp_path / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(f"agent memory {CANARY}".encode())
        r = _g2_cutoff_resource(ctx_for(tmp_path))
        assert r.passed is False, (
            f"{name} was invisible to the old six-extension allowlist; the file a contaminated "
            "agent writes its memory into is not called .json"
        )


class TestItNeverHandsBackTheCanary:
    def test_the_detail_carries_counts_not_guids(self, tmp_path):
        (tmp_path / "out.txt").write_text(CANARY)
        r = _g2_cutoff_resource(ctx_for(tmp_path))
        blob = repr(r.detail)
        assert CANARY not in blob, (
            "returning the matched GUID hands a contaminated submitter the exact string to strip "
            "next time, and the registry is private material besides"
        )
        assert "canary_hit_count" in r.detail


class TestAnEmptyRegistrySkips:
    def test_no_registry_means_no_scan(self, tmp_path):
        (tmp_path / "out.txt").write_text(CANARY)
        assert _g2_cutoff_resource(ctx_for(tmp_path, registry=frozenset())).passed is True
