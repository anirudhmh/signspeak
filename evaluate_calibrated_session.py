#!/usr/bin/env python3
"""Evaluate a neutral-calibrated model on a separate session, using rest captures only for calibration."""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

from calibrated_dataset import calibrated_examples, load_recordings


def predict(features, model):
    means = model["standardization_mean"]
    scales = model["standardization_scale"]
    labels = model["labels"]
    centroids = model["centroids"]
    z = [(features[i] - means[i]) / scales[i] for i in range(len(features))]
    distances = {
        label: math.sqrt(sum((z[i] - centroids[label][i]) ** 2 for i in range(len(z))))
        for label in labels
    }
    return min(labels, key=lambda label: distances[label])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default="data/raw/session2.csv")
    parser.add_argument("--model", default="models/neutral_centroid_model.json")
    args = parser.parse_args()
    csv_path, model_path = Path(args.csv), Path(args.model)
    if not csv_path.exists():
        print(f"ERROR: session CSV not found: {csv_path}")
        return 2
    if not model_path.exists():
        print(f"ERROR: calibrated model not found: {model_path}")
        return 2
    try:
        model = json.loads(model_path.read_text(encoding="utf-8-sig"))
        if model.get("calibration_mode") != "subtract_session_neutral_median":
            raise ValueError("Model does not use the expected neutral calibration")
        records = load_recordings(csv_path)
        examples, baseline, calibration_ids = calibrated_examples(
            records, int(model["neutral_recordings_used"])
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}")
        return 2

    labels = list(model["labels"])
    unknown = sorted({str(row["label"]) for row in examples} - set(labels))
    if unknown:
        print("ERROR: Session has labels absent from model: " + ", ".join(unknown))
        return 2
    matrix = {actual: {predicted: 0 for predicted in labels} for actual in labels}
    counts = defaultdict(int)
    correct = 0
    for row in examples:
        actual = str(row["label"])
        predicted = predict(row["features"], model)
        matrix[actual][predicted] += 1
        counts[actual] += 1
        correct += actual == predicted

    print(f"Session CSV: {csv_path.resolve()}")
    print(f"Calibration recordings excluded from evaluation: {len(calibration_ids)}")
    print("Neutral baseline (raw counts): " + ", ".join(f"{value:.1f}" for value in baseline))
    print(f"Held-out session accuracy: {correct / len(examples):.3f} ({correct}/{len(examples)})")
    print("Test recordings by label:")
    for label in labels:
        print(f"  {label}: {counts[label]}")
    print("Per-class precision / recall / support:")
    for label in labels:
        tp = matrix[label][label]
        predicted_count = sum(matrix[actual][label] for actual in labels)
        support = sum(matrix[label].values())
        precision = tp / predicted_count if predicted_count else 0.0
        recall = tp / support if support else 0.0
        print(f"  {label}: precision={precision:.3f}, recall={recall:.3f}, support={support}")
    print("Confusion matrix (rows=actual, columns=predicted):")
    print("  actual\\pred " + " ".join(f"{label:>8}" for label in labels))
    for actual in labels:
        print(f"  {actual:>12} " + " ".join(f"{matrix[actual][label]:8d}" for label in labels))
    print("Calibration recordings were not used as scored test examples.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
