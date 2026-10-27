# SignSpeak

SignSpeak is an ESP32-based smart glove that reads five flex sensors and an MPU6050, classifies a small set of hand signs on a connected computer, and displays/speaks the prediction on a phone webpage over Wi-Fi. The current model uses `hello`, `ok`, `peace`, `rest`, and `sos`.

## Repository contents

- `firmware/phone_wifi_tts.ino` — ESP32 firmware for sensor streaming, OLED output, and the phone webpage.
- `scripts/` — Python data collection, validation, model training, evaluation, and live prediction tools.
- `models/session6_neutral_centroid_model.json` — the saved model for the five current labels.
- `data/session6_before_phrases_backup.csv` — matching labeled training data, before the `good_luck` phrase was added.

## Hardware and wiring

- ESP32 flex sensor ADC pins: GPIO 32, 33, 34, 35, 36 (thumb through little finger).
- MPU6050 and I2C OLED share SDA GPIO 21 and SCL GPIO 22.
- Connect all device grounds together. Keep flex-sensor ADC voltage within 0–3.3 V.
- The firmware expects a 128×64 SH1106 OLED at I2C address `0x3C`.

## Setup

Install the ESP32 board support in Arduino IDE, plus the **Adafruit GFX Library** and **Adafruit SH110X** libraries. Open `firmware/phone_wifi_tts.ino`, replace the hotspot name and password placeholders with your local 2.4 GHz hotspot credentials, select the correct ESP32 board and COM port, and upload. Do not commit real Wi-Fi credentials.

On Windows, open PowerShell in the repository root and install the Python dependency:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Close Arduino Serial Monitor before running Python, because only one program can use the ESP32 COM port at a time.

## Validate and train

```powershell
python scripts/validate_dataset.py --csv data/session6_before_phrases_backup.csv
python scripts/train_calibrated.py --csv data/session6_before_phrases_backup.csv --model-out models/session6_neutral_centroid_model.json
```

Training overwrites the named model output file. Keep a copy if you want to preserve the current saved model.

## Run live recognition

```powershell
python scripts/live_predict.py --port COM10 --model models/session6_neutral_centroid_model.json
```

When prompted, press Enter with your hand relaxed for neutral calibration. The script then reads sensor windows, prints predictions, and sends the stable prediction to the ESP32 for the OLED/phone page. Open the phone page using the local address printed by the firmware after it joins the hotspot.

## Optional ntfy SOS alerts

Subscribe the recipient's phone to the same private ntfy topic. In PowerShell, set the topic locally and enable alerts:

```powershell
$env:NTFY_TOPIC = Read-Host "Enter the ntfy topic"
python scripts/live_predict.py --port COM10 --model models/session6_neutral_centroid_model.json --enable-ntfy
```

With `--enable-ntfy`, three consecutive SOS windows can send a real urgent notification. Without the flag, SOS is dry-run only. Never commit the ntfy topic or recipient details. This prototype depends on the computer, ESP32, Wi-Fi, and ntfy service being available; do not rely on it as the only emergency communication method.

## Data and model notes

The supplied CSV contains the original five labels and sensor readings. The current repository model does not include `good_luck`. The training script reports a held-out split from the supplied recordings; live performance can differ, so test all signs with the actual glove setup.
