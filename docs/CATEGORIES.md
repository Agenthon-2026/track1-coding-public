# Track 1 Task Categories — Full Reference

## Executive summary (read this first)

Track 1 grades AI agents on their ability to write correct quantitative-finance code. To keep
tasks comparable and reviewable, every task belongs to one of **ten categories** — from pricing
stock options to reading earnings-call text. This document explains what each category is, why it
matters in the real world, what financial sanity checks ("invariants") a grader must apply, and
what makes tasks easy or hard. **If you are new to quantitative finance, read the definitions in
the margins — every technical term is explained the first time it appears.** For the official list
of all terms, see the competition-wide GLOSSARY published with the shared toolkit:
`Agenthon-2026/Agenthon2026-public`, file `docs/GLOSSARY.md`.

Every task card sets `[metadata] category` to one of the ten IDs below. The category controls
which domain expert reviews the task and which automated sanity checks run at gate
`g3_domain_semantics` (the fourth quality gate; see `public/docs/CONCEPTS.md` for what gates are).

Difficulty default: **medium** — the task must defeat a simple one-shot language-model call while
still being solvable by a well-designed agent in under 30 minutes of wall-clock time.

---

## 1. `derivatives-pricing`

### What this is (plain English)

A **derivative** (also called an "option" or "contract") is a financial instrument whose value
*derives* from something else — typically a stock price, an interest rate, or a commodity price.
The most common example is a **European call option**: the right (but not the obligation) to buy
a share of stock at a fixed price (the **strike**, K) on a specific future date (the **expiry**,
T). If the stock is trading above K on that date, you exercise and pocket the difference. If not,
you let it expire worthless.

**Pricing** means computing the fair value of that contract today. The workhorse is the
**Black-Scholes model** (BS), which takes five numbers — spot price S, strike K, time to expiry T,
risk-free rate r, volatility σ — and returns a price and a set of **Greeks** (sensitivities, named
after Greek letters: Delta measures how much the price moves when S moves; Gamma is the rate of
change of Delta; Vega measures sensitivity to σ; Theta to time).

**Real-world scenario.** You work at an options desk. A trader shows you a list of 50 options and
asks: "What are these worth today, and how do I hedge them?" Your job is to implement a BS pricer
and output the price plus Greeks for each row. The risk manager then checks that your prices obey
put-call parity and that your Greeks have the right signs before approving the hedge.

### Example task ideas

1. **BS PDE Greek solver.** Given a table of European option parameters, solve the
   Black-Scholes PDE (partial differential equation) on a finite-difference grid and output price
   plus Delta, Gamma, Vega, Theta for each row. (The exemplar task `t1-EXAMPLE-bs-greeks-pde`
   does exactly this.)
2. **Heston model calibration.** Given observed market option prices at multiple strikes and
   maturities, fit the five Heston stochastic-volatility parameters (v0, kappa, theta, xi, rho)
   to minimise pricing error. Output the calibrated parameters and the repriced surface.
3. **Barrier option Monte Carlo.** Price a down-and-out call (which expires worthless if the
   stock ever trades below a barrier B) using Monte Carlo simulation with 10,000+ paths and
   antithetic variates as a variance-reduction technique.

### Key concepts (each in one sentence)

- **European option.** A contract that can only be exercised on the expiry date (not before).
- **Black-Scholes PDE.** A partial differential equation that describes how an option price
  changes over time and with the stock price; solving it gives the fair value.
- **Greeks.** The first- and second-order sensitivities of an option price to its input
  parameters (Delta = ∂V/∂S; Gamma = ∂²V/∂S²; Vega = ∂V/∂σ; Theta = ∂V/∂t).
- **Put-call parity.** A no-arbitrage relationship that says C − P = S − K·exp(−rT) exactly,
  where C is a call price and P is a put price on the same underlying, strike, and expiry.
- **Implied volatility.** The volatility σ that makes the Black-Scholes formula match an
  observed market price; it is inferred (implied) rather than observed directly.
- **Stochastic volatility.** Models (like Heston) where σ itself changes randomly over time,
  making them more realistic than constant-σ Black-Scholes.
- **Finite-difference method.** Solving the BS PDE by replacing the continuous derivatives with
  discrete approximations on a grid of stock-price × time points.
- **Monte Carlo simulation.** Pricing by simulating thousands of random stock-price paths and
  averaging the payoff across them.

### Financial invariants a grader must check

These are **structural** checks — they should hold for any correct pricing model, not just one
specific method.

| Invariant | What to check | Why it must hold |
|---|---|---|
| Put-call parity | `C − P ≈ S − K·exp(−rT)` within 1e-3 USD | If violated, you could lock in a riskless profit by simultaneously buying the cheap side and selling the expensive side — a textbook arbitrage. |
| Call delta in (0, 1) | `0 < delta_call < 1` for every row | A call can never move more than $1 for a $1 move in the stock (it would be cheaper to just buy the stock). |
| Put delta in (−1, 0) | `−1 < delta_put < 0` | Symmetric argument for puts. |
| Gamma > 0 | `gamma > 0` for all European options | Gamma = second derivative of value with respect to spot; a negative Gamma would mean a concave payoff, which no-arbitrage rules out for European options. |
| Vega > 0 | `vega > 0` for all European options | Higher uncertainty (higher σ) always increases option value — more upside without adding downside (the optionality benefit). |
| Price ≥ intrinsic value | `call_price ≥ max(0, S − K·exp(−rT))` | You could buy the option and immediately exercise it (even for a European, you could replicate the payoff); if cheaper, free money. |
| Price ≤ upper bound | `call_price ≤ S`; `put_price ≤ K·exp(−rT)` | A call can never be worth more than owning the stock itself. |
| No calendar spread arbitrage | Option price non-decreasing in T at fixed K | A longer-dated option gives you all the optionality of the shorter one and more; it cannot be cheaper. |
| Butterfly / convexity | `∂²C/∂K² ≥ 0` across strikes | If violated, you can buy a butterfly spread and extract riskless profit. |
| BS PDE residual near zero | `‖LV − ∂V/∂t‖_∞ < ε` on interior grid points | The numerical solution must actually solve the equation it claims to solve. |

