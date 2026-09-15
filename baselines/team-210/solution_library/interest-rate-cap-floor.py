import json, os, math
import numpy as np
from scipy.stats import norm

IN = r"C:\Users\Saifuddin\Documents\Agenthon-2026\track1-coding-public\units\t1-interest-rate-cap-floor\environment\data\params.json"
OUTDIR = r"C:\Users\Saifuddin\Documents\agenthon-t1\benchmark_runs\all_87_units\t1-interest-rate-cap-floor"
os.makedirs(OUTDIR, exist_ok=True)

with open(IN) as f:
    p = json.load(f)

fr = np.array(p["forward_rates"], dtype=float)
df = np.array(p["discount_factors"], dtype=float)
vol = float(p["vol"]); K = float(p["strike"]); N = float(p["notional"]); pl = float(p["period_length"])
n = len(fr)
assert len(df) == n

caplets = np.zeros(n); floorlets = np.zeros(n)
for i in range(n):
    T = i * pl
    if T == 0:
        caplets[i] = N * pl * df[i] * max(fr[i] - K, 0.0)
        floorlets[i] = N * pl * df[i] * max(K - fr[i], 0.0)
    else:
        d1 = (math.log(fr[i]/K) + 0.5*vol*vol*T) / (vol*math.sqrt(T))
        d2 = d1 - vol*math.sqrt(T)
        caplets[i] = N * pl * df[i] * (fr[i]*norm.cdf(d1) - K*norm.cdf(d2))
        floorlets[i] = N * pl * df[i] * (K*norm.cdf(-d2) - fr[i]*norm.cdf(-d1))

cap_price = float(np.sum(caplets)); floor_price = float(np.sum(floorlets))
swap_value = float(N * pl * np.sum(df * (fr - K)))
parity = cap_price - floor_price - swap_value

res = {
    "cap_price": round(cap_price, 2),
    "floor_price": round(floor_price, 2),
    "caplets": [round(float(x), 4) for x in caplets],
    "floorlets": [round(float(x), 4) for x in floorlets],
    "swap_value": round(swap_value, 2),
    "put_call_parity_error": round(parity, 6),
}
out = os.path.join(OUTDIR, "results.json")
with open(out, "w") as f:
    json.dump(res, f, indent=2)

with open(out) as f:
    r = json.load(f)
assert len(r["caplets"]) == n and len(r["floorlets"]) == n
assert abs(r["cap_price"] - round(sum(r["caplets"]),2)) < 0.02
assert abs(r["floor_price"] - round(sum(r["floorlets"]),2)) < 0.02
assert abs(r["put_call_parity_error"]) < 1e-3, "put-call parity failed"
print("OK", r["cap_price"], r["floor_price"], r["put_call_parity_error"])