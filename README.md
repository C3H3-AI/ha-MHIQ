# MHIQ — Mitsubishi Smart AC

[![HACS Validation](https://img.shields.io/badge/HACS-Custom-orange)](https://hacs.xyz)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2026.5-blue)](https://www.home-assistant.io)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![GitHub](https://img.shields.io/badge/GitHub-C3H3--AI-blue)](https://github.com/C3H3-AI/ha-MHIQ)

Home Assistant custom integration for **Mitsubishi Heavy Industries Haier (三菱海尔重工)** smart air conditioners using the **SC-MIAS-W3M** WiFi module.

> **Model**: SC-MIAS-W3M (三菱海尔重工 WiFi module)
> **Brand**: MHIQ — Mitsubishi Heavy Industries Haier (三菱海尔重工)
> **App**: SLAC (三菱智能空调)

---

## Features

- Control up to **9 air conditioner units** through a single WiFi module
- Full climate control: mode (cool/heat/fan/dry/auto), temperature, fan speed
- Real-time temperature readings for each indoor unit
- Built-in **weather service** (optional): outdoor temperature, humidity, wind, air quality
- Config Flow setup via **phone number + password** login
- Supports **Chinese mainland phone numbers**
- Options Flow to toggle weather service on/off without reinstall

---

## Hardware

| Component | Description |
|-----------|-------------|
| **WiFi Module** | SC-MIAS-W3M, manufactured by Mitsubishi Heavy Industries Haier |
| **Communication** | Cloud-based (WiFi module connects to manufacturer's IoT cloud) |
| **Units** | Up to 9 indoor units per module |
| **Network** | Standard 2.4GHz WiFi |

---

## Installation

### HACS (Custom Repository)

1. Open HACS → Integrations → Custom repositories
2. Add this repository URL: `https://github.com/C3H3-AI/ha-MHIQ`
3. Category: **Integration**
4. Click **Download**
5. Restart Home Assistant

### Manual

1. Copy the `custom_components/slac/` directory to your HA `config/custom_components/` directory
2. Restart Home Assistant
3. Go to Settings → Devices & Services → Add Integration
4. Search for "Mitsubishi Smart AC" or "MHIQ"

---

## Configuration

### Step 1: Phone Login

1. Enter your Chinese mainland phone number
2. Enter your SLAC app password
3. Enable "Weather service" if desired (requires location)
4. Click Submit

### Step 2: Location (Weather Only)

If you enabled weather service and left location fields empty, the integration will attempt to auto-detect your location based on your Home Assistant public IP. If detection fails, weather is silently disabled.

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
| Toggle weather | Enable/disable weather sensors |
| Update location | Change province/city/district |
| Re-login | Update phone/password |

---

## Entities

### Climate (per indoor unit)

Each unit identified by its internal address (1-9).

| Entity ID Pattern | Attributes |
|-------------------|------------|
| `climate.slac_ac_{internal_addr}` | Mode, temp, fan speed, current temp |

**Supported HVAC Modes**: off, cool, heat, fan_only, dry, auto

### Sensor (Weather - Optional)

Enabled only if weather service is toggled on.

| Entity | Unit |
|--------|------|
| Weather Condition | Text description |
| Weather Temperature | °C |
| Humidity | % |
| Wind Direction | Cardinal direction |
| Wind Force | Beaufort scale |
| Wind Speed | m/s |
| Rain Probability | % |
| Air Quality | Level |
| PM2.5 | µg/m³ |

---

## Credits

- **Author**: [C3H3-AI](https://github.com/C3H3-AI)

---

## License

MIT License

---

## Disclaimer

This integration is an independent, community-developed project. It is not affiliated with, endorsed by, or officially supported by Mitsubishi Heavy Industries Haier or any of its subsidiaries. Use at your own risk.