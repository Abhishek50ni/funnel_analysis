"""
Phase 4 — Data Cleaning & Preprocessing Pipeline
RetailRocket E-Commerce Dataset

Before running:
1. Download the dataset from Kaggle: https://www.kaggle.com/datasets/retailrocket/ecommerce-dataset
2. Unzip it into a folder called `data/` next to this script, so you have:
   data/events.csv
   data/item_properties_part1.csv
   data/item_properties_part2.csv
   data/category_tree.csv

Run with: python phase4_cleaning_pipeline.py
Output: data/clean_events.csv  (the single analysis-ready table for Phase 5+)
"""

import pandas as pd
import numpy as np

DATA_DIR = "data"
SESSION_GAP_MINUTES = 30
BOT_PERCENTILE_CUTOFF = 0.995  # flag top 0.5% most active visitors as bots

# ---------------------------------------------------------------------------
# Step 1: Load & fix data types
# ---------------------------------------------------------------------------
print("Step 1: Loading data...")

events = pd.read_csv(f"{DATA_DIR}/events.csv")
item_props1 = pd.read_csv(f"{DATA_DIR}/item_properties_part1.csv")
item_props2 = pd.read_csv(f"{DATA_DIR}/item_properties_part2.csv")
category_tree = pd.read_csv(f"{DATA_DIR}/category_tree.csv")

item_props = pd.concat([item_props1, item_props2], ignore_index=True)

# Convert timestamps (ms) to datetime
events["timestamp"] = pd.to_datetime(events["timestamp"], unit="ms")
item_props["timestamp"] = pd.to_datetime(item_props["timestamp"], unit="ms")

# Cast IDs as strings/categoricals — they are identifiers, not numbers to do math on
for col in ["visitorid", "itemid", "transactionid"]:
    events[col] = events[col].astype("string")

item_props["itemid"] = item_props["itemid"].astype("string")
category_tree["categoryid"] = category_tree["categoryid"].astype("string")
category_tree["parentid"] = category_tree["parentid"].astype("string")

print(f"  Raw events: {len(events):,} rows")
print(f"  Raw item_properties: {len(item_props):,} rows")

# ---------------------------------------------------------------------------
# Step 2: Deduplicate
# ---------------------------------------------------------------------------
print("Step 2: Removing duplicate events...")

before = len(events)
events = events.drop_duplicates(subset=["visitorid", "itemid", "event", "timestamp"])
print(f"  Removed {before - len(events):,} duplicate rows")

# ---------------------------------------------------------------------------
# Step 3: Handle missing values
# ---------------------------------------------------------------------------
print("Step 3: Handling missing values...")

# transactionid is expected to be null for view/addtocart — this is NOT missing data, leave as is.
# In item_properties, keep only the two human-readable properties: categoryid, available
item_props = item_props[item_props["property"].isin(["categoryid", "available"])].copy()
print(f"  Kept {len(item_props):,} item_property rows (categoryid + available only)")

# ---------------------------------------------------------------------------
# Step 4: Remove bot / abnormal traffic
# ---------------------------------------------------------------------------
print("Step 4: Filtering bot traffic...")

visitor_event_counts = events.groupby("visitorid").size()
bot_threshold = visitor_event_counts.quantile(BOT_PERCENTILE_CUTOFF)
bot_visitors = visitor_event_counts[visitor_event_counts > bot_threshold].index

before = len(events)
events = events[~events["visitorid"].isin(bot_visitors)]
print(f"  Bot event-count threshold: >{bot_threshold:.0f} events")
print(f"  Removed {len(bot_visitors):,} bot visitors, {before - len(events):,} events")

# ---------------------------------------------------------------------------
# Step 5: Fix event ordering
# ---------------------------------------------------------------------------
print("Step 5: Sorting events chronologically...")

events = events.sort_values(["visitorid", "timestamp"]).reset_index(drop=True)

# ---------------------------------------------------------------------------
# Step 6: Session generation (30-minute inactivity rule)
# ---------------------------------------------------------------------------
print("Step 6: Generating sessions...")

events["prev_timestamp"] = events.groupby("visitorid")["timestamp"].shift(1)
events["gap_minutes"] = (events["timestamp"] - events["prev_timestamp"]).dt.total_seconds() / 60
events["new_session"] = (events["gap_minutes"].isna()) | (events["gap_minutes"] > SESSION_GAP_MINUTES)
events["session_seq"] = events.groupby("visitorid")["new_session"].cumsum()
events["session_id"] = events["visitorid"].astype(str) + "_S" + events["session_seq"].astype(str)

events = events.drop(columns=["prev_timestamp", "gap_minutes", "new_session", "session_seq"])
print(f"  Created {events['session_id'].nunique():,} sessions across {events['visitorid'].nunique():,} visitors")

# ---------------------------------------------------------------------------
# Step 7: Pivot item_properties from long to wide (latest value per item)
# ---------------------------------------------------------------------------
print("Step 7: Pivoting item properties (latest value per item)...")

item_props_latest = (
    item_props.sort_values("timestamp")
    .groupby(["itemid", "property"], as_index=False)
    .last()
)

item_props_wide = item_props_latest.pivot(index="itemid", columns="property", values="value").reset_index()
item_props_wide.columns.name = None
item_props_wide = item_props_wide.rename(columns={"categoryid": "categoryid", "available": "available"})

# available: 1 = in stock, 0 = out of stock; keep as-is, fill missing as "unknown"
if "available" in item_props_wide.columns:
    item_props_wide["available"] = item_props_wide["available"].fillna("unknown")
if "categoryid" in item_props_wide.columns:
    item_props_wide["categoryid"] = item_props_wide["categoryid"].fillna("unknown")

print(f"  {len(item_props_wide):,} unique items with category/availability info")

# ---------------------------------------------------------------------------
# Step 8: Map events to funnel stages
# ---------------------------------------------------------------------------
print("Step 8: Mapping events to funnel stages...")

funnel_map = {"view": "Product View", "addtocart": "Add to Cart", "transaction": "Purchase"}
events["funnel_stage"] = events["event"].map(funnel_map)

# ---------------------------------------------------------------------------
# Step 9: Join everything into one analysis table
# ---------------------------------------------------------------------------
print("Step 9: Joining events + item properties + category tree...")

clean = events.merge(item_props_wide, on="itemid", how="left")
clean = clean.merge(category_tree, on="categoryid", how="left")

clean["categoryid"] = clean["categoryid"].fillna("unknown")
clean["available"] = clean["available"].fillna("unknown")

# ---------------------------------------------------------------------------
# Step 10: Sanity checks
# ---------------------------------------------------------------------------
print("Step 10: Running sanity checks...")

stage_counts = clean["funnel_stage"].value_counts()
print("  Funnel stage counts:")
print(stage_counts.to_string())

views = stage_counts.get("Product View", 0)
carts = stage_counts.get("Add to Cart", 0)
purchases = stage_counts.get("Purchase", 0)

if not (views >= carts >= purchases):
    print("  WARNING: funnel counts are not monotonically decreasing — investigate before proceeding")
else:
    print("  OK: funnel counts decrease monotonically (Views >= Cart >= Purchase)")

orphan_categories = (clean["categoryid"] == "unknown").sum()
print(f"  Rows with unknown category: {orphan_categories:,} ({orphan_categories/len(clean)*100:.1f}%)")

# ---------------------------------------------------------------------------
# Save output
# ---------------------------------------------------------------------------
output_path = f"{DATA_DIR}/clean_events.csv"
clean.to_csv(output_path, index=False)
print(f"\nDone. Clean analysis-ready table saved to: {output_path}")
print(f"Final row count: {len(clean):,}")