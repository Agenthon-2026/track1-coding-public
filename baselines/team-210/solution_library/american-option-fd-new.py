import json, os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

OUT = r"C:\Users\Saifuddin\Documents\agenthon-t1\benchmark_runs\all_87_units\t1-american-option-fd-new"
os.makedirs(OUT, exist_ok=True)

# Read manifest (required input)
with open(r"C:\Users\Saifuddin\Documents\Agenthon-2026\track1-coding-public\units\t1-american-option-fd-new\manifest.json") as f:
    manifest = json.load(f)

S0, K, r, q, sigma, T = 100.0, 100.0, 0.05, 0.0, 0.30, 1.0
dividends = [(0.25, 2.5), (0.75, 2.5)]

def price_option(option_type, NS, NT, divs, S0=100.0, K=100.0, r=0.05, q=0.0, sigma=0.30, T=1.0):
    """
    Crank-Nicolson FD with PSOR for American, simple CN for European.
    Returns (V0, V_grid, S_grid, t_grid, S_star_array)
    V_grid shape: (NT+1, NS+1)
    """
    Smax = 3.0 * K
    dS = Smax / NS
    dt = T / NT
    S = np.linspace(0, Smax, NS + 1)
    t = np.linspace(0, T, NT + 1)

    # Coefficients
    a = 0.5 * (sigma**2 * S**2 / dS**2 + r * S / dS)
    b = 1.0 + sigma**2 * S**2 / dS**2 - r * S
    c = 0.5 * (sigma**2 * S**2 / dS**2 - r * S / dS)
    # a[0]=0, c[NS]=0 handled by boundary conditions

    # Terminal payoff
    if option_type == 'put':
        V = np.maximum(K - S, 0.0)
    else:
        V = np.maximum(S - K, 0.0)

    V_grid = np.zeros((NT + 1, NS + 1))
    V_grid[NT] = V.copy()
    S_star = np.zeros(NT + 1)
    S_star[NT] = 0.0  # at maturity, no early exercise premium

    american = (option_type == 'put')  # American put; American call = European for no-div, but we handle both
    # Actually: American put and American call both need PSOR. European just CN.
    is_american = option_type in ('american_put', 'american_call')
    is_put = option_type in ('put', 'american_put')

    # Sort dividends by time descending (we go backward in time)
    divs_sorted = sorted(divs, key=lambda x: -x[0])

    for n in range(NT, 0, -1):
        # Check if we cross a dividend
        crossed_div = None
        for (td, D) in divs_sorted:
            if t[n-1] < td <= t[n]:
                crossed_div = (td, D)
                break

        # CN step