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
    if not entry.data.get(CONF_ENABLE_WEATHER, True):
        _LOGGER.info("SLAC weather sensors disabled by user config")
        return
    _LOGGER.info("SLAC sensor async_setup_entry STARTED")
    coordinator: SlacCoordinator = hass.data[DOMAIN][entry.entry_id]
    _LOGGER.info("SLAC sensor coordinator devices=%d props=%d",
                 len(coordinator.devices), len(coordinator.device_properties))
    entities = []

    sensors = [
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
    for key, name, data_key, unit, device_class in sensors:
        entities.append(SlacWeatherSensor(coordinator, key, name, data_key, unit, device_class))

    _LOGGER.info("SLAC sensor async_setup_entry created %d entities", len(entities))
    if entities:
        async_add_entities(entities)


class SlacWeatherSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SlacCoordinator,
        key: str,
        name: str,
        data_key: str,
        unit: str | None,
        device_class: SensorDeviceClass | None,
    ) -> None:
        super().__init__(coordinator)
        self._key = key
        self._data_key = data_key
        self._attr_unique_id = f"slac_weather_{key}"
        self._attr_translation_key = key
        self._attr_name = name
        if unit:
            self._attr_native_unit_of_measurement = unit
        if device_class:
            self._attr_device_class = device_class
        # 天气传感器绑定到独立的天气设备，而非空调设备
        self._attr_device_info = {
            "identifiers": WEATHER_DEVICE_IDENTIFIERS,
            "name": "三菱空调天气",
            "manufacturer": "三菱电机 Mitsubishi Electric",
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