### Typical difficulty and why

**Easy tasks** price one vanilla European option with a closed-form formula.
**Medium tasks** implement a full PDE or MC solver across a table of options and check at least
two invariants (e.g. put-call parity + delta bounds).
**Hard tasks** add: model calibration to a volatility surface; American early-exercise (which
requires an optimal stopping problem); multi-factor term structure models; or exotic payoffs
(barriers, Asians, lookbacks).

### Common mistakes

- Forgetting to convert theta from per-year to per-day (divide by 365).
- Using total returns instead of *excess* returns (above the risk-free rate) when computing Sharpe.
- Outputting `sigma` as a percentage (20) instead of a decimal (0.20) — the instruction always
  states the convention.
- Forgetting the `exp(−rT)` discount on the strike in put-call parity.
- Hardcoding a specific numerical method when the task says "any method" — the tests check
  invariants, not the algorithm.
- Running into numerical instability at very short maturities (T < 5 days) on a coarse grid.

---

## 2. `fixed-income`

### What this is (plain English)

**Fixed income** refers to bonds and related instruments that pay a stream of known (or
deterministic) cash flows. The simplest bond pays a fixed **coupon** (interest) every six months
for, say, 10 years, then returns the **face value** (principal) at maturity. The bond's **price**
is the present value of all those future cash flows, discounted at the current market yield.

**Yield** and price move in opposite directions: if the market wants a higher return (yield goes
up), the present value of fixed coupons falls (price goes down). This inverse relationship is the
first thing every fixed-income practitioner learns.

**Real-world scenario.** You manage a $100 million bond portfolio for a pension fund. Your boss
asks: "What is the interest-rate sensitivity of our portfolio? If rates rise by 0.01% (1 basis
point), how much do we lose?" Your job is to compute **DV01** (the dollar value of a 1 basis-point
move) for each bond, then design a **duration hedge** using interest-rate swaps to protect the
portfolio.

### Example task ideas

1. **Nelson-Siegel curve fitting.** Given a set of observed Treasury bond prices at various
   maturities, fit the Nelson-Siegel-Svensson model to extract a smooth yield curve. Output
   the curve parameters and repriced bond yields at a grid of maturities.
2. **DV01 and duration matching.** Given a liability schedule (future cash flows) and a
   universe of bonds, find the bond portfolio weights that match the liability's DV01 and
   convexity while minimising tracking error.
3. **OIS multi-curve bootstrap.** Under the post-2008 multi-curve framework, bootstrap separate
   discount factors (OIS) and projection curves (LIBOR/SOFR) from a set of market instruments
   (deposits, FRAs, swaps). Output a discount factor grid.

### Key concepts

- **Coupon.** The periodic interest payment on a bond, expressed as a fraction of face value.
- **Yield to maturity (YTM).** The single discount rate that equates the present value of all
  future cash flows with today's market price; it is the bond's "internal rate of return."
- **Duration.** A measure of how long, on average, it takes to receive the bond's cash flows;
  also a measure of price sensitivity to yield changes (higher duration = more sensitive).
- **Modified duration.** Duration scaled by `1/(1+y)` where y is the yield; gives the
  approximate percentage price change for a 1-unit yield change.
- **DV01 (dollar value of a basis point).** The change in price for a 0.01% (1 bp) rise in
  yield; computed as `modified_duration × price × 0.0001`.
- **Convexity.** The second-order price sensitivity to yield; a bond with higher convexity
  gains more than it loses when yields move by the same amount in either direction.
- **Discount factor.** A number between 0 and 1 that represents the present value of $1
  payable at a future date; it is `exp(−r·T)` for continuously compounded rates.
- **OIS (Overnight Index Swap).** A swap that exchanges a fixed rate for a compounded overnight
  rate (e.g. SOFR); used as the discount rate after the 2008 financial crisis.
- **Bootstrap.** The iterative process of solving for discount factors one maturity at a time
  from a sequence of market prices.

### Financial invariants a grader must check

| Invariant | What to check | Why it must hold |
|---|---|---|
| Price decreases with yield | Numerically verify `P(y+ε) < P(y)` | Basic inverse relationship of bond price and yield. |
| Par bond at par | A bond with coupon = yield must price at 100 | Definitional: par bond means coupon exactly offsets the time value. |
| DV01 consistency | `DV01 ≈ −∂P/∂y × 0.0001` within 0.1% | DV01 must match the finite-difference approximation of the price-yield function. |
| Swap NPV = 0 at fair rate | The fixed rate that makes swap NPV = 0 equals the par swap rate | A swap at inception has zero value to both counterparties by definition. |
| Discount factors positive and decreasing | `DF(0) = 1`, `DF(T₁) > DF(T₂)` for T₁ < T₂ | A dollar received sooner is always worth more than a dollar received later. |
| Modified duration formula | `ModDur × P ≈ DV01 / 0.0001` | Algebraic identity; violations signal a calculation bug. |

### Typical difficulty and why

**Medium tasks** price a handful of vanilla bonds, compute DV01, and check 2–3 invariants.
**Hard tasks** involve multi-curve bootstrapping under OIS reform (two curves, not one),
convexity adjustments for futures vs. forwards, or prepayment model calibration for
mortgage-backed securities.

### Common mistakes

- Mixing "yield" conventions (annual vs. semi-annual compounding, or actual/actual vs.
  30/360 day-count).
- Forgetting the accrued interest component in "dirty price" vs. "clean price."
- Using the wrong compounding frequency when converting between yield and discount factor.
- Not adjusting DV01 for the notional (a $1 million bond has 10,000× the DV01 of a $100 face bond).

