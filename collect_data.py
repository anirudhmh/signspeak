#!/usr/bin/env python3
"""Collect one-second labeled SignSpeak sensor recordings from ESP32 serial CSV.

Expected ESP32 row format (header is ignored):
  t_ms,flex_thumb,flex_index,flex_middle,flex_ring,flex_little,
  ax_raw,ay_raw,az_raw,gx_raw,gy_raw,gz_raw

Uses only Python's standard library plus pyserial. It does not require pandas.
"""

from __future__ import annotations

import argparse
import csv
import time
from datetime import datetime
from pathlib import Path

import serial
from serial.tools import list_ports

SENSOR_COLUMNS = [
    "flex_thumb", "flex_index", "flex_middle", "flex_ring", "flex_little",
    "ax_raw", "ay_raw", "az_raw", "gx_raw", "gy_raw", "gz_raw",
]
OUTPUT_COLUMNS = ["recording_id", "label", "sample_index", "t_ms", *SENSOR_COLUMNS]


def parse_sensor_row(line: str) -> tuple[int, list[int]] | None:
    """Return board time and 11 raw sensor values, or None for non-data lines."""
    parts = line.strip().split(",")
    if len(parts) != 12:
        return None
    try:
        values = [int(part.strip()) for part in parts]
    except ValueError:
        return None
    return values[0], values[1:]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="ESP32 serial port, for example COM10")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--seconds", type=float, default=1.0,
                        help="duration of each recording (default: 1 second)")
    parser.add_argument("--output", default="data/raw/sensor_samples.csv",
                        help="CSV output path (default: data/raw/sensor_samples.csv)")
    parser.add_argument("--label", help="record many examples with this label without retyping it")
    parser.add_argument("--count", type=int, help="number of recordings when --label is used")
    args = parser.parse_args()
    if args.seconds <= 0:
        parser.error("--seconds must be greater than zero")
    if args.count is not None and args.count <= 0:
        parser.error("--count must be greater than zero")
    if args.count is not None and not args.label:
        parser.error("--count requires --label")

    ports = [p.device for p in list_ports.comports()]
    port_name = args.port
    if not port_name:
        print("Available serial ports:", ", ".join(ports) if ports else "none")
        port_name = input("Enter the ESP32 port (for example COM10): ").strip()
    if not port_name:
        print("No serial port selected.")
        return 2

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = output_path.exists() and output_path.stat().st_size > 0
    try:
        board = serial.Serial(port_name, args.baud, timeout=0.25)
    except serial.SerialException as exc:
        print(f"Could not open {port_name}: {exc}")
        print("Close Arduino Serial Monitor and check the selected COM port.")
        return 2

    print(f"Connected to {port_name} at {args.baud} baud.")
    print("Expected 12 comma-separated fields: time + 11 sensor values.")
    if args.label:
        print(f"Batch mode: recording {args.count or 'until stopped'} example(s) labeled '{args.label}'.")
        print("Prepare the gesture and press Enter for each one. Ctrl+C stops the batch.")
    else:
        print("Enter a label, prepare that gesture, then press Enter to record.")
        print("Use q as the label to stop. Keep each gesture steady for one second.")

    try:
        with output_path.open("a", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            if not file_exists:
                writer.writerow(OUTPUT_COLUMNS)
                csv_file.flush()

            recording_number = 0
            connection_lost = False
            while True:
                if args.label:
                    if args.count is not None and recording_number >= args.count:
                        break
                    label = args.label.strip()
                else:
                    label = input("Label (or q to quit): ").strip()
                    if label.lower() in {"q", "quit", "exit"}:
                        break
                    if not label:
                        print("Please enter a label, for example rest.")
                        continue

                input("Make the gesture, then press Enter to record...")
                board.reset_input_buffer()
                print(f"Recording '{label}' for {args.seconds:g} second(s)...")
                recording_number += 1
                recording_id = datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{recording_number:03d}"
                start = None
                deadline = None
                sample_index = 0

                while deadline is None or time.monotonic() < deadline:
                    try:
                        line = board.readline().decode("ascii", errors="replace")
                    except serial.SerialException as exc:
                        print(f"Serial connection lost during recording: {exc}")
                        print("This recording may be incomplete; reconnect the ESP32 and retry it.")
                        connection_lost = True
                        break
                    parsed = parse_sensor_row(line)
                    if parsed is None:
                        continue
                    board_ms, sensor_values = parsed
                    if start is None:
                        start = time.monotonic()
                        deadline = start + args.seconds
                    writer.writerow([recording_id, label, sample_index, board_ms, *sensor_values])
                    sample_index += 1

                csv_file.flush()
                print(f"Saved {sample_index} samples to {output_path}")
                if sample_index < int(args.seconds * 25):
                    print("Warning: fewer than 25 samples received; check the serial stream.")
                if connection_lost:
                    break
    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        board.close()

    print(f"Data file: {output_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


