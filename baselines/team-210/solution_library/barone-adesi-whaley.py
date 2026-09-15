import json, os, math
import numpy as np
import pandas as pd
from scipy.stats import norm
from scipy.optimize import brentq

IN = r"C:\Users\Saifuddin\Documents\Agenthon-2026\track1-coding-public\units\t1-barone-adesi-whaley"
OUT = r"C:\Users\Saifuddin\Documents\agenthon-t1\benchmark_runs\all_87_units\t1-barone-adesi-whaley"
os.makedirs(OUT, exist_ok=True)

# ---------- Step 1: calibration ----------
df = pd.read_csv(os.path.join(IN, "environment", "data", "spy_daily.csv"))
S0 = float(df["close"].iloc[-1])
lr = np.log(df["close"].values[1:] / df["close"].values[:-1])
sigma = float(np.std(lr, ddof=1) * np.sqrt(252))
n_returns = int(len(lr))
r, D = 0.05, 0.013

calib = {"S0": S0, "sigma": sigma, "r": r, "D": D, "n_returns": n_returns}
with open(os.path.join(OUT, "calibration.json"), "w") as f:
    json.dump(calib, f, indent=4)
with open(os.path.join(OUT, "calibration.json")) as f:
    json.load(f)

# ---------- Black-Scholes ----------
def bs_call(S, K, T, r, D, sig):
    if T <= 0:
        return max(S - K, 0.0)
    d1 = (math.log(S / K) + (r - D + 0.5 * sig * sig) * T) / (sig * math.sqrt(T))
    d2 = d1 - sig * math.sqrt(T)
    return S * math.exp(-D * T) * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)

def bs_put(S, K, T, r, D, sig):
    if T <= 0:
        return max(K - S, 0.0)
    d1 = (math.log(S / K) + (r - D + 0.5 * sig * sig) * T) / (sig * math.sqrt(T))
    d2 = d1 - sig * math.sqrt(T)
    return K * math.exp(-r * T) * norm.cdf(-d2) - S * math.exp(-D * T) * norm.cdf(-d1)

# ---------- BAW ----------
def baw_call(S, K, T, r, D, sig):
    if T <= 0:
        return max(S - K, 0.0)
    if D <= 0:
        return bs_call(S, K, T, r, D, sig)
    m1 = (r - D) / (0.5 * sig * sig)
    m2 = m1 - 2 * r / (sig * sig)
    A1 = (1 + math.exp(-r * T)) ** m1
    A2 = (1 + math.exp(-r * T)) ** m2
    def f(Ss):
        if Ss <= 0:
            return -1.0
        C = bs_call(Ss, K, T, r, D, sig)
        d1 = (math.log(Ss / K) + (r - D + 0.5 * sig * sig) * T) / (sig *