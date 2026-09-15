import json, os
import numpy as np
import pandas as pd

BASE = r"C:\Users\Saifuddin\Documents\Agenthon-2026\track1-coding-public\units\t1-alpha-hedge-strategy\environment\data"
OUT  = r"C:\Users\Saifuddin\Documents\agenthon-t1\benchmark_runs\all_87_units\t1-alpha-hedge-strategy"
os.makedirs(OUT, exist_ok=True)

with open(os.path.join(BASE, "params.json")) as f:
    P = json.load(f)

ret = pd.read_csv(os.path.join(BASE, "returns.csv"), parse_dates=["date"])
fac = pd.read_csv(os.path.join(BASE, "factors.csv"), parse_dates=["date"])

tickers = sorted([c for c in ret.columns if c != "date"])
R = ret.set_index("date")[tickers]
nan_count = int(R.isna().sum().sum())
R = R.ffill().bfill()

ann = P["annualization_factor"]
lb_a = P["lookback_alpha"]
lb_r = P["lookback_risk"]
top_n = P["long_top_n"]
bot_n = P["short_bottom_n"]
w_l = P["long_weight_per_stock"]
w_s = P["short_weight_per_stock"]
tc_bps = P["transaction_cost_bps"]
sig_start = P["signal_start_day"]
trade_start = P["trade_start_day"]
seed = P["seed"]
np.random.seed(seed)

dates = R.index
n = len(dates)

# rolling mean return over alpha lookback
roll_mean = R.rolling(lb_a).mean()

# signal: z-score cross-sectionally
signal = pd.DataFrame(index=dates, columns=tickers, dtype=float)
for i in range(n):
    if i < sig_start:
        continue
    row = roll_mean.iloc[i]
    if row.isna().any():
        continue
    mu = row.mean()
    sd = row.std(ddof=1)
    if sd == 0 or np.isnan(sd):
        continue
    signal.iloc[i] = (row - mu) / sd

# trading period
trade_dates = dates[trade_start:]
n_trade = len(trade_dates)

# monthly rebalance: first trading day of each calendar month
month_keys = trade_dates.to_period("M")
rebal_idx = []
prev = None
for i, mk in enumerate(month_keys):
    if mk != prev:
        rebal_idx.append(i)
        prev = mk
n_rebalances = len(rebal_idx)

# build strategy returns
strat_ret = pd.Series(0.0, index=trade_dates)
prev_w = pd.Series(0.0, index=tickers)

for ri, ti in enumerate(rebal_idx):
    d = trade_dates[ti]
    sig_row = signal.loc[d]
    if sig_row.isna().all():
        continue
    valid = sig_row.dropna()
    if len(valid) < top_n + bot_n:
        continue
    longs = valid.nlargest(top_n).index
    shorts = valid.nsmallest(bot_n).index
    w = pd.Series(0.0, index=tickers)
    w[longs] = w_l
    w[shorts] = -w_s
    # turnover
    turnover = (w - prev_w).abs().sum()
    cost = turnover * tc_bps * 1e-4
    # apply to first day of this month
    strat_ret.iloc[ti] -= cost
    prev_w =    # returns for days in this month
    end_ti = rebal_idx[ri + 1] if ri + 1 < len(rebal_idx) else n_trade
    for j in range(ti, end_ti):
        d2 = trade_dates[j]
        r = R.loc[d2, tickers]
        strat_ret.iloc[j] += float((w * r).sum())

# performance metrics
sr = strat_ret
ann_ret = float(sr.mean() * ann)
ann_vol = float(sr.std(ddof=1) * np.sqrt(ann))
sharpe = ann_ret / ann_vol if ann_vol > 0 else 0.0
cum = (1 + sr).cumprod()
peak = cum.cummax()
dd = (cum - peak) / peak
max_dd = float(-dd.min())

# factor regression on trading period
f = fac.set_index("date").loc[trade_dates, P["factor_names"]]
X = pd.concat([pd.Series(1.0, index=trade_dates), f], axis=1)
X_np = X.values
y_np = sr.values
beta, _, _, _ = np.linalg.lstsq(X_np, y_np, rcond=None)
alpha_daily = float(beta[0])
betas = {P["factor_names"][0]: float(beta[1]), P["factor_names"][1]: float(beta[2]), P["factor_names"][2]: float(beta[3])}
resid = y_np - X_np @ beta
te_ann = float(resid.std(ddof=1) * np.sqrt(ann))
ann_alpha = float(alpha_daily * ann)
ir = ann_alpha / te_ann if te_ann > 0 else 0.0
hit_rate = float((sr > 0).mean())

results = {
    "annualized_return": ann_ret,
    "annualized_volatility": ann_vol,
    "sharpe_ratio": sharpe,
    "max_drawdown": max_dd,
    "annualized_alpha": ann_alpha,
    "market_beta_residual": betas[P["factor_names"][0]],
    "n_rebalances": int(n_rebalances),
}
with open(os.path.join(OUT, "results.json"), "w") as f:
    json.dump(results, f, indent=2)

solution = {
    "intermediates": {
        "nan_count": {"value": int(nan_count)},
        "n_rebalances": {"value": int(n_rebalances)},
        "annualized_alpha": {"value": ann_alpha},
        "market_beta_residual": {"value": betas[P["factor_names"][0]]},
        "smb_beta_residual": {"value": betas[P["factor_names"][1]]},
        "hml_beta_residual": {"value": betas[P["factor_names"][2]]},
        "tracking_error_annual": {"value": te_ann},
        "information_ratio": {"value": ir},
        "hit_rate": {"value": hit_rate},
        "sharpe_ratio": {"value": sharpe},
    }
}
with open(os.path.join(OUT, "solution.json"), "w") as f:
    json.dump(solution, f, indent=2)

# verify
with open(os.path.join(OUT, "results.json")) as f:
    r2 = json.load(f)
with open(os.path.join(OUT, "solution.json")) as f:
    s2 = json.load(f)
assert r2["sharpe_ratio"] == s2["intermediates"]["sharpe_ratio"]["value"], "sharpe mismatch"
assert r2["annualized