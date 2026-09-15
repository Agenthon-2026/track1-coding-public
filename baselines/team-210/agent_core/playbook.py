"""The field playbook: distilled failure experience, injected into every
model prompt.

Every entry here was EARNED - it names a failure class that actually
happened in a measured run (the sweeps, the benchmark post-mortems, the
stress suite) and states the generic rule that prevents it. Entries are
distilled hard: the playbook competes with the instruction for the model's
attention, so a lesson that cannot be said in two lines has not been
understood yet.

Two laws govern this file:
  1. GENERIC ONLY. A lesson may name a convention, an identity, a trap - it
     may never name a unit, a dataset value, or an expected answer. Anything
     unit-specific is memorisation wearing a helmet, and dies on hidden
     tasks while poisoning the leak gate.
  2. EARNED ONLY. New entries cite the failure ledger; entries that a
     measured A/B shows to be dead weight get removed. The playbook is a
     product of the measurement loop, not a textbook.

Injection is mandatory by construction: `select()` output is placed in the
prompt by code_writer, so the model cannot skip it - which is the point.
"""

from __future__ import annotations

#: Character budget for the whole playbook block. Raised as the universal
#: laws grew: at 10k the category blocks were being dropped (derivatives got
#: one of two). The official per-unit allowance is 1M input tokens, so the
#: constraint is attention, not quota - but prompt bloat is itself untested.
MAX_CHARS = 14000

