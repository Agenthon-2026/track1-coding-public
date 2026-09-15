import json, os, sys
import numpy as np
import pandas as pd

DATA = r"C:\Users\Saifuddin\Documents\Agenthon-2026\track1-coding-public\units\t1-residual-momentum\environment\data\stock_chars.pqt"
OUT  = r"C:\Users\Saifuddin\Documents\agenthon-t1\benchmark_runs\all_87_units\t1-residual-momentum"
os.makedirs(OUT, exist_ok=True)

df = pd.read_parquet(DATA)
n_input_rows = int(len(df))
print("cols:", list(df.columns))
print("dtypes:", df.dtypes.to_dict())
print("shape:", df.shape)

# Identify date column
date_col = None
for c in df.columns:
    if 'date' in c.lower():
        date_col = c
        break
if date_col is None:
    # try first column
    date_col = df.columns[0]
print("date_col:", date_col)

df['date'] = pd.to_datetime(df[date_col])
df = df.sort_values(['date', df.columns[1]]).reset_index(drop=True)

CONTROLS = ['rvol_21d','ivol_capm_21d','ivol_capm_252d','ivol_ff3_21d','ivol_hxz4_21d',
            'beta_60m','beta_dimson_21d','betabab_1260d','betadown_252d','corr_1260d',
            'rskew_21d','coskew_21d','iskew_capm_21d','iskew_ff3_21d','iskew_hxz4_21d']
RAW = ['ret_12_7','ret_6_1']
RES = ['resff3_12_1','resff3_6_1']
TARGET = 'ret_lead1m'
ALL_SIGNALS = RAW + RES

# Standardize cross-sectionally (population std, ddof=0)
def zscore_cross(df, cols):
    for c in cols:
        if c not in df.columns:
            print(f"WARNING: column {c} not found, skipping")
            continue
        m = df[c].mean()
        s = df[c].std(ddof=0)
        if s == 0 or np.isnan(s):
            df[c] = 0.0
        else:
            df[c] = (df[c] - m) / s
    return df

# Group by date
dates = sorted(df['date'].unique())
print("n dates:", len(dates))

# Build per-date frames
date_frames = {}
for d in dates:
    sub = df[df['date'] == d].copy()
    date_frames[d] = sub

# Standardize each date
for d in dates:
    date_frames[d] = zscore_cross(date_frames[d], CONTROLS + ALL_SIGNALS + [TARGET])

# Determine OOS start: after 120th calendar month
# "expanding-window OOS forecasts starting after the 120th calendar month"
# The 120th calendar month means the 120th unique month in the data
unique_months = sorted(set(d.to_period('M') for d in dates))
print("n unique months:", len(unique_months))
if len(unique_months) > 120:
    oos_start_month = unique_months[120]  # 0-indexed, so 121st month