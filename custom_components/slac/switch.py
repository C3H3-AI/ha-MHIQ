import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DOMAIN, SlacCoordinator

_LOGGER = logging.getLogger(__name__)

SWITCH_TYPES = {
    "fresh_air": {
        "attr_key": "FreshAir",
        "icon_on": "mdi:air-filter",
        "icon_off": "mdi:air-filter-off",
    },
    "auxiliary_electricity": {
        "attr_key": "AuxiliaryElectricity",
        "icon_on": "mdi:radiator",
        "icon_off": "mdi:radiator-off",
    },
}


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
        if unit_key not in coordinator.device_properties.get(iot_id, {}):
            continue
        if internal_addr == 0:
            continue
        nick = device.get("nickName", "") or device.get("deviceName", "") or f"设备{internal_addr}"
        for switch_type, config in SWITCH_TYPES.items():
            entities.append(SlacToggleSwitch(coordinator, iot_id, internal_addr, unit_key, nick, switch_type, config))

    _LOGGER.info("SLAC switch creating %d entities", len(entities))
    if entities:
        async_add_entities(entities)


class SlacToggleSwitch(CoordinatorEntity, SwitchEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SlacCoordinator,
        iot_id: str,
        internal_addr: int,
        unit_key: str,
        nick: str,
        switch_type: str,
        config: dict,
    ) -> None:
        super().__init__(coordinator)
        self._iot_id = iot_id
        self._internal_addr = internal_addr
        self._unit_key = unit_key
        self._switch_type = switch_type
        self._attr_key = config["attr_key"]
        self._api_reports_state = switch_type == "auxiliary_electricity"

        self._attr_unique_id = f"slac_{switch_type}_{internal_addr}"
        self._attr_translation_key = switch_type
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{iot_id}_ac_{internal_addr}")},
        }
        self._icon_on = config["icon_on"]
        self._icon_off = config["icon_off"]
        self._local_state = False

    @property
    def _props(self) -> dict:
        return self.coordinator.device_properties.get(self._iot_id, {}).get(self._unit_key, {})

    @property
    def is_on(self) -> bool:
        props = self._props
        api_value = props.get(self._attr_key)
        if self._api_reports_state and api_value is not None:
            return api_value == 1
        return self._local_state

    async def async_turn_on(self, **kwargs) -> None:
        coordinator: SlacCoordinator = self.coordinator
        items = {
            "InternalAddress": self._internal_addr,
            self._attr_key: 1,
        }
        try:
            await coordinator.api.async_set_properties(self._iot_id, items)
            self._local_state = True
            await coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.error("Failed to turn on %s: %s", self._switch_type, e)

    async def async_turn_off(self, **kwargs) -> None:
        coordinator: SlacCoordinator = self.coordinator
        items = {
            "InternalAddress": self._internal_addr,
            self._attr_key: 0,
        }
        try:
            await coordinator.api.async_set_properties(self._iot_id, items)
            self._local_state = False
            await coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.error("Failed to turn off %s: %s", self._switch_type, e)