import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DOMAIN, SlacCoordinator
from .const import CONF_ENABLE_WEATHER

_LOGGER = logging.getLogger(__name__)

WEATHER_DEVICE_IDENTIFIERS = {(DOMAIN, "weather")}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SlacCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []

    for device in coordinator.devices:
        iot_id = device.get("iotId", "")
        internal_addr = device.get("internalAddress", -1)
        unit_key = f"Info{internal_addr}"
        props = coordinator.device_properties.get(iot_id, {}).get(unit_key, {})
        nick = device.get("nickName", "") or device.get("deviceName", "") or f"设备{internal_addr}"
        if unit_key in coordinator.device_properties.get(iot_id, {}):
            entities.append(SlacErrorCodeSensor(coordinator, iot_id, internal_addr, unit_key, nick))

    _LOGGER.info("SLAC sensor creating %d ErrorCode sensors", len(entities))

    if entry.data.get(CONF_ENABLE_WEATHER, True):
        weather_sensors = [
            ("weather_location", "天气地区", "location", None, None),
            ("outdoor_temp", "室外温度", "tmp", UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE),
            ("weather_cond", "天气状况", "cond_txt", None, None),
            ("air_quality", "空气质量", "qlty", None, None),
            ("pm25", "PM2.5", "pm25", "μg/m³", SensorDeviceClass.PM25),
            ("temp_max", "最高温度", "tmp_max", UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE),
            ("temp_min", "最低温度", "tmp_min", UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE),
            ("comfort", "舒适度", "comf", None, None),
            ("wind", "风力", "wind_sc", None, None),
        ]
        for key, name, data_key, unit, device_class in weather_sensors:
            entities.append(SlacWeatherSensor(coordinator, key, data_key, unit, device_class))
        _LOGGER.info("SLAC sensor creating %d weather sensors", len(weather_sensors))

    _LOGGER.info("SLAC sensor async_setup_entry created %d entities", len(entities))
    if entities:
        async_add_entities(entities)


class SlacErrorCodeSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SlacCoordinator,
        iot_id: str,
        internal_addr: int,
        unit_key: str,
        nick: str,
    ) -> None:
        super().__init__(coordinator)
        self._iot_id = iot_id
        self._internal_addr = internal_addr
        self._unit_key = unit_key

        self._attr_unique_id = f"slac_error_{internal_addr}"
        self._attr_translation_key = "error_code"
        self._attr_device_class = None
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{iot_id}_ac_{internal_addr}")},
        }

    @property
    def _props(self) -> dict:
        return self.coordinator.device_properties.get(self._iot_id, {}).get(self._unit_key, {})

    @property
    def native_value(self) -> Any:
        props = self._props
        code = props.get("ErrorCode", 0)
        return int(code) if code is not None else 0

    @property
    def icon(self) -> str:
        if self.native_value and self.native_value != 0:
            return "mdi:alert-circle"
        return "mdi:check-circle"


class SlacWeatherSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SlacCoordinator,
        key: str,
        data_key: str,
        unit: str | None,
        device_class: SensorDeviceClass | None,
    ) -> None:
        super().__init__(coordinator)
        self._key = key
        self._data_key = data_key
        self._attr_unique_id = f"slac_weather_{key}"
        self._attr_translation_key = key
        if unit:
            self._attr_native_unit_of_measurement = unit
        if device_class:
            self._attr_device_class = device_class
        self._attr_device_info = {
            "identifiers": WEATHER_DEVICE_IDENTIFIERS,
            "name": "三菱空调天气",
            "manufacturer": "三菱重工海尔",
            "model": "天气服务",
        }

    @property
    def native_value(self) -> Any:
        if self._key == "weather_location":
            province = self.coordinator.api.province or ""
            city = self.coordinator.api.city or ""
            sub_locality = self.coordinator.api.sub_locality or ""
            location = f"{province} {city} {sub_locality}".strip()
            return location if location else None

        has_location = bool(self.coordinator.api.province or self.coordinator.api.city)
        if not has_location:
            return None

        weather = self.coordinator.data.get("weather") if self.coordinator.data else None
        if not weather:
            return None
        val = weather.get(self._data_key)
        if val is None:
            return None
        if self._data_key in ("tmp", "tmp_max", "tmp_min", "pm25"):
            try:
                return float(val)
            except (ValueError, TypeError):
                return val
        return val

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        weather = self.coordinator.data.get("weather") if self.coordinator.data else None
        if not weather:
            return {}
        attrs = {}
        if self._key == "outdoor_temp":
            attrs["最高温度"] = weather.get("tmp_max")
            attrs["最低温度"] = weather.get("tmp_min")
            attrs["天气"] = weather.get("cond_txt")
            attrs["空气质量"] = weather.get("qlty")
        return attrs