UNIVERSAL = """\
- Read inputs with the EXACT absolute paths given; never resolve a data file
  relative to the working directory.
- If the instruction SHOWS an example output (JSON object, table), the
  example IS the contract: mirror its keys, nesting, wrapper and order.
- Deliverable filenames are exact; write them under the given output
  directory; create subdirectories when the path has them.
- After writing each file, read it back with the standard parser
  (json.load / pd.read_csv / pd.read_parquet) and crash on failure - an
  unreadable file can never be a correct answer.
- End with asserts that recompute every identity the task states (sums that
  reconcile, parities, monotone orders, repricing round-trips) at the STATED
  tolerance; a failing assert must crash the program.
- Conventions are graded literally: day counts, compounding, rounding rules,
  column order, dtypes, units (%, bps, decimal). Take them from the text,
  never from habit.
- A column named rank must be a complete 1..N ranking: integers, no gaps,
  no duplicates.
- JSON integers must be ints (not 3.0, not numpy types); use plain Python
  types when dumping.
- Vectorise with numpy/pandas; a per-row Python loop over a large frame will
  blow the time budget.
- Never copy instruction text, IDs or tokens into deliverables; outputs
  carry numbers and requested fields only.
- COMPLETENESS: enumerate EVERY output file and EVERY required field named
  anywhere in the instruction - intermediates, calibration files, per-step
  files, extra JSON fields - produce all of them, and assert their presence
  before exiting. Partial delivery of a multi-file contract scores zero.
- CARDINALITY: derive the expected number of rows/items from the inputs
  (one per entity x period x instrument as the task defines) and assert the
  exact count. "Roughly the right rows" is a graded failure.
- CONVENTION ANCHOR: when two conventions both seem plausible (simple vs
  compound, annual vs continuous, calendar vs business days), test BOTH
  against any worked number or example the instruction shows and keep the
  one that reproduces it. Never pick by habit when an anchor exists.
- CROSS-CHECK: for any priced or estimated headline quantity, compute it a
  SECOND, independent way (closed form vs simulation, matrix vs iterative,
  library vs manual) and assert agreement within the stated tolerance. A
  formula bug almost never survives two different derivations. When the
  task itself asks for two estimates of one quantity, a gap beyond the
  stated tolerance is a BUG in one of them - fix it, never report it.
- CITED METHOD: an estimator or test named by author/paper/section is the
  canonical published definition, not a lookalike that estimates the same
  thing; when the instruction paraphrases a cited formula and the
  paraphrase would contradict the paper, the paper wins. Print the formula
  you implemented next to the citation.
- STATED MECHANIC: a prescribed estimator (tau inversion, sqrt(h) scaling of
  the reported number, a seeded draw count, an adjusted quantity defined
  earlier such as a forward or discounted spot) is used VERBATIM downstream
  - never upgraded to a "better" method. Every key in a supplied config
  file is consumed (an estimation window means "only the last W rows").
- SILENT SPEC: when the text is silent, do not improvise. An undefined
  branch of a rule means "no action"; undefined output keys reuse the
  instruction's own category tokens; a quantity NAMED after a standard
  measure (duration, VaR, tail index xi, information ratio) takes that
  measure's standard sign, units and definition; a field whose name carries
  a unit suffix (_per_unit, _days, _periods, _bps, _pct) is in that unit
  even if a blanket sentence suggests otherwise. Record every such choice in
  the summary output.
- LITERAL TOKENS: keys, column names, enum strings, booleans (`true`, not
  True) and number formats (fixed 6 decimals) are copied byte-for-byte from
  the instruction. After writing, re-read each file as RAW TEXT and regex-
  check the literals - the in-memory value being right is not enough.
- SENTENCE CHECKLIST: before computing, list every sentence containing must
  / only / exactly / iff / before / after / in this order / positive /
  non-negative, AND every descriptive fact (settlements per day, "has upper
  tail dependence", "standard error from the Fisher information"), and
  write one assert per sentence against the produced output. Descriptive
  sentences are checks too.
- ORDERING FIDELITY: when the text fixes a direction or says which member
  of a tie survives, implement it against THAT ordering and hand-check two
  elements. A library keyword can invert what you meant: keep="last" on a
  reversed frame keeps the first, and a weight vector indexed by lag applied
  to a chronologically ascending window weights the OLDEST point most.
- SELECTION FIELDS: a field that names the chosen method/model/profile is
  decided by the selection rule the task states, never by insertion order.
  Every filter named in the key must also filter the rows the score is
  computed from, and a max/min over equal scores silently returns the first
  key - assert the candidate scores differ before naming a winner. The
  margin between candidates is often far tighter than the tolerance allowed
  on the scores themselves, so reproduce each candidate's formula exactly.
- SELF-REPORTED FLAGS: a field whose name declares a unit (_pct, _bps) is
  in that unit, and a *_validates / *_ok boolean must be recomputed from the
  numbers you actually wrote against the threshold the task states. If it
  comes out false, fix the computation - never ship a self-declared failure.
- UNGUARDED BRANCH: when a stated formula sits under a condition and the
  text gives no alternative for the failing case, the guarded action does
  NOT happen (zero, no trade, no row). Inventing a fallback changes the
  answer everywhere downstream.
- REQUESTED DATE: a valuation or scheduling date comes from the request, not
  from whichever date the data happens to contain. Build its grid from the
  session/template the task defines and use observed history only where the
  task says to; never substitute a nearby observed date for a requested one.
- RENDERED TEXT IS THE VALUE: stated decimal counts, zero-padded dates,
  ISO/Z suffixes and lowercase booleans are part of the deliverable. Format
  explicitly, then re-read the written file and check the literal text.
- RECURSIVE SIMULATION: loop over time steps with a whole-population vector
  per step - never vectorise across the recursion axis - start at the stated
  initial state, and check a per-step sigma is not re-scaled by sqrt(dt) a
  second time. Assert the terminal mean sits near the analytical mean.
- UNITS OF SENSITIVITIES: a bump-and-revalue sensitivity to a "+/-x%
  relative" bump is dV / (2 * x * parameter), in the units of the closed-
  form benchmark it will be compared to; "per 1%" prose never licenses an
  extra x0.01. Model parameters fitted on rescaled data (returns x100) are
  reported in NATIVE units after descaling. Horizon scaling multiplies the
  reported 1-day number by sqrt(h); it does not re-parameterise the
  distribution.
- RECONCILE ACROSS FILES: totals in a summary equal the sums of the detail
  files at the level the task aggregates (buckets, cohorts, non-absorbing
  rows only); any cost that is counted in a total is also posted to the
  ledger it belongs to. Assert both before exiting.
- OPTIMISER AT A BOUND: a fitted parameter sitting at its box bound (or a
  standard error of exactly 0, or a fit returning the library's starting
  values) is a wrong-likelihood signal, not an estimate - fall back to the
  moment/closed-form estimator the task allows and say so.
- SAMPLE WINDOW: performance and regression statistics use the trading or
  regime-aligned sub-sample only (never warm-up days with zero position);
  a rolling window of length W over n points yields n - W evaluations;
  data cleaning drops non-finite rows ONLY unless trimming is requested;
  counts are reported before windowing when the field says "valid"; keep
  first/last among duplicates means input-file order (stable sort).
- EVENT TIMELINE: a signal at close t executes at t+1; position state is
  keyed to EXECUTION time, so no new entry can be signalled while an exit
  is pending and no two opposite executions share a date; releases and
  cash updates happen BEFORE the evaluation step of the same timestamp when
  the text says "before". Assert these orderings on the trade log."""

