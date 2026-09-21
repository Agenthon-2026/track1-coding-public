## Executive summary (read this first)

The organizer can build a Track 1 dataset from all public units or an explicit ordered list.
The builder creates separate participant and grader trees. It removes `checks/` and
`reference/` from participant inputs, checks for renamed copies of answer files, and keeps
the complete answers in the grader tree. A failed build keeps the previous output intact.

### Select the units

For example, a roster file can contain:

```text
# One immediate unit directory handle per line.
t1-example-a
t1-example-b
```

Use handles that actually exist under the selected units directory:

```bash
python scripts/build_dev_dataset.py \
  --units /absolute/real/path/units \
  --out /absolute/real/path/t1-development \
  --roster /absolute/real/path/roster.txt
```

Blank lines and full-line comments are ignored. Duplicate handles, missing units, absolute
paths, traversal, nested paths, links and special filesystem nodes are refused. Every
selected unit must contain a regular `card.toml` and use the known Track 1 layout.
Unselected units are not included or inspected recursively. Omitting `--roster` preserves
the existing selection: all immediate unit directories, sorted by name.

The builder writes `build-roster.json` with the selected directory handles in build order.
This records the local build selection. It is not a signed evaluation plan and does not
change which units a deployed phase scores. A proposed reduced roster belongs in separate
organizer review material until its adoption is approved.

### Keep answers separate

The command prints these two upload roots:

| CodaBench slot | Local directory | Contents |
|---|---|---|
| `input_data` | `<out>/ingestion/input` | Contains `ref/`; participant task inputs only |
| `reference_data` | `<out>/scoring/input/ref` | Unit directories with the full grader material |

The shared toolkit owns the safe split. Track 1 additionally enforces both answer directory
names and a content check, including when used with older shared toolkit declarations.
The builder refuses an output with no answer files across the selected set. It also
checks that every answer path and its bytes are preserved in the grader copy. Distinct
answer files with identical bytes still count separately.

### Preserve the previous artifact

Preflight inspects selected source trees and any previous output before copying. Input
and output paths must not overlap. The builder prepares both trees in a sibling temporary
directory, keeping unrelated existing output metadata. It promotes the completed directory
only after every unit passes the leak and grader-copy checks. An ordinary promotion failure
restores the prior directory. Refused candidates are removed.

Use real paths, without symlinked ancestors. For example, on macOS `/tmp` is normally a link;
choose a real workspace directory or its resolved path. Keep source and output trees idle
while a build runs. The builder does not coordinate concurrent writers.

Directory replacement uses two renames. A power loss or forced process kill between them
can leave the prior artifact in a sibling named `.<out-name>.previous-<id>`. An exceptional
restore failure reports that backup path. Preserve it for recovery; do not upload an
incomplete output. A cleanup warning after successful promotion also names any backup
that remains for operator cleanup.

Existing evaluation plans and trust metadata are retained, but this command does not
create, validate or re-sign them. Before publication, the organizer must bind the approved
roster and dataset to a matching signed plan and verify the completed phase package.
Building a local candidate neither publishes a dataset nor authorizes its use.