---

## 3. `credit`

### What this is (plain English)

**Credit risk** is the risk that a borrower (a company, bank, or government) fails to repay its
debt — called a **default**. **Credit derivatives** are contracts that let investors buy or sell
protection against default. The most important one is the **credit default swap** (CDS): you pay
a fixed premium (the "spread") every quarter; if the reference company defaults, you receive the
face value of the bond in return.

**Real-world scenario.** You work on the credit desk at a bank. A hedge fund wants to buy
protection on $10 million of XYZ Corp debt over the next 5 years. Your job is to build a
**hazard-rate model** (a model of the instantaneous default rate at each moment in time) from
observed CDS prices at 1, 3, and 5 years, and then price a custom 4-year CDS for the client.

### Example task ideas

1. **CDS curve bootstrap.** Given par CDS spreads at 1Y, 3Y, 5Y, and 10Y maturities, bootstrap
   a piecewise-constant hazard-rate (default intensity) curve. Output the hazard rates and
   survival probabilities at each tenor.
2. **Merton structural model.** Treat a company's equity as a call option on its assets (Merton
   1974). Given equity price, equity volatility, face value of debt, and maturity, infer the
   asset value and asset volatility. Output the implied default probability and distance to
   default.
3. **CVA calculation.** Given an interest-rate swap and a counterparty hazard-rate curve, compute
   the credit valuation adjustment (CVA) — the expected loss due to the counterparty defaulting
   before maturity.

### Key concepts

- **Default.** The event where a borrower fails to make a scheduled payment or declares bankruptcy.
- **Hazard rate (default intensity), λ.** The instantaneous probability of defaulting in the
  next small time interval dt, given survival to time t; roughly, λ(t)·dt = P(default in [t, t+dt]).
- **Survival probability.** The probability that a company has not defaulted by time T, equal to
  `S(T) = exp(−∫₀ᵀ λ(s) ds)`.
- **CDS spread (par spread).** The annual premium (as a fraction of notional) at which the
  present value of premium payments equals the present value of protection payments; it is the
  "fair rate" for the CDS.
- **Recovery rate.** The fraction of face value recovered after default; a standard assumption
  is 40% (i.e. you recover $0.40 per $1 face).
- **CVA (Credit Valuation Adjustment).** The reduction in the price of a derivative to account
  for the possibility that the counterparty defaults; it equals the expected loss from
  counterparty default.
- **Gaussian copula.** A statistical model for the joint default probability of multiple
  companies; it links their marginal default probabilities through a multivariate normal
  correlation structure.

### Financial invariants a grader must check

| Invariant | What to check | Why it must hold |
|---|---|---|
| Survival probability is monotone decreasing | `S(T₁) > S(T₂)` for T₁ < T₂ | The longer you wait, the more chances there were to default; survival probability can only fall. |
| Hazard rates positive | `λ(t) > 0` at all tenors | A negative default intensity has no meaning; it would imply negative default probability. |
| CDS legs balance at par spread | `PV(premium leg) = PV(protection leg)` at the par spread | This is the definition of the par spread; a violation means the pricing formula is wrong. |
| CVA ≥ 0 | `CVA ≥ 0` | CVA is an expected loss; it cannot be negative. |
| Tranche total = portfolio total | Sum of losses across all tranches = total portfolio default loss | Each dollar of loss must be absorbed by exactly one tranche. |

### Typical difficulty and why

**Medium tasks** bootstrap a CDS curve from 3–5 inputs and reprice one new CDS.
**Hard tasks** involve: wrong-way risk (CVA where the counterparty is more likely to default when
the swap has a large positive value to you); stochastic intensity models; or multi-name correlation
structures (CLO tranching, CDO pricing).

### Common mistakes

- Confusing "spread" with "upfront" CDS quotation (post-2009, most IG CDS are quoted
  upfront; HY CDS still use spread).
- Forgetting to condition on survival when computing expected premium-leg cash flows.
- Using continuous compounding for hazard rates but annual compounding for bond yields in the
  same calculation.

---

## 4. `factor-research`

### What this is (plain English)

**Equity factors** are systematic characteristics of stocks that predict future returns. The most
famous are: **Value** (cheap stocks outperform expensive ones), **Momentum** (stocks that have
risen recently keep rising in the short term), and **Quality** (profitable, stable companies
outperform). A **factor portfolio** is a long-short portfolio — you buy stocks with high factor
scores and short-sell stocks with low scores — that tries to capture the factor premium.

**Real-world scenario.** You work at a systematic hedge fund. The portfolio manager wants to know
whether a new "earnings surprise" factor actually predicts stock returns after accounting for
transaction costs. You need to: rank all S&P 500 stocks by the factor, form a long-short
portfolio, compute the information coefficient (IC, the rank correlation between the factor and
next-month returns), and verify that the portfolio is dollar-neutral (equal dollar amounts long
and short).

### Example task ideas

1. **Momentum factor construction.** Given 24 months of monthly returns for 200 stocks, compute
   the 12-1 momentum signal (total return from month −12 to month −1, skipping the most recent
   month), rank stocks into quintiles, and compute the long-minus-short return for the next month.
2. **Cross-sectional factor regression.** Given a panel of stock returns and factor exposures
   (size, value, momentum), run a Fama-MacBeth two-pass regression to estimate the factor risk
   premia. Output the factor returns and their t-statistics.
3. **Signal combination with IC weighting.** Given three alpha signals with different ICs and
   correlations, compute the optimal combination weights using the IC-IR framework. Output the
   combined signal and the improvement in IR over any single signal.

### Key concepts

- **Long-short portfolio.** A portfolio that buys some stocks (the "long" leg) and short-sells
  others (the "short" leg); profits from relative performance, not absolute market direction.
- **Dollar-neutral.** The portfolio's total dollar long exposure equals its total dollar short
  exposure, so it is not sensitive to overall market moves.
