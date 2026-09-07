# Validation record — 2026-09-07

**Model capability score: not measured.** No `MODEL_ENDPOINT` or `MODEL_NAME` was
configured. The evaluator refused to start inference. No pass@1/pass@3 number is
claimed, and no competition submission descriptor was fabricated.

Completed checks:

- Full repository tests: **46 passed**, with five existing pytest return-value warnings.
- Baseline tests: **13 passed** in an offline, read-only Python 3.13 container.
- Ruff lint/format for the baseline and scorer; strict mypy for the scorer: passed.
- All **87 public units** passed card/schema, manifest, canary-uniqueness and
  public-safety validation. The held-out roster firewall and contract scripts passed.
- Built the sealed local dataset with both input and grader trees; verified all
  original and staged manifests and matched their retained input bytes. The frozen
  roster hashes instructions, data, metadata and grader files.
- Built `finance-bench-sandbox:latest`, `track1-iterative:latest` and
  `track1-grader:latest`; the agent runs Python **3.13.15**, advertises interface
  **2.0**, and accepts `solve --task-dir ... --out ...`.
- Actual agent-container missing-model check: exits with a clear configuration
  error and writes no claimed reward.
- Actual offline grader-container negative control on the public exemplar:
  deliberately wrong deliverables passed g0/g1/g2, the trusted pytest checks
  executed and rejected them at g3, and grader-generated JSON artifacts appeared.
  This tests the scoring chain; it is **not an agent performance measurement**.
- A temporary, explicitly synthetic packaging fixture passed the toolkit's C5
  descriptor/digest validation and was then deleted.

The negative control exposed a pre-existing scorer incompatibility with the
pinned shared toolkit: `scan_canary` is a withdrawn API that raises. The Track 1
call site now delegates to the toolkit's existing `scan_tree` and returns only
its verdict/counts. Three regression tests failed before this change and pass
after it: clean text, nested binary contamination, and an incomplete symlink scan.
There is no fork of the scanner or scoring math; the upstream toolkit already
contains the supported implementation.

Local image IDs (not a claim that these images have been published to a registry):

```text
agent:  sha256:f6e7b7a87f0745227bb1d7cfdb2cb349ccf3d1f88d776855ed8a4dc792f6a54d
grader: sha256:e82f8a5abfd44a5b59ae31f610eee1f5baa17e96299b61be79d2433275162000
base:   sha256:cbad49a04a5de60c958c861bc634db5a7a68fe9a99b4e1fc898a82ce348e3edd
```

The local dataset is `../track1-baseline-evaluation/dataset-v1/`, with logs in
`../track1-baseline-evaluation/logs/`. It has 87 tasks: 62 tuning and 25 public
validation, with a 34-task smoke subset covering every category string in the
actual cards. Smoke lies entirely in tuning. Public validation is not the private
leaderboard set.

Next measurement, once the organizer endpoint/model/proxy are configured:

```bash
.venv/bin/python scripts/evaluate_baseline.py run \
  --dataset ../track1-baseline-evaluation/dataset-v1 \
  --out ../track1-baseline-evaluation/model-run-1 \
  --image track1-iterative:latest --subset all --attempts 1
```

Competition submission additionally needs the target registry, team/competition
identifiers and actual model version, revision and training cutoff. A published
image's registry digest must be used by `scripts/package_baseline.py`.
