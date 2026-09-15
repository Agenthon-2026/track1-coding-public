import json, os
import numpy as np
import pandas as pd

BASE = r"C:\Users\Saifuddin\Documents\Agenthon-2026\track1-coding-public\units\t1-binance-btc-participation-tca\environment\data"
OUT = r"C:\Users\Saifuddin\Documents\agenthon-t1\benchmark_runs\all_87_units\t1-binance-btc-participation-tca"
os.makedirs(OUT, exist_ok=True)

spec = json.load(open(os.path.join(BASE, "order_spec.json")))
rules = json.load(open(os.path.join(BASE, "tca_rules.json")))
quotes = pd.read_csv(os.path.join(BASE, "quotes.csv"))
trades = pd.read_csv(os.path.join(BASE, "trades.csv"))

start_ms = int(spec["start_time_ms"])
end_ms = int(spec["end_time_ms"])
bucket_ms = int(spec["bucket_ms"])
target_qty = float(spec["target_quantity"])
participation_cap = float(spec["participation_cap"])
max_child_qty = float(spec["max_child_quantity"])
realized_horizon_ms = int(spec["realized_horizon_ms"])
side = spec["side"]
symbol = spec["symbol"]

# Arrival quote: first quote at or after start_time_ms
q = quotes[quotes["transaction_time"] >= start_ms].sort_values("transaction_time")
arrival = q.iloc[0]
arrival_mid = (arrival["best_bid_price"] + arrival["best_ask_price"]) / 2.0
arrival_update_id = int(arrival["update_id"])
arrival_trans = int(arrival["transaction_time"])
arrival_event = int(arrival["event_time"])

# Future reference: first quote at or after end_time_ms + realized_horizon_ms
fut_target = end_ms + realized_horizon_ms
qf = quotes[quotes["transaction_time"] >= fut_target].sort_values("transaction_time")
future = qf.iloc[0]
future_mid = (future["best_bid_price"] + future["best_ask_price"]) / 2.0
future_update_id = int(future["update_id"])
future_trans = int(future["transaction_time"])
future_event = int(future["event_time"])

# Buckets
n_buckets = (end_ms - start_ms) // bucket_ms
bucket_starts = [start_ms + i * bucket_ms for i in range(n_buckets)]
bucket_ends = [start_ms + (i + 1) * bucket_ms for i in range(n_buckets)]

# Filter trades in window
trades_in = trades[(trades["transact_time"] >= start_ms) & (trades["transact_time"] < end_ms)].copy()
trades_in = trades_in.sort_values("transact_time").reset_index(drop=True)

# For each bucket, find eligible trades
# Use searchsorted for efficiency
tt = trades_in["transact_time"].values
rows = []
remaining = target_qty
executed_qty = 0.0
total_notional = 0.0
total_qty = 0.0
market_trade_count = 0
market_volume = 0.0
bucket_count_filled = 0
bucket_count_empty = 0
first_fill_trans = None
last_fill_trans = None

# Pre-sort quotes by transaction_time for searchsorted
q_sorted = quotes.sort_values("transaction_time").reset_index(drop=True)
q_times = q_sorted["transaction_time"].values

for i in range(n_buckets):
    bs = bucket_starts[i]
    be = bucket_ends[i]
    # Eligible trades: bs <= transact_time < be
    lo = np.searchsorted(tt, bs, side="left")
    hi =