- **IC (Information Coefficient).** The rank correlation (Spearman correlation) between a
  factor score and the future return it is supposed to predict; a higher IC means more predictive.
- **IR (Information Ratio).** The average IC divided by the standard deviation of IC over time;
  higher is better.
- **Barra factor model.** A commercial risk model that decomposes stock returns into a set of
  factor exposures (style, industry) and a residual; widely used in portfolio construction.
- **Alpha decay.** The tendency of a factor's predictive power to decrease the further in the
  future you look; knowing the decay rate tells you how often to rebalance.
- **Transaction costs.** Costs of trading (bid-ask spread, market impact, commissions) that
  reduce realized returns relative to the "paper portfolio."
- **No look-ahead bias.** A data hygiene rule: the signal date must strictly precede the return
  measurement period; using tomorrow's data to rank today's stocks is cheating.

### Financial invariants a grader must check

| Invariant | What to check | Why it must hold |
|---|---|---|
| Dollar-neutral | `sum(weights) ≈ 0` | If the portfolio has net long exposure, part of its return is just the market going up, not the factor. |
| IC in [−1, 1] | The rank correlation is bounded | IC is a Spearman correlation; any value outside [−1, 1] signals a calculation error. |
| Annualised Sharpe from excess returns | Sharpe denominator uses sample std of (return − risk-free rate) | Computing Sharpe on total returns, not excess returns, overstates risk-adjusted performance. |
| Beta near zero after market neutralisation | Regress factor portfolio returns on market returns; β ≈ 0 | A "market-neutral" factor portfolio by construction should not be exposed to market beta. |
| No forward-looking bias | Signal date precedes return start date | Using future data in signal construction invalidates the entire backtest. |
| Turnover ≥ 0 | Sum of absolute weight changes is non-negative | Turnover is a magnitude; it cannot be negative. |

### Typical difficulty and why

**Medium tasks** compute one clean factor with proper data hygiene, form quintile portfolios, and
report IC.
**Hard tasks** add signal combination, alpha decay measurement, transaction-cost-aware
optimisation (e.g. penalising portfolio turnover), or replication of a published factor paper.

### Common mistakes

- Sorting stocks by the raw factor instead of ranking within each date (cross-sectional
  normalization is essential).
- Using "point-in-time" data incorrectly — survivorship bias (including only stocks that still
  exist today) or revision bias (using the final value of a series that was revised after the
  fact).
- Annualizing incorrectly (multiply monthly Sharpe by √12, not 12).

---

## 5. `backtesting`

### What this is (plain English)

