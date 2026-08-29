# Task: <One-line title matching card.toml [task].title>

<!-- =========================================================
AUTHORING NOTES (delete this block before publishing)

RULE 1 — Output contract: state exactly which files the agent must
         write, their format, column names, and units.
RULE 2 — No skill leakage: describe WHAT to compute, not HOW.
         Wrong: "Apply Black-Scholes with these Greeks formulas."
         Right: "Compute the option price and Greeks."
RULE 3 — No answer leakage: do not embed numerical reference
         values or tolerance thresholds.
RULE 4 — Data references only: refer to input files by their
         manifest paths under /input; do not inline raw data.
======================================================== -->

## Background

<!-- 2-4 sentences: financial context and motivation.
     Example: "The Black-Scholes model prices European options under the
     assumption of constant volatility. Given a set of option parameters,
     you will compute the fair price and first-order Greeks." -->

<background>

## Inputs

All input files are mounted read-only under `/input`.

| Path | Format | Description |
|---|---|---|
| `/input/environment/data/<filename>` | `<parquet\|csv\|json>` | `<description>` |

<!-- List EVERY file from manifest.json that the agent will use.
     Include column names, units, and any conventions (e.g., rates in decimal, not %).
     Example column description: "strike: float, option strike price in USD" -->

## Task

<!-- State the computation in plain English. One paragraph or a numbered list.
     Name the financial quantity to compute. Do NOT state the method.

     Example:
     "For each row in the input table, compute:
     1. The fair price of a European call option.
     2. Delta: the first derivative of price with respect to spot.
     3. Vega: the first derivative of price with respect to implied volatility.
     Express all monetary values in USD. Express Greeks in their standard
     per-unit convention (see Deliverables)." -->

<task-description>

## Deliverables

Write all output files under `/output`. The verifier will read exactly these paths.

### `/output/results.<format>`

<!-- Specify the exact schema. Example:
| Column | Type | Unit / Convention |
|---|---|---|
| `option_id` | `str` | matches `option_id` column in the input |
| `price` | `float64` | USD, mid-market clean price |
| `delta` | `float64` | dimensionless, ∈ (0, 1) for calls |
| `vega` | `float64` | USD per 1 pp move in implied vol (i.e., per 0.01) |
-->

| Column | Type | Unit / Convention |
|---|---|---|
| `<col>` | `<type>` | `<unit>` |

### `/output/reward.json`

Written automatically by `checks/test.sh` — **do not write this file yourself**.

## Constraints

- **Restricted network.** No open internet — calls to the organizer-hosted model endpoint (`$MODEL_ENDPOINT`) only, through the organizer's audited proxy. Vendor model APIs are refused by the proxy and no API keys are injected. No data fetching: all data you need is under `/input`.
- **Runtime.** Your solution must complete within 1800 seconds of wall-clock time.
- **Resources.** 16 vCPUs, 128 GB RAM. GPU available.
- **Language.** Python 3.13 is available. See `environment/Dockerfile` for the
  exact package list.

## Notes

<!-- Optional: clarify conventions, edge cases, or data quality issues
     WITHOUT giving away the solution.

     Example: "Rates are given as continuously compounded annualised rates in decimal
     form (e.g. 0.05 for 5%). Option maturities are in years." -->

<notes>
