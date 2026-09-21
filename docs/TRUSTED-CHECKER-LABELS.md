## Executive summary (read this first)

Track 1 derives correctness and diagnostic failure labels from the grader's own pytest run.
A participant-authored `pytest_report.json` cannot choose the label. Test function names in the
private JUnit report map to the existing closed label vocabulary; parameter IDs and assertion
text do not. A passing trusted check has no failure label even if the submission claims failure.
The diagnostic-only overlay still runs the trusted checks.

JUnit `<error>` alone does not prove an organizer fault. Grader fixtures often load participant
outputs, so missing or malformed outputs can cause setup errors. Existing fault attribution is
preserved: absent checks, an unavailable test runner, internal/usage errors and an all-skipped
or empty test run remain organizer faults. Distinguishing other broken grader fixtures from
participant-triggered errors needs additional trusted provenance; this change does not infer it
from the XML tag. Private reports and assertion text stay in the existing private diagnostics
channel; official public reporting retains its bounded projection.

Checker budgets are unchanged. Adopting the card's verifier timeout requires timing valid
controls across the intended roster and validating the release's metadata binding first.
