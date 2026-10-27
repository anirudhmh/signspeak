"""Shared pure-Python preprocessing for neutral-calibrated SignSpeak sessions."""

from __future__ import annotations

import csv
import math
import statistics
from pathlib import Path

CHANNELS = [
    "flex_thumb", "flex_index", "flex_middle", "flex_ring", "flex_little",
    "ax_raw", "ay_raw", "az_raw", "gx_raw", "gy_raw", "gz_raw",
]
STAT_NAMES = ["mean", "min", "max", "std", "median"]
EXPECTED_LABELS = {"rest", "hello", "ok", "peace", "sos", "good_luck"}


def load_recordings(path: Path) -> dict[str, dict[str, object]]:
    records: dict[str, dict[str, object]] = {}
    with path.open("r", newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        required = {"recording_id", "label", *CHANNELS}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError("Missing CSV columns: " + ", ".join(sorted(missing)))
        for line_number, row in enumerate(reader, start=2):
            recording_id = (row.get("recording_id") or "").strip()
            label = (row.get("label") or "").strip()
            if not recording_id or not label:
                raise ValueError(f"Missing recording_id or label on line {line_number}")
            try:
                values = [float(row[name]) for name in CHANNELS]
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid sensor value on line {line_number}") from exc
            if recording_id not in records:
                records[recording_id] = {"label": label, "channels": [[] for _ in CHANNELS]}
            record = records[recording_id]
            if record["label"] != label:
                raise ValueError(f"Recording {recording_id} has inconsistent labels")
            for index, value in enumerate(values):
                record["channels"][index].append(value)
    return records


def features(channels: list[list[float]]) -> list[float]:
    output: list[float] = []
    for values in channels:
        if not values:
            raise ValueError("Empty sensor channel")
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        stats = [mean, min(values), max(values), math.sqrt(variance), float(statistics.median(values))]
        output.extend(stats)
    return output


def calibrated_examples(records: dict[str, dict[str, object]], neutral_recording_count: int):
    rest_ids = sorted(record_id for record_id, item in records.items() if item["label"] == "rest")
    if len(rest_ids) <= neutral_recording_count:
        raise ValueError(
            f"Need more than {neutral_recording_count} rest recordings; found {len(rest_ids)}"
        )
    calibration_ids = set(rest_ids[:neutral_recording_count])
    baseline_values = [[] for _ in CHANNELS]
    for record_id in calibration_ids:
        channel_lists = records[record_id]["channels"]
        for index, values in enumerate(channel_lists):
            baseline_values[index].extend(values)
    baseline = [float(statistics.median(values)) for values in baseline_values]

    examples = []
    for record_id, record in sorted(records.items()):
        if record_id in calibration_ids:
            continue
        channel_lists = record["channels"]
        sample_count = len(channel_lists[0])
        if sample_count < 25:
            raise ValueError(f"Recording {record_id} has only {sample_count} samples")
        corrected = [
            [value - baseline[index] for value in values]
            for index, values in enumerate(channel_lists)
        ]
        examples.append({
            "recording_id": record_id,
            "label": str(record["label"]),
            "features": features(corrected),
            "sample_count": sample_count,
        })
    return examples, baseline, sorted(calibration_ids)