CATEGORY = {
    "derivatives-pricing": """\
- Check put-call parity C - P = S - K*exp(-rT) on every matched pair.
- Bounds: call delta in [0,1], put delta in [-1,0], gamma/vega >= 0; allow
  the grader's epsilon at the bound - deep ITM/OTM saturates N(d1) to
  exactly 0 or 1 in floating point.
- theta is usually per CALENDAR DAY (divide by 365); T is in years; rates
  and vols are decimals (0.05 = 5%).
- Barrier options priced "analytically" mean the standard reflection
  (Reiner-Rubinstein) formulas; verify a barrier price against MC and the
  bounds 0 <= knock-out <= vanilla and knock-in + knock-out == vanilla.
- A spread-option approximation that reduces to the exchange-option formula
  at every strike is wrong: the second asset's vol must be strike-weighted.
  Verify against MC at the extreme strikes, not only at zero.
- Greeks are per unit of the underlying parameter unless the schema says
  otherwise; a per-contract Greek and a position Greek (x units held) are
  different fields - never put one under the other's name.""",
    "fixed-income": """\
- Discount factors live in (0,1] and strictly decrease with tenor.
- A bootstrap must REPRICE its inputs: par instruments back to par within
  the stated tolerance is the identity to assert.
- Zero rate <-> df conversions must state their compounding; take annual vs
  continuous from the text, then assert the round-trip.""",
    "portfolio": """\
- Weights sum to 1 (state the tolerance); attribution terms must reconcile:
  allocation + selection (+ interaction) == active return, per group and in
  total - assert the closure.
- Euler risk contributions sum EXACTLY to the portfolio measure; standalone
  measures do not - do not confuse the two. The decomposition is on
  VOLATILITY: marginal = (Sigma w) / sigma_p, component = w * marginal,
  components sum to sigma_p, percentages divide by sigma_p.
- An EWMA covariance recursion is seeded with the first observation's outer
  product and iterated from the second observation, over the stated window
  only; returns are not de-meaned unless told.
- Average leverage is the time-mean of gross exposure sum(|w_i|) over the
  full sample, not a per-element mean.""",
    "risk-management": """\
- ES >= VaR at every level; both rise with confidence - assert the ordering.
- Use the quantile method the task names verbatim (e.g. numpy.quantile
  method='linear'); alternative estimators fail exact graders.
- Fix the sign convention (losses positive vs returns negative) from the
  text before computing anything; VaR and ES are positive loss magnitudes,
  and an empty tail (no path beyond VaR) still yields a non-negative ES.
- Parametric ("analytical") VaR/ES are closed-form expressions of the
  fitted distribution - never a hybrid that averages sample points below a
  parametric quantile.
- A GARCH fit for pricing uses the FINAL-observation conditional volatility
  in decimal, annualised by sqrt(252); the long-run variance is a diagnostic
  only. Fit with zero mean on percent-scaled data, descale the parameters,
  and treat a fit that returns the library's starting values as failed.
- Marchenko-Pastur noise edge uses q = n_assets / window_length.""",
    "credit": """\
- Transition matrix rows sum to 1; cumulative PD is monotone in horizon;
  matrix powers need the time-step stated, not assumed.
- When fine ratings are merged into buckets, aggregate every correction
  (hidden defaults, external counts) at the BUCKET level before differencing
  against the bucket's visible count; absorbing-state start rows carry no
  transitions and are excluded from every total.
- Survival = product of (1 - marginal hazard); assert survival + cumulative
  default = 1.""",
    "backtesting": """\
- No lookahead: a signal computed at t trades at t+lag exactly as stated;
  assert the first traded bar respects the lag.
- Apply costs with the stated unit (bps of traded notional, per side or
  round-trip as written); net and gross series must differ by exactly the
  summed costs.
- A trend signal described as a moving-average crossover with no magnitude
  rule is BINARY: sign(fast - slow) in {+1, -1}.
- Annualise from the mean daily LOG return (exp(mean*252)-1) when returns
  are log returns; state ddof; subtract the annual risk-free rate from the
  annualised mean for Sharpe.
- A closed date range given as calendar dates includes the whole last day:
  expand the upper bound to end-of-day, then assert row count == days x
  stated cadence and that first/last rows sit on the boundary dates.""",
    "microstructure": """\
- VWAP must lie within the min/max of its own fills; participation is a
  fraction of market volume in [0,1] - assert both.
- Preserve event ordering by timestamp; ties broken as the text says.
- Realised-variance noise corrections use the estimator the citation
  defines (highest-frequency RV over twice its return count for the
  Bandi-Russell family); corrected RVs must stay non-negative.
- Aggregate-loss FFT/Panjer grids: size the span from an empirical high
  quantile of the aggregate (MC or iterated CDF), never from mean + k*sd
  when severity is heavy-tailed; any need to renormalise clipped mass is
  aliasing.""",
    "factor-research": """\
- Regress jointly when factors correlate - one-by-one betas differ and
  residuals stop being orthogonal; assert residual orthogonality to every
  factor if stated.
- Rank/IC metrics: use the stated correlation kind (Pearson vs Spearman).
- Dependence-adjusted event-study statistics (BMP, Kolari-Pynnonen,
  Corrado) follow the cited paper's formula exactly; a paraphrase that would
  INFLATE a test statistic under positive cross-correlation is a red flag.
- Permutation / sign-flip p-values are tie-inclusive: compare with a
  tolerance so the untouched configuration counts.""",
}

