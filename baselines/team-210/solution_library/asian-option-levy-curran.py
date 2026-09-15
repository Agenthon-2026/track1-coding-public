import json, os, sys
import numpy as np
import pandas as pd
from scipy.stats import norm

IN_CSV = r"C:\Users\Saifuddin\Documents\Agenthon-2026\track1-coding-public\units\t1-asian-option-levy-curran\environment\data\spy_daily.csv"
OUT = r"C:\Users\Saifuddin\Documents\agenthon-t1\benchmark_runs\all_87_units\t1-asian-option-levy-curran"
os.makedirs(OUT, exist_ok=True)

# Load data
df = pd.read_csv(IN_CSV)
print("CSV columns:", list(df.columns))
print("CSV shape:", df.shape)

# Compute log returns
closes = df['close'].values
rets = np.log(closes[1:] / closes[:-1])
n_prices = len(closes)
S0 = float(closes[-1])
ret_mean = float(np.mean(rets))
ret_std = float(np.std(rets, ddof=1))
sigma = ret_std * np.sqrt(252)
print(f"n_prices={n_prices}, S0={S0}, sigma={sigma}, ret_mean={ret_mean}, ret_std={ret_std}")

# Calibration
calib = {
    "n_prices": int(n_prices),
    "sigma": float(sigma),
    "S0": float(S0),
    "return_mean": float(ret_mean),
    "return_std": float(ret_std)
}
cal_path = os.path.join(OUT, "calibration.json")
with open(cal_path, 'w') as f:
    json.dump(calib, f, indent=4)
with open(cal_path) as f:
    json.load(f)
print("Wrote calibration.json")

r = 0.05
N_MC = 100000
rng = np.random.default_rng(42)

def bs_call(S, K, T, r, sigma):
    if T <= 0 or sigma <= 0:
        return max(S - K * np.exp(-r * T), 0.0)
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)

def geo_asian_exact(S0, K, T, r, sigma, n):
    # Discrete geometric Asian: effective vol
    # sigma_G^2 = sigma^2 * (1/n) * sum_{i=1}^{n} t_i / T  ... actually:
    # For discrete monitoring at t_i = i*T/n, i=1..n:
    # Var(log G) = sigma^2 * (1/n^2) * sum_{i=1}^n t_i
    # = sigma^2 * (1/n^2) * T/n * sum_{i=1}^n i = sigma^2 * T * (n+1)/(2n)
    # Effective: sigma_G = sigma * sqrt(T * (n+1)/(2n)) / sqrt(T) = sigma * sqrt((n+1)/(2n))
    # Then price = BS with S_eff = S0 * exp(-r*T/2) ... no.
    # Standard: G is lognormal with E[G] = S0 * exp(-r*T/2) * exp(sigma^2 * T * (n+1)/(4n