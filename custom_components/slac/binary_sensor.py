import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DOMAIN, SlacCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SlacCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []

    first_iot_id = ""
    for device in coordinator.devices:
        iot_id = device.get("iotId", "")
        if iot_id:
            first_iot_id = iot_id
            break
    if first_iot_id:
        entities.append(SlacModuleOnlineBinarySensor(coordinator, first_iot_id))
        _LOGGER.info("SLAC binary_sensor adding WiFi module online indicator: %s", first_iot_id)

    for device in coordinator.devices:
        iot_id = device.get("iotId", "")
        internal_addr = device.get("internalAddress", -1)
        unit_key = f"Info{internal_addr}"
        if unit_key not in coordinator.device_properties.get(iot_id, {}):
            continue
        nick = device.get("nickName", "") or device.get("deviceName", "") or f"设备{internal_addr}"
        entities.append(SlacSubOnlineBinarySensor(coordinator, iot_id, internal_addr, unit_key, nick))

    _LOGGER.info("SLAC binary_sensor creating %d entities", len(entities))
    if entities:
        async_add_entities(entities)


class SlacModuleOnlineBinarySensor(CoordinatorEntity, BinarySensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SlacCoordinator,
        iot_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._iot_id = iot_id

        self._attr_unique_id = "slac_online_module"
        self._attr_translation_key = "module_online"
        self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
        self._attr_device_info = {
            "identifiers": {(DOMAIN, iot_id)},
        }

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.device_properties.get(self._iot_id))

    @property
    def icon(self) -> str:
        return "mdi:wifi" if self.is_on else "mdi:wifi-off"


class SlacSubOnlineBinarySensor(CoordinatorEntity, BinarySensorEntity):
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

        self._attr_unique_id = f"slac_online_{internal_addr}"
        self._attr_name = "在线状态"
        self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{iot_id}_ac_{internal_addr}")},
        }

    @property
    def _props(self) -> dict:
        return self.coordinator.device_properties.get(self._iot_id, {}).get(self._unit_key, {})

    @property
    def is_on(self) -> bool:
        return bool(self._props)

    @property
    def icon(self) -> str:
        return "mdi:wifi" if self.is_on else "mdi:wifi-off"