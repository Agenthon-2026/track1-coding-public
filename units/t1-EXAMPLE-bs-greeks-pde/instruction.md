# Task: Black-Scholes Greeks via Finite-Difference PDE Solver

## Background

The Black-Scholes partial differential equation (PDE) governs the fair price of
a European option on a non-dividend-paying stock.  Rather than using closed-form
formulae, this task requires you to solve the PDE numerically on a finite-difference
grid and then compute option sensitivities (Greeks) from the numerical solution.
The checker will verify structural properties of the output — not a specific numerical
method — so you may use any PDE discretisation (explicit, implicit, Crank-Nicolson)
or any equivalent method you prefer.

## Inputs

All files are mounted read-only under `/input`.

| Path | Format | Description |
|---|---|---|
| `/input/environment/data/options.parquet` | Parquet | Option parameter table; schema below |

**`options.parquet` schema:**

| Column | Type | Unit / Convention |
|---|---|---|
| `option_id` | `str` | Unique row identifier |
| `S` | `float64` | Current spot price (USD) |
| `K` | `float64` | Strike price (USD) |
| `T` | `float64` | Time to expiration (years; > 0) |
| `r` | `float64` | Continuously compounded risk-free rate (decimal, e.g. 0.05 = 5 %) |
| `sigma` | `float64` | Implied volatility (decimal, e.g. 0.20 = 20 %) |
| `option_type` | `str` | `"call"` or `"put"` |

The table contains both calls and puts.  For each `option_id` there is exactly one row.

## Task

For each row in `options.parquet`, compute the following quantities:

1. **price** — the fair value of the European option (USD).
2. **delta** — sensitivity of price to spot price (`∂V/∂S`), dimensionless.
3. **gamma** — second-order sensitivity to spot (`∂²V/∂S²`), per USD.
4. **vega** — sensitivity to implied volatility (`∂V/∂σ`), in USD per unit of σ
   (i.e., per 1.0 move in σ in decimal terms — so a 1 pp move in vol = 0.01 × vega).
5. **theta** — sensitivity to time decay (`∂V/∂t`), in USD per calendar day
   (negative for long positions; use convention ∂V/∂t not −∂V/∂T).

You may use any numerical method.  Your implementation must be consistent:
the Greeks should match the first and second differences of `price` with respect
to the corresponding input parameter at the precision described in the Deliverables.

## Deliverables

### `/output/results.parquet`

A Parquet file with one row per input option, preserving `option_id` order.

| Column | Type | Unit / Convention |
|---|---|---|
| `option_id` | `str` | Matches input `option_id` |
| `price` | `float64` | USD, ≥ 0 |
| `delta` | `float64` | Dimensionless; ∈ (0, 1) for calls, ∈ (−1, 0) for puts |
| `gamma` | `float64` | Per USD; > 0 for both calls and puts |
| `vega` | `float64` | USD per unit of σ; > 0 for both calls and puts |
| `theta` | `float64` | USD per calendar day; typically < 0 for long positions |

### `/output/reward.json`

Written automatically by `checks/test.sh` — **do not write this file**.

## Constraints

- **Restricted network.** No open internet — calls to the organizer-hosted model endpoint (`$MODEL_ENDPOINT`) only, through the organizer's audited proxy. Vendor model APIs are refused by the proxy and no API keys are injected. No data fetching: all data you need is under `/input`.
- **Runtime.** Complete within 1800 seconds.
- **Resources.** 16 vCPUs, 128 GB RAM, GPU available.
- **Language.** Python 3.13.  Available packages: `numpy`, `pandas`, `scipy`,
  `pyarrow`, `numba`.  See `environment/Dockerfile` for the full list.

## Notes

- Rates and volatilities are in decimal form (0.05 = 5 %, not 5).
- Time `T` is in years.  To convert theta to a per-day figure, divide by 365.
- The input table contains a mix of in-the-money, at-the-money, and out-of-the-money
  options across a range of maturities from 1 week to 2 years.
- Numerical edge cases: very short maturities (< 5 days) and very deep ITM/OTM
  options are included; your solver should handle these gracefully.
