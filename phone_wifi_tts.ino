#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SH110X.h>
#include <WiFi.h>
#include <WebServer.h>
#include <string.h>

const int flexPins[5] = {32, 33, 34, 35, 36};

#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
#define OLED_ADDRESS 0x3C

// Enter your phone hotspot credentials here. Do not share them in chat.
const char *WIFI_SSID = "boyyy";
const char *WIFI_PASSWORD = "12345678";

Adafruit_SH1106G display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, -1);
WebServer server(80);

uint8_t mpuAddress = 0;
unsigned long lastSampleMs = 0;
bool oledReady = false;
char hostLine[64];
size_t hostLineLength = 0;
String currentPrediction = "Waiting";

const char PHONE_PAGE[] PROGMEM = R"HTML(
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta charset="utf-8">
<title>SignSpeak Phone Voice</title>
<style>
body{font-family:Arial,sans-serif;text-align:center;margin:2rem;background:#f2f5f7;color:#17212b}
main{max-width:440px;margin:auto;background:white;padding:1.5rem;border-radius:16px;box-shadow:0 2px 14px #0002}
button{font-size:1.2rem;padding:.8rem 1.2rem;border:0;border-radius:10px;background:#087f8c;color:white}
#label{font-size:2rem;font-weight:bold;margin:1.3rem}
</style>
</head>
<body>
<main>
<h1>SignSpeak</h1>
<p>Connect to the ESP32 and enable phone speech.</p>
<button id="start" onclick="startVoice()">Enable phone voice</button>
<div id="label">Waiting</div>
<p id="status">Voice is off</p>
</main>
<script>
let voiceEnabled=false;
let previousLabel="";
const spokenPhrases={hello:'Hello',ok:'Okay',peace:'Peace',good_luck:'Good luck!',call_me:'Call me!'};
function startVoice(){
  if(!('speechSynthesis' in window)){document.getElementById('status').textContent='This browser does not support speech.';return;}
  voiceEnabled=true;
  document.getElementById('start').disabled=true;
  document.getElementById('status').textContent='Phone voice is on';
  const ready=new SpeechSynthesisUtterance('Phone voice ready');
  ready.lang='en-US'; ready.rate=0.95; ready.volume=1;
  speechSynthesis.speak(ready);
}
function speakLabel(label){
  if(!voiceEnabled || label===previousLabel)return;
  previousLabel=label;
  const phrase=spokenPhrases[label];
  if(!phrase)return;
  speechSynthesis.cancel();
  const utterance=new SpeechSynthesisUtterance(phrase);
  utterance.lang='en-US'; utterance.rate=0.9; utterance.volume=1;
  speechSynthesis.speak(utterance);
}
async function pollPrediction(){
  try{
    const response=await fetch('/prediction',{cache:'no-store'});
    const data=await response.json();
    const label=data.label || 'Waiting';
    document.getElementById('label').textContent=spokenPhrases[label] || label;
    speakLabel(label);
  }catch(e){document.getElementById('status').textContent='Lost connection to ESP32';}
}
setInterval(pollPrediction,300);
pollPrediction();
</script>
</body>
</html>
)HTML";

bool deviceResponds(uint8_t address) {
  Wire.beginTransmission(address);
  return Wire.endTransmission() == 0;
}

void writeMPURegister(uint8_t reg, uint8_t value) {
  Wire.beginTransmission(mpuAddress);
  Wire.write(reg);
  Wire.write(value);
  Wire.endTransmission();
}

bool readMPU(int16_t &ax, int16_t &ay, int16_t &az,
             int16_t &gx, int16_t &gy, int16_t &gz) {
  Wire.beginTransmission(mpuAddress);
  Wire.write(0x3B);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(mpuAddress, (uint8_t)14, (uint8_t)true) != 14) return false;

  int16_t values[7];
  for (int i = 0; i < 7; i++) {
    uint8_t highByte = Wire.read();
    uint8_t lowByte = Wire.read();
    values[i] = (int16_t)((highByte << 8) | lowByte);
  }

  ax = values[0]; ay = values[1]; az = values[2];
  gx = values[4]; gy = values[5]; gz = values[6];
  return true;
}

void drawPrediction() {
  if (!oledReady) return;
  display.clearDisplay();
  display.setTextColor(SH110X_WHITE);
  display.setTextSize(1);
  display.setCursor(0, 2);
  display.println("SignSpeak prediction");
  display.drawLine(0, 15, 127, 15, SH110X_WHITE);
  String shownPrediction = currentPrediction;
  if (currentPrediction == "good_luck") shownPrediction = "Good luck!";
  else if (currentPrediction == "call_me") shownPrediction = "Call me!";
  display.setTextSize(2);
  display.setCursor(0, 28);
  display.println(shownPrediction);
  display.display();
}

void handleRoot() {
  server.send_P(200, "text/html", PHONE_PAGE);
}

void handlePrediction() {
  String safeLabel = currentPrediction;
  safeLabel.replace("\"", "");
  server.send(200, "application/json", "{\"label\":\"" + safeLabel + "\"}");
}

void readHostCommands() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\r') continue;

    if (c == '\n') {
      hostLine[hostLineLength] = '\0';
      if (strncmp(hostLine, "PRED:", 5) == 0) {
        String newPrediction = String(hostLine + 5);
        if (newPrediction != currentPrediction) {
          currentPrediction = newPrediction;
          drawPrediction();
        }
      }
      hostLineLength = 0;
    } else if (hostLineLength < sizeof(hostLine) - 1) {
      hostLine[hostLineLength++] = c;
    } else {
      hostLineLength = 0;
    }
  }
}

