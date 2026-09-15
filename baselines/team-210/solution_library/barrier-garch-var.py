import json, os
import numpy as np
import pandas as pd
from scipy.stats import norm
from scipy.optimize import minimize

DATA = r"C:\Users\Saifuddin\Documents\Agenthon-2026\track1-coding-public\units\t1-barrier-garch-var\environment\data"
OUT  = r"C:\Users\Saifuddin\Documents\agenthon-t1\benchmark_runs\all_87_units\t1-barrier-garch-var"
os.makedirs(OUT, exist_ok=True)

with open(os.path.join(DATA, "params.json")) as f:
    P = json.load(f)
df = pd.read_csv(os.path.join(DATA, "returns.csv"))
r = df["log_return"].values.astype(float)
n = len(r)
assert n == 750, f"expected 750 rows, got {n}"

S0, K, B = P["S0"], P["K"], P["B"]
rate, T, conf, nC = P["r"], P["T"], P["confidence_level"], P["n_contracts"]
fd_dS_pct, fd_dsigma = P["fd_dS_pct"], P["fd_dsigma"]

# ---- GARCH(1,1) fit via MLE (no arch library) ----
def garch_loglik(params, r):
    omega, alpha, beta = params
    if omega <= 0 or alpha < 0 or beta < 0 or alpha + beta >= 1:
        return -1e10
    n = len(r)
    h = np.empty(n)
    h[0] = np.var(r)
    for t in range(1, n):
        h[t] = omega + alpha * r[t-1]**2 + beta * h[t-1]
        if h[t] <= 0:
            return -1e10
    ll = -0.5 * np.sum(np.log(2*np.pi) + np.log(h) + r**2 / h)
    return ll

def neg_ll(params):
    return -garch_loglik(params, r)

x0 = [np.var(r)*0.05, 0.1, 0.85]
res = minimize(neg_ll, x0, method='Nelder-Mead',
               options={'maxiter': 100000, 'xatol': 1e-12, 'fatol': 1e-12})
omega, alpha, beta = res.x
persistence = alpha + beta
long_run_var = omega / (1.0 - persistence)

# conditional variance series
h = np.empty(n)
h[0] = np.var(r)
for t in range(1, n):
    h[t] = omega + alpha * r[t-1]**2 + beta * h[t-1]
garch_var_1d = float(h[-1])
garch_vol = float(np.sqrt(garch_var_1d * 252.0))

# ---- Reiner-Rubinstein down-and-out call ----
def rr_dco(S, K, B, r, T, sigma):
    if sigma <= 0 or T <= 0:
        return max(S - K * np.exp(-r * T), 0.0)
    if B >= S:
        return 0.0
    sqT = np.sqrt(T)
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * sqT)
    d2 = d1 -