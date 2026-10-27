#!/usr/bin/env python3
"""Train a neutral-calibrated nearest-centroid baseline using Python stdlib."""

from __future__ import annotations

import argparse
import json
import math
import random
import time
from collections import defaultdict
from pathlib import Path

from calibrated_dataset import CHANNELS, EXPECTED_LABELS, STAT_NAMES, calibrated_examples, load_recordings


def split_by_recording(examples, test_fraction: float, seed: int):
    by_label = defaultdict(list)
    for item in examples:
        by_label[str(item["label"])].append(item)
    missing = EXPECTED_LABELS - set(by_label)
    if missing:
        raise ValueError("Missing expected labels: " + ", ".join(sorted(missing)))
    rng = random.Random(seed)
    train, test = [], []
    for label, group in sorted(by_label.items()):
        if len(group) < 2:
            raise ValueError(f"Need at least two recordings for {label}")
        shuffled = list(group)
        rng.shuffle(shuffled)
        count = max(1, round(len(group) * test_fraction))
        test.extend(shuffled[:count])
        train.extend(shuffled[count:])
    return train, test, by_label


def fit_centroids(train):
    labels = sorted({str(row["label"]) for row in train})
    width = len(train[0]["features"])
    means = [sum(row["features"][i] for row in train) / len(train) for i in range(width)]
    scales = []
    for i in range(width):
        variance = sum((row["features"][i] - means[i]) ** 2 for row in train) / len(train)
        scale = math.sqrt(variance)
        scales.append(scale if scale > 1e-12 else 1.0)
    centroids = {}
    for label in labels:
        group = [row for row in train if row["label"] == label]
        centroids[label] = [
            sum((row["features"][i] - means[i]) / scales[i] for row in group) / len(group)
            for i in range(width)
        ]
    return labels, means, scales, centroids


def predict(features, labels, means, scales, centroids):
    z = [(features[i] - means[i]) / scales[i] for i in range(len(features))]
    distances = {
        label: math.sqrt(sum((z[i] - centroids[label][i]) ** 2 for i in range(len(z))))
        for label in labels
    }
    return min(labels, key=lambda label: distances[label])


def report(test, labels, means, scales, centroids):
    matrix = {actual: {predicted: 0 for predicted in labels} for actual in labels}
    predictions = []
    start = time.perf_counter()
    for row in test:
        predicted = predict(row["features"], labels, means, scales, centroids)
        actual = str(row["label"])
        matrix[actual][predicted] += 1
        predictions.append((actual, predicted))
    elapsed = time.perf_counter() - start
    correct = sum(actual == predicted for actual, predicted in predictions)
    print(f"Held-out recording accuracy: {correct / len(test):.3f} ({correct}/{len(test)})")
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
    print(f"Host inference timing: {elapsed * 1000 / max(1, len(test)):.3f} ms/recording (not ESP32 timing)")
    return correct / len(test)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default="data/raw/sensor_samples.csv")
    parser.add_argument("--neutral-recordings", type=int, default=2,
                        help="reserve this many first rest recordings for session calibration")
    parser.add_argument("--test-fraction", type=float, default=0.20)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--model-out", default="models/neutral_centroid_model.json")
    args = parser.parse_args()
    if args.neutral_recordings < 1:
        parser.error("--neutral-recordings must be at least 1")
    if not 0.05 <= args.test_fraction <= 0.5:
        parser.error("--test-fraction must be between 0.05 and 0.5")

    source_path = Path(args.csv)
    if not source_path.exists():
        print(f"ERROR: CSV file not found: {source_path}")
        return 2
    try:
        records = load_recordings(source_path)
        examples, baseline, calibration_ids = calibrated_examples(records, args.neutral_recordings)
        train, test, by_label = split_by_recording(examples, args.test_fraction, args.seed)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 2

    labels, means, scales, centroids = fit_centroids(train)
    print(f"Training CSV: {source_path.resolve()}")
    print(f"Reserved neutral calibration recordings: {len(calibration_ids)}")
    print(f"Training recordings: {len(train)}; held-out recordings: {len(test)}")
    print("Recordings per label after calibration reservation:")
    for label in sorted(by_label):
        print(f"  {label}: {len(by_label[label])}")
    print("Neutral baselines (raw counts; flex 5, accel 3, gyro 3):")
    print("  " + ", ".join(f"{value:.1f}" for value in baseline))
    accuracy = report(test, labels, means, scales, centroids)

    model = {
        "model_type": "nearest_centroid",
        "calibration_mode": "subtract_session_neutral_median",
        "neutral_label": "rest",
        "neutral_recordings_used": len(calibration_ids),
        "feature_channels": CHANNELS,
        "feature_statistics": STAT_NAMES,
        "feature_names": [f"{channel}_{stat}" for channel in CHANNELS for stat in STAT_NAMES],
        "labels": labels,
        "standardization_mean": means,
        "standardization_scale": scales,
        "centroids": centroids,
        "split_seed": args.seed,
        "test_fraction": args.test_fraction,
        "train_recording_count": len(train),
        "held_out_recording_count": len(test),
        "held_out_accuracy": accuracy,
        "note": "Neutral calibration is per wear session; validate on a later session before deployment.",
    }
    model_path = Path(args.model_out)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_text(json.dumps(model, indent=2), encoding="utf-8")
    print(f"Calibrated model saved: {model_path.resolve()} ({model_path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
