#!/usr/bin/env python3
"""Validate SignSpeak's labeled one-second sensor recordings using only stdlib."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

SENSOR_COLUMNS = [
    "flex_thumb", "flex_index", "flex_middle", "flex_ring", "flex_little",
    "ax_raw", "ay_raw", "az_raw", "gx_raw", "gy_raw", "gz_raw",
]
REQUIRED_COLUMNS = ["recording_id", "label", "sample_index", "t_ms", *SENSOR_COLUMNS]
EXPECTED_LABELS = {"rest", "hello", "ok", "peace", "sos", "good_luck"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default="data/raw/sensor_samples.csv",
                        help="path to collector CSV (default: data/raw/sensor_samples.csv)")
    parser.add_argument("--min-recordings", type=int, default=30,
                        help="minimum separate recordings expected per label (default: 30)")
    args = parser.parse_args()

    path = Path(args.csv)
    if not path.exists():
        print(f"ERROR: CSV file not found: {path}")
        return 2

    recordings: dict[str, dict[str, object]] = {}
    malformed_rows = 0
    total_rows = 0

    with path.open("r", newline="", encoding="utf-8-sig") as csv_file:
        reader = csv.DictReader(csv_file)
        missing = [column for column in REQUIRED_COLUMNS if column not in (reader.fieldnames or [])]
        if missing:
            print("ERROR: Missing required CSV columns: " + ", ".join(missing))
            print("Found header: " + ", ".join(reader.fieldnames or []))
            return 2

        for row in reader:
            total_rows += 1
            recording_id = (row.get("recording_id") or "").strip()
            label = (row.get("label") or "").strip()
            if not recording_id or not label:
                malformed_rows += 1
                continue
            try:
                int(row["sample_index"])
                int(row["t_ms"])
                for column in SENSOR_COLUMNS:
                    int(row[column])
            except (TypeError, ValueError):
                malformed_rows += 1
                continue

            if recording_id not in recordings:
                recordings[recording_id] = {"label": label, "count": 0}
            elif recordings[recording_id]["label"] != label:
                malformed_rows += 1
                continue
            recordings[recording_id]["count"] = int(recordings[recording_id]["count"]) + 1

    by_label: Counter[str] = Counter()
    incomplete: list[tuple[str, str, int]] = []
    for recording_id, info in recordings.items():
        label = str(info["label"])
        count = int(info["count"])
        by_label[label] += 1
        if count < 25:
            incomplete.append((recording_id, label, count))

    print(f"CSV: {path.resolve()}")
    print(f"Rows read: {total_rows}")
    print(f"Valid recordings: {len(recordings)}")
    print(f"Malformed rows: {malformed_rows}")
    print("Separate recordings by label:")
    if by_label:
        for label in sorted(by_label):
            count = by_label[label]
            status = "OK" if count >= args.min_recordings else f"NEED {args.min_recordings - count} MORE"
            print(f"  {label}: {count} ({status})")
    else:
        print("  none")

    missing_labels = sorted(EXPECTED_LABELS - set(by_label))
    if missing_labels:
        print("Missing expected labels: " + ", ".join(missing_labels))

    if incomplete:
        print("Recordings with fewer than 25 samples (likely interrupted):")
        for recording_id, label, count in incomplete:
            print(f"  {recording_id} [{label}]: {count} samples")
    else:
        print("Interrupted recordings (<25 samples): none")

    if malformed_rows or incomplete or missing_labels or any(n < args.min_recordings for n in by_label.values()):
        print("\nDataset check: NOT READY for the first model yet.")
        return 1

    print("\nDataset check: READY for the first baseline model.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

