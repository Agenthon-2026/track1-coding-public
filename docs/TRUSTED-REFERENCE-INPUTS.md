## Executive summary (read this first)

The organizer must ship complete, valid reference inputs before Track 1 grades participant
output. For example, deleting `checks/reference_data/expected.json` must raise `OrganizerFault`,
even if the participant output is wrong or empty. It must never turn an empty set of expected
deliverables into a passing answer.

The packaged Track 1 verifier checks organizer references at `g0_integrity`, before output
gates. Direct trusted-checker calls perform the same preflight before pytest starts. A reference
fault aborts scoring; it does not enter the participant failure-label classifier. Missing files,
malformed JSON, or fixture exceptions caused by participant output retain their existing
participant-failure behavior.

Before validation, the scorer binds the reference tree and manifest using byte hashes and
file identities. It checks that same binding after validation and before releasing any
verdict, including on timeout or exception paths. The outer verifier keeps its binding across
all gates, including early output failures. Deleting a reference, replacing its contents, or
replacing both the reference and its manifest during grading aborts scoring. Revalidating a
replacement pair cannot establish trust in a different answer set halfway through a run.

### What a unit author must provide

Every file under `checks/reference_data/` must have an entry in the unit's existing checksum
manifest. These files are required in the organizer scoring tree, including references whose
redistribution flag is false. The shared manifest validator checks path safety, regular-file
identity, checksums, duplicate paths and complete reference-directory coverage. This adds no
new manifest schema fields. Keep prior input entries unchanged when adding reference coverage.

JSON reference files must be nonempty objects with no duplicate keys. CSV references must have
distinct, nonempty column names and consistent row widths; a header-only table is allowed.
The preflight preserves flat expected-value objects and the generic grader's existing numeric,
string, list and object values. It does not compute answers or change tolerance comparisons.

The shared generic grader, imported with `from verifier import run_verification`, additionally
requires valid `expected.json`, `checkpoints.json`, `concept_graph.json` and `bridges.json`.
Deliverable and checkpoint collections must be nonempty. Declared tolerances must contain
finite nonnegative `rtol` or `atol` values. An optional `alt_paths.json` must contain complete
alternative paths; once it is in the manifest, removing it is an organizer fault. A single-path
unit may omit that file. Graph and bridge metadata are validated for structure, without adding
new semantic graph requirements.

Direct graders that read the same structured reference formats declare them as a literal
mapping in their trusted `checks/test_outputs.py`:

```python
T1_REFERENCE_FORMATS = {
    "expected.json": "deliverables",
    "checkpoints.json": "checkpoints",
}
```

The supported format names are `deliverables` and `checkpoints`. The scorer reads this
declaration from Python syntax without importing the checker. Every declared file is required.
An unrelated participant key named `deliverables` does not select a reference schema.

Other reference contents are protected by their immutable manifest hashes; the preflight is
not a proof that an author computed correct targets. Authors must still execute known-good
outputs and meaningful bad-output controls. The standalone Harbor `test.sh` path is unchanged;
this preflight belongs to the packaged platform verifier.

### Release and validation

Publish the scorer and regenerated scoring-tree reference manifests as one coordinated
release. An older public scoring tree whose reference files are absent from its manifest will
be refused by this scorer. The mounted participant tree continues to strip `checks/` and its
manifest entries through the existing dataset splitter. This source change does not rebuild
or publish a live dataset.

CI runs `tests/test_checker_references.py` explicitly. It uses the real generic grader with
synthetic values to check good and wrong answers, missing/malformed/rehashed invalid reference
objects, alternative paths, manifest omissions, links, CSV corruption and participant fixture
errors. Actual pytest controls also change references between preflight and execution, between
gates, and during timeout/error paths. It validates the current public reference shapes without executing participant
code or exposing sealed reference data.
