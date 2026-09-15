
import pathlib
import numpy as np
import pandas as pd
from scipy.stats import norm

IN = pathlib.Path(r"C:\Users\Saifuddin\Documents\Agenthon-2026\track1-coding-public\units\t1-EXAMPLE-bs-greeks-pde")
OUT = pathlib.Path(r"C:\Users\Saifuddin\Documents\agenthon-t1\benchmark_runs\all_87_units\t1-EXAMPLE-bs-greeks-pde")
OUT.mkdir(parents=True, exist_ok=True)

opts = pd.read_parquet(IN / "environment/data/options.parquet")
S = opts["S"].to_numpy(float); K = opts["K"].to_numpy(float)
T = opts["T"].to_numpy(float); r = opts["r"].to_numpy(float)
v = opts["sigma"].to_numpy(float)
is_call = (opts["option_type"] == "call").to_numpy()

rt = np.sqrt(T); vrt = v * rt
d1 = (np.log(S / K) + (r + 0.5 * v ** 2) * T) / vrt
d2 = d1 - vrt
pdf = norm.pdf(d1); disc = np.exp(-r * T)

call = S * norm.cdf(d1) - K * disc * norm.cdf(d2)
put = K * disc * norm.cdf(-d2) - S * norm.cdf(-d1)
price = np.where(is_call, call, put)
delta = np.where(is_call, norm.cdf(d1), norm.cdf(d1) - 1.0)
gamma = pdf / (S * vrt)
vega = S * pdf * rt
decay = -S * pdf * v / (2.0 * rt)
theta = np.where(is_call,
                 decay - r * K * disc * norm.cdf(d2),
                 decay + r * K * disc * norm.cdf(-d2)) / 365.0

pd.DataFrame({
    "option_id": opts["option_id"].to_numpy(),
    "price": price, "delta": delta, "gamma": gamma,
    "vega": vega, "theta": theta,
}).to_parquet(OUT / "results.parquet", index=False)
print("wrote results.parquet", len(opts), "rows")