#: Instruction keywords that pull in a category block even when the card's
#: category is missing or 'cross-domain' (the largest bucket).
KEYWORDS = {
    "derivatives-pricing": ("option", "black-scholes", "greek", "strike",
                            "implied vol"),
    "fixed-income": ("yield curve", "discount factor", "bootstrap", "par rate",
                     "duration", "bond"),
    "portfolio": ("attribution", "brinson", "weights", "risk parity",
                  "contribution"),
    "risk-management": ("var", "cvar", "expected shortfall", "quantile",
                        "drawdown"),
    "credit": ("transition matrix", "hazard", "default", "migration", "cds"),
    "backtesting": ("backtest", "signal", "turnover", "lookahead",
                    "moving average"),
    "microstructure": ("vwap", "order book", "fills", "participation",
                       "imbalance"),
    "factor-research": ("factor", "regression", "residual", "information "
                        "coefficient"),
}


def select(category: str | None, instruction: str) -> str:
    """Universal lessons plus every category block the unit plausibly needs."""
    parts = [UNIVERSAL]
    text = (instruction or "").lower()
    chosen = []
    for slug, block in CATEGORY.items():
        if slug == (category or ""):
            chosen.append((0, slug, block))
            continue
        hits = sum(1 for k in KEYWORDS.get(slug, ()) if k in text)
        if hits >= 2:
            chosen.append((1, slug, block))
    for _, slug, block in sorted(chosen):
        candidate = "\n".join(parts + [f"[{slug}]", block])
        if len(candidate) > MAX_CHARS:
            break
        parts += [f"[{slug}]", block]
    return "\n".join(parts)
