"""
Build the per-component survival training tables from the REAL v11 dataset.

Unlike the 2rd-model generator (which *synthesised* failure times), this reads
the actual fleet panel and derives survival targets from the dataset's own
forward-looking columns:

    duration_days = days_until_next_maintenance
    event(comp)   = 1 if next_service_type == comp's service else 0 (censored)

Each vehicle contributes ~70 monthly snapshots; every snapshot is a valid
"from this state, how long until this component needs service?" observation,
which is exactly the single-reading inference the production app performs.

Split is BY VEHICLE (not by row) so no vehicle appears in both train and test.

Writes:
    data/survival_snapshots_train.csv
    data/survival_snapshots_test.csv

Usage:
    python build_survival_dataset.py
    python build_survival_dataset.py --test-frac 0.2 --seed 42
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

import common as C


def load_snapshots(dataset_path) -> pd.DataFrame:
    df = pd.read_csv(dataset_path, usecols=C.SNAPSHOT_COLS)
    # Basic hygiene: numeric coercion + fill, keep categoricals as strings.
    for col in C.SHARED_NUMERIC_COLS + C.ALL_HEALTH_COLS + ["days_until_next_maintenance"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df[C.SHARED_NUMERIC_COLS + C.ALL_HEALTH_COLS] = (
        df[C.SHARED_NUMERIC_COLS + C.ALL_HEALTH_COLS].fillna(0.0)
    )
    for col in C.CATEGORICAL_COLS + ["next_service_type"]:
        df[col] = df[col].astype(str).fillna("__missing__")
    return df


def split_by_vehicle(df: pd.DataFrame, test_frac: float, seed: int):
    rng = np.random.default_rng(seed)
    vids = df["vehicle_id"].unique().copy()
    rng.shuffle(vids)
    n_test = int(len(vids) * test_frac)
    test_ids = set(vids[:n_test])
    train = df[~df["vehicle_id"].isin(test_ids)].reset_index(drop=True)
    test  = df[ df["vehicle_id"].isin(test_ids)].reset_index(drop=True)
    return train, test


def summarise(df: pd.DataFrame, name: str) -> None:
    print(f"\n--- {name}: {len(df):,} snapshots | {df['vehicle_id'].nunique():,} vehicles ---")
    print(f"{'component':<11s} {'events':>8s} {'event_rate':>11s} "
          f"{'med_dur_evt':>12s} {'med_dur_cens':>13s}")
    for comp in C.COMPONENTS:
        dur, evt = C.derive_target(df, comp)
        rate = evt.mean()
        med_e = dur[evt == 1].median() if evt.sum() else float("nan")
        med_c = dur[evt == 0].median()
        print(f"{comp:<11s} {int(evt.sum()):>8d} {rate:>10.2%} "
              f"{med_e:>11.1f}d {med_c:>12.1f}d")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", default=str(C.DATASET_PATH))
    p.add_argument("--test-frac", type=float, default=0.20)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    C.DATA_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Reading v11 dataset:\n  {args.dataset}")
    df = load_snapshots(args.dataset)
    print(f"Loaded {len(df):,} snapshots across {df['vehicle_id'].nunique():,} vehicles.")

    train, test = split_by_vehicle(df, args.test_frac, args.seed)
    train.to_csv(C.TRAIN_CSV, index=False)
    test.to_csv(C.TEST_CSV, index=False)

    summarise(train, "TRAIN")
    summarise(test, "TEST")

    print(f"\nWrote: {C.TRAIN_CSV}  ({len(train):,} rows)")
    print(f"Wrote: {C.TEST_CSV}   ({len(test):,} rows)")


if __name__ == "__main__":
    main()
