# Changelog

## [1.2.5] - 2026-11-26

### Fixed

- climate: `set_temperature`, `set_fan_mode` and `set_swing_mode` no longer send `PowerSwitch: 1`
  - previously, changing temperature / fan speed / swing on a unit that was **off** turned it on
  - these setters now send only the values they are named for; power is changed only by `set_hvac_mode` / `turn_on` / `turn_off`

## [1.2.4] - 2026-09-13

### Added

- hassfest CI (home-assistant/actions/hassfest@master)
- HACS validate CI (hacs/action@main)
- tag-triggered auto Release workflow
- PR template + Issue template

### Fixed

- manifest: remove deprecated keys (authors/icon/homeassistant)
- manifest: canonical key order (domain,name then alphabetical)
- services.yaml: remove deprecated device target filters
