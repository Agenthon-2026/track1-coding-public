import os, json, re
import numpy as np
import pandas as pd

DATA = r"C:\Users\Saifuddin\Documents\Agenthon-2026\track1-coding-public\units\t1-13f-amendment-aware-crowding\environment\data"
OUT  = r"C:\Users\Saifuddin\Documents\agenthon-t1\benchmark_runs\all_87_units\t1-13f-amendment-aware-crowding"
os.makedirs(OUT, exist_ok=True)

# ---- read inputs ----
sub  = pd.read_csv(f"{DATA}/SUBMISSION.tsv", sep="\t", dtype=str)
cov  = pd.read_csv(f"{DATA}/COVERPAGE.tsv", sep="\t", dtype=str)
summ = pd.read_csv(f"{DATA}/SUMMARYPAGE.tsv", sep="\t", dtype=str)
info = pd.read_csv(f"{DATA}/INFOTABLE.tsv", sep="\t", dtype=str)
tm   = pd.read_csv(f"{DATA}/target_managers.csv", dtype=str)
tp   = pd.read_csv(f"{DATA}/target_periods.csv", dtype=str)

# normalise
for df in (sub, cov, summ, info):
    for c in df.columns:
        df[c] = df[c].fillna("").astype(str).str.strip()

# ---- target universe ----
tm["manager_order"] = range(1, len(tm)+1)
tp["period_order"]  = range(1, len(tp)+1)
tp["period_end"]    = tp["period_end"].str.strip()
tm["CIK"]           = tm["CIK"].str.strip()

# ---- filter eligible filings ----
# 13F-HR and 13F-HR/A with REPORTTYPE == '13F HOLDINGS REPORT'
sub["FORMTYPE"] = sub["FORMTYPE"].str.upper()
cov["REPORTTYPE"] = cov["REPORTTYPE"].str.upper()

# join submission + coverpage on accession
sub_cov = sub.merge(cov, on="ACCESSION_NUMBER", how="inner", suffixes=("_sub","_cov"))
eligible = sub_cov[
    (sub_cov["FORMTYPE"].isin(["13F-HR","13F-HR/A"])) &
    (sub_cov["REPORTTYPE"] == "13F HOLDINGS REPORT")
].copy()

# target CIKs
target_ciks = set(tm["CIK"])
eligible = eligible[eligible["CIK"].isin(target_ciks)]

# parse dates
def parse_date(s):
    s = str(s).strip()
    for fmt in ("%d-%b-%Y","%Y-%m-%d","%m/%d/%Y"):
        try: return pd.Timestamp(pd.to_datetime(s, format=fmt))
        except: pass
    try: return pd.Timestamp(pd.to_datetime(s))
    except: return pd.NaT

eligible["FILING_DATE_ts"] = eligible["FILING_DATE"].apply(parse_date)
eligible["DATEREPORTED_ts"] = eligible["DATEREPORTED"].apply(parse_date)
eligible["AMENDMENTNO_f"] = pd.to_numeric(eligible["AMENDMENTNO"], errors="coerce")
eligible["ISAMENDMENT_f"] = eligible["ISAMENDMENT"].str.upper().isin(["Y","YES","TRUE"])

# ---- summary page per accession ----
summ["VALUE"] = pd.to_numeric(summ["VALUE"], errors="coerce").fillna(0)
summ["SSHPRNAMT"] = pd.to_numeric(summ["SSHPRNAMT"], errors="coerce").fillna(0)
summ_agg = summ.groupby("ACCE_["ACCESSION_NUMBER"].agg(entry_total="count", value_total="sum").reset_index()
eligible = eligible.merge(summ_agg, on="ACCESSION_NUMBER", how="left")
eligible["summarypage_entry_total"] = eligible["entry_total"].fillna(0).astype(int)
eligible["summarypage_value_total"] = eligible["value_total"].fillna(0)

# ---- info table per accession ----
info["VALUE"] = pd.to_numeric(info["VALUE"], errors="coerce").fillna(0)
info["SSHPRNAMT"] = pd.to_numeric(info["SSHPRNAMT"], errors="coerce").fillna(0)
info_agg = info.groupby("ACCESSION_NUMBER").agg(rows_in_filing=("CUSIP","count"), value_total_in_filing=("VALUE","sum")).reset_index()
eligible = eligible.merge(info_agg, on="ACCESSION_NUMBER", how="left")
eligible["rows_in_filing"] = eligible["rows_in_filing"].fillna(0).astype(int)
eligible["value_total_in_filing"] = eligible["value_total_in_filing"].fillna(0)
eligible["summarypage_row_diff"] = eligible["rows_in_filing"] - eligible["summarypage_entry_total"]
eligible["summarypage_value_diff"] = eligible["value_total_in_filing"] - eligible["summarypage_value_total"]

# ---- resolve effective filing per (CIK, period_end) ----
# For each (CIK, period_end):
#   - initial filing (ISAMENDMENT != Y)
#   - amendments sorted by AMENDMENTNO
#   - RESTATEMENT: replaces the entire book
#   - NEW HOLDINGS: appends to the book
#   - Other amendment types: treat as replace (restatement-like)

# Map period_end from DATEREPORTED
eligible["period_end"] = eligible["DATEREPORTED"].apply(lambda s: str(s).strip())

# Build target period lookup
tp_map = tp.set_index("period_end")["period_order"].to_dict()
eligible["period_order"] = eligible["period_end"].map(tp_map)
eligible = eligible[eligible["period_order"].notna()].copy()
eligible["period_order"] = eligible["period_order"].astype(int)

# manager lookup
tm_map = tm.set_index("CIK")[["manager_order","manager_label"]].to_dict("index")
eligible["manager_order"] = eligible["CIK"].map(lambda c: tm_map[c]["manager_order"])
eligible["manager_label"] = eligible["CIK"].map(lambda c: tm_map[c]["manager_label"])

# Sort for resolution
eligible = eligible.sort_values(["CIK","period_end","FILING_DATE_ts","AMENDMENTNO_f"], na_position="last").reset_index(drop=True)

filing_rows = []
effective_books = {}  # (CIK, period_end) -> list of accession numbers in order

for (cik, pe), grp in eligible.groupby(["CIK","period_end"]):
    grp = grp.sort_values(["FILING_DATE_ts","AMENDMENTNO_f"], na_position="last")
    # Separate initial and amendments
    initials = grp[~grp["ISAMENDMENT_f"]]
    amends   = grp[grp["ISAMENDMENT_f"]].sort_values("AMENDMENTNO_f")
    
    applied = []
    # Initial filing
    for _, r in initials.iterrows():
        applied.append((r, "replace_initial"))
    # Amendments
    for _, r in amends.iterrows():
        atype = str(r["AMENDMENTTYPE"]).strip().upper()
        if "NEW HOLDINGS" in atype:
            action = "append