void setup() {
  Serial.begin(115200);
  delay(500);

  Wire.begin(21, 22);
  Wire.setClock(100000);
  oledReady = display.begin(OLED_ADDRESS, true);
  drawPrediction();

  if (deviceResponds(0x68)) mpuAddress = 0x68;
  else if (deviceResponds(0x69)) mpuAddress = 0x69;
  else {
    Serial.println("ERROR: MPU6050 not found at 0x68 or 0x69");
    while (true) delay(1000);
  }

  writeMPURegister(0x6B, 0x00);
  writeMPURegister(0x1A, 0x03);
  writeMPURegister(0x19, 19);
  writeMPURegister(0x1C, 0x00);
  writeMPURegister(0x1B, 0x00);

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Connecting to phone hotspot");
  unsigned long wifiStart = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - wifiStart < 20000) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("Connected to hotspot. Phone page: http://");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("ERROR: hotspot connection failed; check name, password, and 2.4 GHz band");
  }

  server.on("/", HTTP_GET, handleRoot);
  server.on("/prediction", HTTP_GET, handlePrediction);
  server.begin();

  delay(100);
  Serial.println("t_ms,flex_thumb,flex_index,flex_middle,flex_ring,flex_little,ax_raw,ay_raw,az_raw,gx_raw,gy_raw,gz_raw");
}

void loop() {
  server.handleClient();
  readHostCommands();

  unsigned long now = millis();
  if (now - lastSampleMs < 20) return;
  lastSampleMs = now;

  int16_t ax, ay, az, gx, gy, gz;
  if (!readMPU(ax, ay, az, gx, gy, gz)) {
    Serial.println("ERROR: MPU6050 read failed");
    return;
  }

  Serial.print(now);
  for (int i = 0; i < 5; i++) {
    Serial.print(',');
    Serial.print(analogRead(flexPins[i]));
  }
  Serial.print(','); Serial.print(ax);
  Serial.print(','); Serial.print(ay);
  Serial.print(','); Serial.print(az);
  Serial.print(','); Serial.print(gx);
  Serial.print(','); Serial.print(gy);
  Serial.print(','); Serial.println(gz);
}

