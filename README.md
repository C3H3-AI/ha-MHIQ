# MHIQ — Mitsubishi Smart AC

[![HACS Validation](https://img.shields.io/badge/HACS-Custom-orange)](https://hacs.xyz)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2026.5-blue)](https://www.home-assistant.io)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![GitHub](https://img.shields.io/badge/GitHub-C3H3--AI-blue)](https://github.com/C3H3-AI/ha-MHIQ)

Home Assistant custom integration for **Mitsubishi Heavy Industries Haier (三菱海尔重工)** smart air conditioners using the **SC-MIAS-W3M** WiFi module.

This integration was developed through full APK reverse engineering of the official SLAC mobile app.

> **Model**: SC-MIAS-W3M (三菱海尔重工 WiFi module)
> **Brand**: MHIQ — Mitsubishi Heavy Industries Haier (三菱海尔重工)
> **App**: SLAC (三菱智能空调)

---

## Features

- Control up to **9 air conditioner units** through a single WiFi module
- Full climate control: mode (cool/heat/fan/dry/auto), temperature, fan speed
- Real-time sensor readings: indoor temperature, outdoor temperature, PM2.5
- Built-in **weather service** (optional): outdoor temperature, humidity, wind, air quality from the manufacturer's weather API
- Config Flow setup via **phone number + password** login
- Supports **Chinese mainland phone numbers** (validates +86 format)
- Automatic iotToken refresh (expires ~20h, auto-renewed)
- Options Flow to toggle weather service on/off without reinstall

---

## Hardware

| Component | Description |
|-----------|-------------|
| **WiFi Module** | SC-MIAS-W3M, manufactured by Mitsubishi Heavy Industries Haier |
| **Communication** | Cloud-based (WiFi module connects to manufacturer's IoT cloud) |
| **Units** | Up to 9 indoor units per module |
| **Network** | Standard 2.4GHz WiFi, requires internet access to the cloud API |

---

## Installation

### HACS (Custom Repository)

1. Open HACS → Integrations → Custom repositories
2. Add this repository URL: `https://github.com/C3H3-AI/ha-MHIQ`
3. Category: **Integration**
4. Click **Install**
5. Restart Home Assistant

### Manual

1. Copy the `custom_components/slac/` directory to your HA `config/custom_components/` directory
2. Restart Home Assistant
3. Go to Settings → Devices & Services → Add Integration
4. Search for "Mitsubishi Smart AC" or "MHIQ"

---

## Configuration

### Step 1: Phone Login

1. Enter your Chinese mainland phone number (e.g., `13800138000`)
2. Enter your SLAC app password
3. Enable "Weather service" if desired (requires location)
4. Click Submit

### Step 2: Location (Weather Only)

If you enabled weather service and left location fields empty, the integration will attempt to auto-detect your location via **Nominatim reverse geocoding** (based on your Home Assistant public IP). If detection fails, weather is silently disabled.

Alternatively, manually enter:

| Field | Description | Example |
|-------|-------------|---------|
| Province | Province name | Zhejiang |
| City | City name | Wenzhou |
| District | District/county | Yueqing |

### Post-Install Options

After installation, go to **Configure** to:

| Option | Description |
|--------|-------------|
| Toggle weather | Enable/disable weather sensors without reinstall |
| Update location | Change province/city/district |
| Re-login | Update phone/password if credentials change |

---

## Entities

### Climate (per indoor unit)

Each unit identified by its **internal address** (1-9, matching the DIP switch or unit ID set during installation).

| Entity ID Pattern | Attributes |
|-------------------|------------|
| `climate.slac_ac_{internal_addr}` | Mode, temp, fan speed, swing, current temp |

**Supported HVAC Modes**: `off`, `cool`, `heat`, `fan_only`, `dry`, `auto`

### Sensor (Weather - Optional)

Enabled only if weather service was toggled on during setup.

| Entity | Device Class | Unit |
|--------|-------------|------|
| `sensor.slac_weather_condition` | `None` | Text description |
| `sensor.slac_weather_temperature` | `temperature` | °C |
| `sensor.slac_weather_humidity` | `humidity` | % |
| `sensor.slac_weather_wind_direction` | `None` | Cardinal direction |
| `sensor.slac_weather_wind_force` | `None` | Beaufort scale |
| `sensor.slac_weather_wind_speed` | `None` | m/s |
| `sensor.slac_weather_rain_probability` | `None` | % |
| `sensor.slac_weather_air_quality` | `None` | Level (e.g., "Good") |
| `sensor.slac_weather_pm25` | `pm25` | µg/m³ |

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  Home Assistant                  │
│                                                   │
│  ┌──────────────────────────────────────────┐    │
│  │          DataUpdateCoordinator            │    │
│  │  ┌──────────────────┐  ┌──────────────┐  │    │
│  │  │ device/list +    │  │ weather/get  │  │    │
│  │  │ properties/get   │  │ (if enabled) │  │    │
│  │  └────────┬─────────┘  └──────┬───────┘  │    │
│  └───────────┼──────────────────┼───────────┘    │
│              │                  │                 │
│  ┌───────────┴──────────────────┴───────────┐    │
│  │              SlacApi Client              │    │
│  │  - OA Login (RSA encrypted password)     │    │
│  │  - Token refresh (identityId/refresh)    │    │
│  │  - HMAC-SHA1 signing (AppKey/AppSecret)  │    │
│  │  - IoT device control & query            │    │
│  └───────────────────┬──────────────────────┘    │
└──────────────────────┼───────────────────────────┘
                       │ HTTPS
┌──────────────────────┴───────────────────────────┐
│              Mitsubishi IoT Cloud                 │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  │
│  │ OA API     │  │ IoT API    │  │ Custom API │  │
│  │ (login)    │  │ (control)  │  │ (weather)  │  │
│  └────────────┘  └────────────┘  └────────────┘  │
└──────────────────────────────────────────────────┘
```

### API Endpoints Discovered

The following endpoints were discovered through **APK reverse engineering** of the official SLAC Android app (v2.1.8):

**Group A — IoT Device API** (requires iotToken + HMAC-SHA1 signature):
- `POST /account/createSessionByAuthCode` — Token exchange (sid → identityId + refreshToken + iotToken)
- `POST /uc/listBindingByAccount` — List bound devices
- `POST /thing/properties/get` — Get device properties (temperatures, modes, PM2.5)
- `POST /thing/properties/set` — Set device properties (mode, temp, fan speed)

**Group B — OA Auth API** (requires RSA-encrypted password):
- `POST /api/prd/login.json` — Phone + password login

**Group C — Custom API** (identityId + iotToken):
- `POST /devDevice/getDeviceList` — Detailed device list with nicknames
- `POST /weather/getWeather` — Weather data (temperature, humidity, wind, PM2.5)

### Security Analysis

| Algorithm | Detail | Source |
|-----------|--------|--------|
| **HMAC-SHA1** | Request signing, AppKey `34457410` + AppSecret `6cf45cdbeaa4ce6faa204741f3d772ca` | AliCloud CloudAPI SDK |
| **RSA/ECB/PKCS1Padding** | Password encryption, 2048-bit public key, 245-byte block processing | Alibaba OA SDK |
| **fastjson escaping** | JSON `"/"` → `"\\/"` before signing | Alibaba fastjson SDK |

---

## Development

### Reverse Engineering

This integration is the result of **full APK reverse engineering** of the SLAC Android app. The methodology is documented as a reusable skill:

- **APKTool + Jadx** for static analysis
- **mitmproxy** + **MuMu emulator** for packet capture
- **Smali patching** (Log.d injection) for runtime verification
- **Frida hooking** for dynamic AppSecret extraction

### Repository Structure

```
ha-MHIQ/
├── custom_components/slac/
│   ├── __init__.py        # Coordinator + platform loading
│   ├── api.py             # Full API client (OA + IoT + Custom)
│   ├── climate.py         # Climate platform (up to 9 units)
│   ├── sensor.py          # Weather sensor platform
│   ├── config_flow.py     # Config/Options flow with weather toggle
│   ├── const.py           # Constants
│   ├── manifest.json      # HA manifest
│   ├── strings.json       # English translations
│   └── translations/
│       └── zh-Hans.json   # Simplified Chinese translations
├── REVERSE_ENGINEERING_RECORD.md  # Full reverse engineering journal
├── SLAC_PROJECT_STATUS.md         # Project status tracking
├── README.md              # This file
└── .gitignore
```

### Requirements

- Home Assistant 2025.3+
- Python 3.11+
- `cryptography>=41.0.0` (for RSA password encryption)

---

## Credits

- **Author**: [C3H3-AI](https://github.com/C3H3-AI)
- **Reverse Engineering & Integration**: SOLO AI
- **APK Analysis Tools**: APKTool, Jadx, Frida, mitmproxy
- **Brand**: MHIQ — Mitsubishi Heavy Industries Haier (三菱海尔重工)
- **WiFi Module**: SC-MIAS-W3M

---

## License

MIT License

---

## Disclaimer

This integration is an independent, community-developed project. It is not affiliated with, endorsed by, or officially supported by Mitsubishi Heavy Industries Haier or any of its subsidiaries. Use at your own risk. The reverse engineering was performed for interoperability purposes under applicable fair use provisions.