**Backtesting** means simulating a trading strategy on historical data to estimate how it would
have performed. You define rules (e.g. "buy when the 50-day moving average crosses above the
200-day moving average"), apply them to past prices, and compute the hypothetical profit and loss.
The key challenge is doing this **honestly** — without peeking at future data, without ignoring
transaction costs, and without overfitting the rules to history.

**Real-world scenario.** You have designed a simple strategy: every month, rebalance a portfolio
to hold the 20 highest-momentum stocks in the S&P 500 in equal weights. You want to know: what
would the annual return, Sharpe ratio, and maximum drawdown have been over the past 10 years?
How much of the profit is eaten by trading costs?

### Example task ideas

1. **Self-financing portfolio simulation.** Given a monthly rebalancing schedule and a set of
   portfolio weights, compute the portfolio value path from an initial $1 million, applying
   transaction costs of 5 bp per trade. Verify the portfolio is self-financing.
2. **Walk-forward optimisation.** For a mean-reversion strategy with one lookback-period
   parameter, run a walk-forward optimisation — fit the parameter on a 12-month training window,
   trade on the next 3 months, then roll forward — to get an honest out-of-sample Sharpe.
3. **Regime detection and switching.** Fit a hidden Markov model (HMM) to identify bull and bear
   market regimes. Implement a strategy that switches between a momentum portfolio (bull) and a
   minimum-variance portfolio (bear). Report performance in each regime.

### Key concepts

- **Self-financing portfolio.** A portfolio where all rebalancing is funded from within — no
  cash is added or withdrawn; value changes come only from price changes and reinvested dividends.
- **Returns compounding.** `V_n = V_0 × (1+r₁) × (1+r₂) × … × (1+r_n)` — the terminal value
  is the starting value times the product of gross returns.
- **Maximum drawdown.** The largest peak-to-trough decline in portfolio value; a measure of
  the worst experience a strategy delivered to an investor.
- **Sharpe ratio.** Mean excess return (above the risk-free rate) divided by the standard
  deviation of excess returns, annualized; measures return per unit of risk.
- **Turnover.** The fraction of portfolio value traded each period; high turnover means high
  transaction costs.
- **Look-ahead bias.** Using information that was not yet available at the time a trade would
  have been made; the single most common error in naive backtests.
- **Walk-forward optimisation.** An honest parameter selection procedure: fit on past data,
  then test on the immediately following (unseen) period, then roll forward.
- **Slippage.** The additional cost due to large orders moving the market price against you.

### Financial invariants a grader must check

| Invariant | What to check | Why it must hold |
|---|---|---|
| Self-financing | `V_n = V_{n-1} × (1 + portfolio_return_n)` | If the portfolio grows without trades, money appeared from nowhere. |
| Returns compounding | `(1+r₁)(1+r₂)…(1+rₙ) = V_n/V_0` | Terminal wealth must equal starting wealth compounded by the product of gross returns. |
| No look-ahead bias | Signal computed from data available at signal_date only | The only way to catch this in code is to verify that the timestamp of each data point used predates the trade date. |
| Maximum drawdown ≤ max observed loss | `max_drawdown ≤ max single-period loss` in magnitude... actually max single-period loss ≤ max_drawdown | Drawdown accumulates over multiple periods; the worst single period is a lower bound. |
| Turnover ≥ 0 | `turnover ≥ 0` at every rebalance | Turnover is a sum of absolute weight changes; it cannot be negative. |
| Sharpe from excess returns | Use `(r − rf)` in numerator and denominator std | Computing Sharpe on gross returns misstates risk-adjusted performance. |

### Typical difficulty and why

**Medium tasks** run a simple rule-based strategy with correct P&L accounting.
**Hard tasks** add: realistic transaction-cost models; statistically rigorous Sharpe significance
tests (bootstrap under the null of no skill); regime detection; or multi-strategy portfolio
optimisation with constraints.

### Common mistakes

- Reusing in-sample fitted parameters on the same data they were fitted to (the parameter
  overfit problem; always use out-of-sample testing).
- Not adjusting for the risk-free rate when computing Sharpe.
- Using closing prices to calculate the trade but buying at closing prices too — real trades
  execute at the next open.

---

## 6. `risk-management`

### What this is (plain English)

**Market risk** is the risk of losing money because prices move against you. Banks and hedge funds
must quantify this risk every day so they hold enough capital to survive bad scenarios.
The most common measure is **VaR (Value at Risk)**: "With 99% confidence, we will not lose more
than $X million in the next trading day." But VaR has a flaw — it tells you nothing about the
*size* of the loss beyond that threshold. **CVaR** (also called **Expected Shortfall**, ES) fixes
this: "Given that we are in the worst 1% of days, what is the average loss?" CVaR is always
at least as large as VaR at the same confidence level.

**Real-world scenario.** You are a risk manager at a bank. You have a portfolio of 20 equities
and 10 interest-rate swaps. Your regulator (under the FRTB rules) requires you to report the
99% VaR and the 97.5% ES every day. Your job is to implement historical simulation and delta-
normal methods for VaR/ES and pass the backtesting requirement (fewer than 4 exceptions in
250 days).

### Example task ideas

1. **Historical simulation VaR and ES.** Given 2 years of daily returns for a 10-asset
   portfolio with given weights, compute the 1-day 95% and 99% VaR and CVaR using
   historical simulation. Output a results table plus the VaR breach dates.
2. **Delta-normal VaR with correlation.** Given a covariance matrix and a vector of portfolio
   deltas (sensitivities to risk factors), compute the parametric (delta-normal) 1-day 99% VaR
   using a multivariate normal model. Also compute the component VaR for each position.
3. **Stress testing.** Given a set of historical stress scenarios (e.g. 2008 crisis, 2020 COVID
   crash), compute the portfolio's stressed P&L for each scenario and rank them. Identify the
   three largest risk contributors under the worst scenario.

### Key concepts

- **VaR (Value at Risk).** The loss level that is exceeded with probability (1 − confidence);
  e.g. 99% VaR is the 99th percentile of the loss distribution.
- **CVaR / Expected Shortfall (ES).** The average loss *conditional on* being in the worst
  (1 − confidence) fraction of outcomes; always ≥ VaR at the same confidence level.
- **Historical simulation.** Computing VaR/ES by applying historical return scenarios to
  today's portfolio, without assuming a parametric distribution.
- **Delta-normal (parametric) VaR.** Assumes returns are normally distributed and computes
  VaR from the portfolio mean and variance; fast but inaccurate for non-normal returns.
- **Subadditivity.** The property of a risk measure where the combined portfolio risk ≤ sum
  of individual risks; ES is subadditive, VaR is not (for general distributions).
- **FRTB (Fundamental Review of the Trading Book).** Basel Committee rules (effective 2025)
  that require banks to use ES at 97.5% confidence rather than VaR at 99%.
- **Greeks aggregation.** Summing sensitivities (deltas, gammas) across all positions to get
  the total portfolio sensitivity to each risk factor.

### Financial invariants a grader must check

| Invariant | What to check | Why it must hold |
|---|---|---|
| CVaR ≥ VaR | At same confidence level | CVaR is the average of the worst losses; VaR is a percentile; the average of the worst is always at least the threshold. |
| VaR non-decreasing in confidence | 99% VaR ≥ 95% VaR | Higher confidence = more conservative threshold = larger (absolute) loss number. |
| Diversified portfolio VaR ≤ sum of individual VaRs | For ES | ES is subadditive: combining assets reduces risk (for ES); a violation suggests a calculation error. |
| Delta-neutral hedge reduces delta ± tolerance | After adding a hedge position, net delta ≈ 0 | A delta-neutral hedge by construction eliminates first-order price sensitivity. |
| Stress loss consistency | Stress P&L = Σ(position_i × scenario_return_i) | Stress losses are computed from position values and scenario returns; discrepancy signals a summation bug. |

### Typical difficulty and why

**Medium tasks** compute historical VaR/ES for a simple portfolio and check the VaR ≥ CVaR
ordering.
**Hard tasks** add FRTB sensitivities-based aggregation (bucketing Greeks by tenor and risk
factor class, then applying prescribed correlations); correlated multi-factor Monte Carlo; or
CVA-VaR (the market risk of the CVA position itself).

### Common mistakes

- Using absolute returns instead of log-returns (or vice versa) without consistency.
- Computing ES as the average of *all* losses rather than the average of losses *beyond* the
  VaR threshold.
- Not annualizing — 1-day VaR ≠ 1-year VaR; scale by √T for normal models.

---

## 7. `microstructure`

### What this is (plain English)

**Market microstructure** studies how trades actually happen — the mechanics of order books,
bid-ask spreads, price impact, and the strategies traders use to execute large orders without
moving the market against themselves. If you want to buy 1 million shares of a stock in one hour,
you cannot just place one big order: you would move the price up dramatically, buying at worse
and worse prices. **Optimal execution** algorithms (like TWAP or the Almgren-Chriss model) split
the order into smaller pieces over time to minimise this market impact.

**Real-world scenario.** Your fund needs to sell 500,000 shares of ABC by end of day. The risk
manager sets a limit: expected transaction cost must be below $50,000. Your job is to compute the
optimal trading trajectory (how many shares to sell in each 10-minute interval) under the
Almgren-Chriss model, accounting for both market impact and timing risk.

### Example task ideas

1. **Effective spread estimation.** Given a file of trade-and-quote (TAQ) tick data, implement
   Roll's model to estimate the effective bid-ask spread. Output the estimated spread for each
   15-minute interval throughout the trading day.
2. **Almgren-Chriss optimal trajectory.** Given a position to liquidate (shares, price, daily
   volume, volatility), compute the optimal selling trajectory under the Almgren-Chriss model
   (minimising expected cost + λ × variance of cost). Output the schedule of trades per interval.
3. **VPIN (Volume-Synchronized Probability of Informed Trading).** Given a series of tick data
   with volume and buy/sell classification, compute VPIN — a measure of the fraction of volume
   that is "informed" (likely to predict near-term price moves).

### Key concepts

- **Order book.** The list of all outstanding buy (bid) and sell (ask) orders at each price
  level; the spread is the gap between the best bid and the best ask.
- **Bid-ask spread.** The difference between the best price at which someone will sell
  (ask) and the best price at which someone will buy (bid); a transaction cost for immediacy.
- **Effective spread.** The actual cost of a transaction, accounting for the fact that trades
  sometimes happen inside the quoted spread; computed from trade-and-quote data.
- **Market impact.** The price movement caused by a trade — buying pressure pushes the price
  up; selling pressure pushes it down.
- **TWAP (Time-Weighted Average Price).** A benchmark execution strategy that splits the order
  into equal pieces over time; simple but not optimal.
- **VWAP (Volume-Weighted Average Price).** A benchmark that weights each trade by its volume
  share; buying at or below VWAP is a common performance target.
- **Almgren-Chriss model.** A mathematical model that finds the optimal trade schedule
  minimising expected cost plus a risk penalty (variance of cost); used industry-wide for
  liquidation and accumulation problems.
- **PIN / VPIN.** Metrics that estimate the fraction of trading volume from "informed" traders
  (those with private information); high PIN/VPIN predicts wider spreads and larger impact.

### Financial invariants a grader must check

| Invariant | What to check | Why it must hold |
|---|---|---|
| Bid ≤ Ask | `bid_price ≤ ask_price` at every tick | A crossed book (bid > ask) is an arbitrage: buy at the ask, immediately sell at the higher bid. |
| Effective spread ≥ 0 | `effective_spread ≥ 0` | Transaction costs cannot be negative; a negative spread would mean you are paid to trade. |
| Almgren-Chriss trajectory is monotone | If liquidating, shares sold per interval ≥ 0 | You are selling, not re-buying; a re-buy in the middle of a sell trajectory is inconsistent. |
| Market impact is non-negative | Buying moves price up; selling moves price down | Orders always move prices against the aggressor; a negative impact means the model is backwards. |
| VWAP within high-low range | Execution price ≤ day high, ≥ day low | VWAP is an average of executed prices; it cannot exceed the highest or fall below the lowest traded price. |
| Total executed = target | Sum of scheduled trades = initial position | The whole point of the trajectory is to liquidate (or accumulate) the entire position. |

### Typical difficulty and why

**Medium tasks** implement a spread estimator or a VWAP schedule from historical data.
**Hard tasks** involve calibrating a market-impact model from real tick data, implementing a
full limit-order-book (LOB) simulator, or solving the full Almgren-Chriss stochastic
optimisation with general constraints.

### Common mistakes

- Missing the "no re-buy" constraint in the liquidation trajectory.
- Confusing "quoted spread" (bid-ask difference) with "effective spread" (twice the trade-
  midpoint difference).
- Off-by-one in the time grid (selling in N+1 intervals instead of N).

---

## 8. `fx`

### What this is (plain English)

**FX (foreign exchange)** is the market where currencies are traded against each other. Every
FX rate has a convention: EUR/USD = 1.08 means 1 euro buys 1.08 dollars. A **forward** is a
contract to exchange currencies at a fixed rate on a future date. **Covered interest parity**
(CIP) says the forward rate must equal the spot rate adjusted for the interest-rate differential
between the two currencies — otherwise there is an arbitrage.

**Triangular arbitrage** is the attempt to profit by trading three currencies in sequence
(EUR → USD → JPY → EUR) if the implied cross rate does not match the direct rate. In efficient
markets these are eliminated within milliseconds; detecting them is a classic coding task.

**Real-world scenario.** You are a corporate treasury analyst. Your company receives €5 million
in three months. You want to lock in the USD value today by buying a forward contract. Your job
is to compute the 3-month EUR/USD forward rate from the spot rate, EUR overnight rate, and
USD overnight rate, and verify that no triangular arbitrage exists in the current market.

### Example task ideas

1. **Covered interest parity and forward curve.** Given spot rates, domestic and foreign
   interest rates at several tenors, compute the full forward curve for EUR/USD and verify CIP
   at each tenor.
2. **Triangular arbitrage detection.** Given a 5×5 FX rate matrix (in real or constructed data
   with planted arbitrages), identify all triangular arbitrage opportunities, compute the
   profit-per-unit, and output their direction (e.g. buy EUR with USD, buy JPY with EUR,
   close with JPY → USD).
3. **Garman-Kohlhagen FX option pricing.** Given a table of EUR/USD option contracts
   (spot, strike, T, domestic rate, foreign rate, σ), price them using the Garman-Kohlhagen
   formula (Black-Scholes extended to account for foreign risk-free rate), and verify put-call
   parity with q = r_foreign.

### Key concepts

- **Spot rate.** The current exchange rate for immediate delivery (typically settling 2 business
  days later in FX markets).
- **Forward rate.** An exchange rate agreed today for delivery at a future date.
- **Covered interest parity (CIP).** The no-arbitrage relationship: `F = S × exp((r_d − r_f) × T)`
  where F is the forward, S is the spot, r_d is the domestic rate, r_f is the foreign rate.
- **Triangular arbitrage.** Trading three currency pairs in a cycle to exploit inconsistencies;
  e.g. EUR/USD, USD/JPY, EUR/JPY should be consistent (their product ≈ 1).
- **Garman-Kohlhagen model.** The Black-Scholes formula adapted for FX options: the foreign
  risk-free rate r_f plays the role of the dividend yield q in the equity option formula.
- **Risk reversal (RR).** An FX vol convention that captures the difference in implied volatility
  between out-of-the-money calls and puts at the same delta (e.g. 25Δ); positive RR means calls
  are more expensive.
- **Butterfly (BF).** An FX vol convention that captures the "smile" — whether out-of-the-money
  options are collectively more expensive than at-the-money options.

### Financial invariants a grader must check

| Invariant | What to check | Why it must hold |
|---|---|---|
| No triangular arbitrage | `EURUSD × USDJPY / EURJPY ≈ 1` (within bid-ask) | A deviation means you can make a riskless profit by trading the triangle. |
| Covered interest parity | `F = S × exp((r_d − r_f) × T)` within tolerance | If violated, you could borrow in the low-rate currency, invest in the high-rate currency, and lock the FX exposure with a forward — a classic carry-and-forward arbitrage. |
| GK put-call parity | Same as BS put-call parity with q = r_f | Put-call parity is a model-independent no-arbitrage condition. |
| Carry sign correct | Long high-yield currency, short low-yield currency | The carry trade by definition earns the yield differential; a sign flip means the implementation is backwards. |
| FX delta sums to 1 for digital replication | The boundary conditions for a digital option | A digital call pays $1 if the rate exceeds a barrier; the delta of the digital must integrate to 1 at the barrier. |

### Typical difficulty and why

**Medium tasks** implement a forward curve or a Garman-Kohlhagen pricer with CIP check.
**Hard tasks** involve the full FX volatility surface in risk-reversal/butterfly quoting
conventions (converting from market quotes to a consistent implied-vol surface), dynamic delta
hedging, or multi-currency portfolio optimisation.

### Common mistakes

- Confusing which currency is the "price currency" vs. the "base currency" (EUR/USD = 1.08
  means 1 EUR = 1.08 USD; quoting it inverted flips all signs).
- Missing the `exp(−r_f × T)` in the Garman-Kohlhagen delta (it is `exp(−r_f × T) × N(d1)`,
  not just `N(d1)`).
- Getting the triangular arbitrage direction wrong (there are two directions for each triangle).

---

## 9. `nlp-on-finance`

### What this is (plain English)

**Financial NLP** uses language models and text-mining to extract structured signals from
unstructured financial documents — earnings call transcripts, SEC regulatory filings (10-K,
10-Q, 8-K), analyst reports, and news articles. The goal is to turn text into numbers that can be
used in quant models: e.g. a "sentiment score" for an earnings call might predict next-day stock
returns.

**Real-world scenario.** Your fund's analysts manually read 200 earnings call transcripts per
quarter, highlighting language that hints at management confidence or caution. You want to
automate this using FinBERT (a pre-trained language model fine-tuned on financial text) to
produce a sentiment score (−1 = very negative, +1 = very positive) for each transcript, then
run an event study to see whether positive surprises predict positive stock returns in the 3 days
after the call.

### Example task ideas

1. **10-K risk-factor extraction.** Given a set of SEC 10-K filings (in plain text), extract
   all text under the "Risk Factors" heading, split into individual numbered risks, and classify
   each into one of 10 risk categories (market risk, credit risk, regulatory risk, …). Output a
   CSV with one row per risk per company.
2. **Earnings call sentiment scoring.** Given a file of earnings call transcript segments
   (JSON with `company`, `quarter`, `text`, `speaker_type`), compute a sentiment score per
   segment using keyword scoring or a provided model. Output the scores and a management-vs-
   analyst aggregate.
3. **News-event study.** Given a CSV of company news events (date, company, headline) and
   a file of daily stock returns, align events to the corresponding stock's return window
   (−1, 0, +1, +2 days relative to event) and compute the mean abnormal return for each event
   type.

### Key concepts

- **Sentiment analysis.** Classifying the emotional tone of a piece of text as positive,
  negative, or neutral; in finance this often correlates with management confidence.
- **FinBERT.** A version of the BERT language model fine-tuned on financial text; better than
  general-purpose sentiment models for earnings call language.
- **Named Entity Recognition (NER).** Identifying and classifying entities in text (company
  names, people, dollar amounts, dates).
- **Event study.** A statistical analysis that estimates the "abnormal return" (return above
  what was expected) around a specific event (earnings announcement, M&A deal, regulatory action).
- **Abnormal return.** The stock return in excess of what a benchmark model (e.g. CAPM) would
  predict; positive abnormal returns around good news confirm the market reacts to the event.
- **SEC EDGAR.** The U.S. Securities and Exchange Commission's online database of public company
  filings; the primary source of structured financial text for NLP research.
- **Look-ahead bias (in NLP).** Using a document that was published *after* the date you are
  "predicting" — always check that the filing or transcript date precedes the return window.

### Financial invariants a grader must check

| Invariant | What to check | Why it must hold |
|---|---|---|
| Sentiment scores in declared range | All scores ∈ [−1, 1] (or [0, 1] depending on convention) | A score outside the declared range signals a normalisation bug or model output being interpreted incorrectly. |
| Event dates precede return window | `event_date < return_start_date` | Using data published after the date you are predicting is look-ahead bias. |
| Extracted figures within tolerance of source | Parsed dollar amounts match the source document ±1% | A parsing error that returns, e.g. thousands instead of millions would produce wildly wrong numbers. |
| Label vocabulary is closed | Classification labels drawn from the declared label set | A classifier that invents new categories (e.g. "cyber-risk-2" when only "cyber-risk" is declared) signals hallucination. |
| Named-entity counts non-negative integers | All counts ≥ 0 and are integers | You cannot extract a negative number of risk factors from a document. |

### Typical difficulty and why

**Medium tasks** parse a fixed small corpus with clear structure (e.g. well-formatted EDGAR
plain text) and produce a structured CSV.
**Hard tasks** require fine-tuning a language model on held-out financial documents with F1 or
precision/recall targets; or building a multi-document aggregation with entity resolution
(matching "Microsoft Corp.", "MSFT", and "Microsoft" to the same entity).

### Common mistakes

- Confusing the currency of reported figures (millions vs. billions; USD vs. EUR).
- Not stripping boilerplate text (forward-looking statement disclaimers are in nearly every
  earnings call and will dominate keyword counts if not filtered).
- Ignoring the speaker type — management's language differs from an analyst's Q&A questions; a
  combined sentiment score misses this.

---

## 10. `cross-domain`

### What this is (plain English)

**Cross-domain tasks** deliberately span two or more of the nine categories above. They test
whether an agent can integrate knowledge from different areas of quantitative finance — the kind
of integration a real quant does every day. For example: pricing a portfolio of credit derivatives
that also has FX exposure (combining credit + fx), or building a factor signal from earnings-call
NLP and then backtesting it properly (combining nlp-on-finance + factor-research + backtesting).

Because real finance problems rarely fall neatly into one box, cross-domain tasks are the
hardest in Track 1. A single-call language-model attempt is especially likely to fail here,
because solving the task requires maintaining coherent state across at least two separate
computation problems.

**Real-world scenario.** You run a multi-asset portfolio with European equity options (derivatives-
pricing), a bond ladder (fixed-income), and some CDS contracts (credit). Your risk manager asks
for a single consolidated report: the portfolio DV01, the option deltas, the CDS survival
probabilities, and the total CVA. You need to compute each component correctly and aggregate them
into one consistent output.

### Example task ideas

1. **Factor strategy on NLP signals with risk controls.** Given earnings-call sentiment scores and
   daily stock returns, build a momentum-enhanced sentiment signal, form a long-short portfolio
   using the signal, compute the annualised Sharpe and IC, and verify that the portfolio is
   dollar-neutral and market-beta-neutral. (Combines nlp-on-finance + factor-research.)
2. **FX-hedged credit portfolio.** Price a set of CDS contracts on European issuers, convert the
   USD-denominated protection legs to EUR using current FX forwards, and compute the net EUR
   exposure, DV01-equivalent, and CVA of the portfolio. (Combines credit + fx + fixed-income.)
3. **Delta-hedged bond option book.** Given a portfolio of interest-rate options (swaptions),
   compute the option delta with respect to the swap rate, the bond DV01 of the underlying swaps,
   and the total interest-rate sensitivity. Hedge both the delta and the DV01 simultaneously using
   a combination of government bonds and IR swaps. (Combines derivatives-pricing + fixed-income.)

### Key concepts

Each cross-domain task imports the key concepts from its constituent categories. See the
relevant sections above. The additional concept specific to cross-domain tasks is:

- **Risk aggregation.** Combining risk measures from different asset classes into a single
  coherent number — e.g. converting all sensitivities to a common risk factor (e.g. DV01 in
  USD equivalent) before summing.

### Financial invariants a grader must check

A cross-domain task must check **at least one invariant from each constituent category**.
The combined invariant set is the union of the applicable invariants from those categories.

| Category pairing | Minimum required checks |
|---|---|
| derivatives + fixed-income | Put-call parity OR delta bounds, AND DV01 consistency |
| credit + fx | Survival probability monotone, AND CIP for cross-currency swap |
| nlp + factor-research | Sentiment in declared range AND no look-ahead, AND dollar-neutral portfolio |
| Any pairing | At least two distinct financial invariants, one from each category |

There must be no "free pass" — a cross-domain task that only checks invariants from one category
does not qualify.

### Typical difficulty and why

Cross-domain tasks are **almost always hard**. They require:
- Correctly solving at least two sub-problems, each of which is a medium task on its own.
- Passing the invariant checks for both sub-problems.
- A consistent interface between the two parts (correct data types, units, and conventions).

A single-call language-model attempt is very unlikely to solve a cross-domain task, but a
well-designed agent that decomposes the problem into steps can succeed.

### Common mistakes

- Solving only one of the two constituent sub-problems and ignoring the other.
- Passing data between sub-problems in inconsistent units (e.g. outputting a yield in basis
  points from the fixed-income step and feeding it as a decimal to the derivatives step).
- Writing checks that test only the final aggregated number, not the intermediate invariants;
  this makes it easy for a wrong-for-the-right-reasons solution to pass.

---

## Quick reference table

| # | Category ID | Plain name | Key invariant to check | Typical difficulty |
|---|---|---|---|---|
| 1 | `derivatives-pricing` | Options & derivatives | Put-call parity, delta bounds | Medium |
| 2 | `fixed-income` | Bonds & rates | DV01 consistency, discount monotone | Medium |
| 3 | `credit` | Credit risk & CDS | Survival probability monotone | Medium |
| 4 | `factor-research` | Equity factors | Dollar-neutral, no look-ahead | Medium |
| 5 | `backtesting` | Strategy simulation | Self-financing, no look-ahead | Medium |
| 6 | `risk-management` | VaR & stress testing | CVaR ≥ VaR | Medium |
| 7 | `microstructure` | Order books & execution | Bid ≤ Ask, trajectory monotone | Medium/Hard |
| 8 | `fx` | Foreign exchange | Triangular no-arbitrage, CIP | Medium |
| 9 | `nlp-on-finance` | Text on finance | Scores in range, no look-ahead | Medium |
| 10 | `cross-domain` | Multi-category | Union of constituent invariants | Hard |
