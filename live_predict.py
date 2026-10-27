#!/usr/bin/env python3
"""Live SignSpeak host classifier: calibrate in rest, classify 1-second windows, send label to ESP32 OLED."""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, deque
from pathlib import Path

import serial

CHANNELS = [
    "flex_thumb", "flex_index", "flex_middle", "flex_ring", "flex_little",
    "ax_raw", "ay_raw", "az_raw", "gx_raw", "gy_raw", "gz_raw",
]
STAT_NAMES = ["mean", "min", "max", "std", "median"]


def parse_row(line: str):
    parts = line.strip().split(",")
    if len(parts) != 12:
        return None
    try:
        values = [int(value.strip()) for value in parts]
    except ValueError:
        return None
    return values[1:]


def make_features(rows, baseline):
    result = []
    for channel in range(11):
        values = [row[channel] - baseline[channel] for row in rows]
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        result.extend([mean, min(values), max(values), math.sqrt(variance), float(statistics.median(values))])
    return result


def rank_predictions(features, model):
    means = model["standardization_mean"]
    scales = model["standardization_scale"]
    labels = model["labels"]
    centers = model["centroids"]
    z = [(features[i] - means[i]) / scales[i] for i in range(len(features))]
    distances = {
        label: math.sqrt(sum((z[i] - centers[label][i]) ** 2 for i in range(len(z))))
        for label in labels
    }
    return sorted(distances.items(), key=lambda item: item[1])


def read_n_valid(board, count, timeout_seconds=20):
    samples = []
    deadline = time.monotonic() + timeout_seconds
    while len(samples) < count and time.monotonic() < deadline:
        raw = board.readline().decode("ascii", errors="replace")
        row = parse_row(raw)
        if row is not None:
            samples.append(row)
    if len(samples) < count:
        raise RuntimeError(f"Received only {len(samples)} valid sensor rows; expected {count}. Check the serial stream.")
    return samples


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM10")
    parser.add_argument("--model", default="models/session6_good_luck_neutral_centroid_model.json")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--calibration-samples", type=int, default=100,
                        help="keep the hand neutral for this many samples (default: 100, about 2 seconds)")
    parser.add_argument("--window-samples", type=int, default=50,
                        help="samples per prediction (default: 50, about 1 second)")
    parser.add_argument("--sos-confirm-windows", type=int, default=3,
                        help="consecutive SOS windows required before alert (default: 3)")
    parser.add_argument("--enable-ntfy", action="store_true",
                        help="send real ntfy notifications after confirmed SOS; off by default")
    args = parser.parse_args()
    ntfy_topic = os.environ.get("NTFY_TOPIC", "").strip()
    if args.enable_ntfy and not ntfy_topic:
        raise SystemExit("NTFY_TOPIC is not set. In PowerShell run: $env:NTFY_TOPIC = $topic")

    model_path = Path(args.model)
    if not model_path.exists():
        raise SystemExit(f"Model not found: {model_path}")
    model = json.loads(model_path.read_text(encoding="utf-8-sig"))
    if model.get("calibration_mode") != "subtract_session_neutral_median":
        raise SystemExit("This model does not use the supported neutral calibration mode.")

    print(f"Model: {model_path}")
    print("Close Arduino Serial Monitor. Keep your hand in REST position, then press Enter to connect and calibrate.")
    input()

    try:
        board = serial.Serial(args.port, args.baud, timeout=1)
    except serial.SerialException as exc:
        raise SystemExit(f"Could not open {args.port}. Close Serial Monitor and check the port.\n{exc}")

    try:
        # Opening USB serial may reset the ESP32. Allow it to boot, then discard startup text.
        time.sleep(2)
        board.reset_input_buffer()
        print(f"Calibrating neutral baseline from {args.calibration_samples} samples; keep hand relaxed...")
        calibration = read_n_valid(board, args.calibration_samples)
        baseline = [float(statistics.median(row[i] for row in calibration)) for i in range(11)]
        print("Calibration complete. Make one sign and hold it steady for about one second.")
        recent = deque(maxlen=3)
        sos_streak = 0
        rest_streak = 0
        sos_latched = False
        if args.enable_ntfy:
            print(f"AUTOMATIC ntfy enabled: a notification is sent after {args.sos_confirm_windows} consecutive SOS windows.")
        else:
            print(f"SOS dry-run enabled: requires {args.sos_confirm_windows} consecutive SOS windows. No message will be sent.")

        while True:
            rows = read_n_valid(board, args.window_samples)
            ranked = rank_predictions(make_features(rows, baseline), model)
            raw_prediction = ranked[0][0]
            recent.append(raw_prediction)
            stable_prediction = Counter(recent).most_common(1)[0][0]

            # Require consecutive raw SOS windows before a one-shot alert.
            sos_streak = sos_streak + 1 if raw_prediction == "sos" else 0
            rest_streak = rest_streak + 1 if raw_prediction == "rest" else 0
            if not sos_latched and sos_streak >= args.sos_confirm_windows:
                sos_latched = True
                if not args.enable_ntfy:
                    print("*** DRY RUN: SOS CONFIRMED. No message sent. ***")
                else:
                    topic_path = urllib.parse.quote(ntfy_topic, safe="")
                    request = urllib.request.Request(
                        f"https://ntfy.sh/{topic_path}",
                        data=b"SignSpeak detected a sustained SOS gesture. Please contact the wearer and check that they are safe.",
                        headers={"Title": "SignSpeak SOS", "Priority": "urgent"},
                        method="POST",
                    )
                    try:
                        with urllib.request.urlopen(request, timeout=10) as response:
                            print(f"*** ntfy accepted SOS notification (HTTP {response.status}). ***")
                    except (urllib.error.URLError, TimeoutError, OSError) as exc:
                        print(f"*** ntfy notification failed; no delivery confirmed: {exc} ***")
            if sos_latched and rest_streak >= 3:
                sos_latched = False
                sos_streak = 0
                print("SOS trigger re-armed after stable REST.")
            board.write(f"PRED:{stable_prediction}\n".encode("ascii"))
            board.flush()
            nearest = ", ".join(f"{label}={distance:.2f}" for label, distance in ranked[:2])
            print(f"Prediction: {stable_prediction} (window: {raw_prediction}; nearest distances: {nearest})")
    except KeyboardInterrupt:
        print("\nStopped live recognition.")
    except (serial.SerialException, RuntimeError) as exc:
        print(f"Live recognition stopped: {exc}")
    finally:
        board.close()


if __name__ == "__main__":
    main()



