import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
    HVACAction,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import SlacCoordinator
from .const import (
    AC_MODE_HA_MAP,
    AC_TO_FAN_MODE,
    AC_TO_SWING_MODE,
    AC_TO_PRESET_MODE,
    DOMAIN,
    FAN_MODE_LIST,
    FAN_MODE_TO_AC,
    HA_MODE_TO_AC,
    HVAC_ACTION_MAP,
    PRESET_MODE_LIST,
    PRESET_MODE_MAP,
    SWING_MODE_LIST,
    SWING_MODE_TO_AC,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback,
) -> None:
    _LOGGER.info("SLAC climate async_setup_entry STARTED")
    coordinator: SlacCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []
    seen = set()
    module_iot_id = ""
    for device in coordinator.devices:
        iot_id = device.get("iotId", "")
        if iot_id:
            module_iot_id = iot_id
        nick_name = device.get("nickName", "") or device.get("deviceName", "") or "三菱空调"
        internal_addr = device.get("internalAddress", -1)
        unit_key = f"Info{internal_addr}"
        key = f"{iot_id}_{unit_key}"
        if key in seen:
            continue
        seen.add(key)
        props = coordinator.device_properties.get(iot_id, {})
        if unit_key in props:
            _LOGGER.info("SLAC climate adding entity: iot_id=%s unit_key=%s nick=%s", iot_id, unit_key, nick_name)
            entities.append(SlacClimate(coordinator, entry, iot_id, nick_name, unit_key, device))
        else:
            _LOGGER.debug("SLAC climate skip %s: unit_key %s not in props keys=%s",
                          nick_name, unit_key, list(props.keys()))

    if module_iot_id:
        device_registry = dr.async_get(hass)
        detail = coordinator.device_detail or {}
        module_name = detail.get("productName", "三菱中央空调")
        product_model = detail.get("productModel", "W3M")
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, module_iot_id)},
            name=f"{module_name} (智能控制模块)",
            manufacturer="三菱重工海尔",
            model=f"SC-MIAS-{product_model}",
            configuration_url="https://slacapp2.mhaq.cn",
        )

    _LOGGER.info("SLAC climate async_setup_entry created %d entities", len(entities))
    if entities:
        async_add_entities(entities)

    entity_registry = er.async_get(hass)
    old_unique_ids = {f"{iot_id}_Info{addr}" for addr in range(9)}
    _to_remove = [
        entity_id
        for entity_id, e_entry in entity_registry.entities.items()
        if e_entry.platform == DOMAIN and e_entry.domain == "climate"
        and e_entry.unique_id in old_unique_ids
    ]
    for entity_id in _to_remove:
        _LOGGER.info("Removing old-style climate entity: %s", entity_id)
        entity_registry.async_remove(entity_id)


def build_device_info(coordinator: SlacCoordinator, device: dict) -> dict:
    iot_id = device.get("iotId", "")
    internal_addr = device.get("internalAddress", -1)
    nick_name = device.get("nickName", "") or device.get("deviceName", "") or "三菱空调"
    is_floor = internal_addr == 0
    info = {
        "identifiers": {(DOMAIN, f"{iot_id}_ac_{internal_addr}")},
        "via_device": (DOMAIN, iot_id),
        "name": nick_name,
        "manufacturer": "三菱重工海尔",
        "model": "地暖模块" if is_floor else "室内机",
        "configuration_url": "https://slacapp2.mhaq.cn",
    }
    return info


class SlacClimate(CoordinatorEntity, ClimateEntity):
    _attr_has_entity_name = False
    _enable_turn_on_off_backwards_compatibility = False

    def __init__(
        self,
        coordinator: SlacCoordinator,
        entry: ConfigEntry,
        iot_id: str,
        nick_name: str,
        unit_key: str,
        device: dict,
    ) -> None:
        super().__init__(coordinator)
        self._iot_id = iot_id
        self._nick_name = nick_name
        self._unit_key = unit_key
        self._internal_addr = int(unit_key.replace("Info", ""))
        self._device = device
        self._is_floor = self._internal_addr == 0

        self._attr_unique_id = f"slac_ac_{self._internal_addr}"
        self._attr_name = nick_name
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_target_temperature_step = 0.5
        self._attr_min_temp = 16
        self._attr_max_temp = 30
        self._attr_device_info = build_device_info(coordinator, device)

        if self._is_floor:
            self._attr_supported_features = (
                ClimateEntityFeature.TURN_ON
                | ClimateEntityFeature.TURN_OFF
                | ClimateEntityFeature.TARGET_TEMPERATURE
            )
            self._attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
        else:
            self._attr_supported_features = (
                ClimateEntityFeature.TURN_ON
                | ClimateEntityFeature.TURN_OFF
                | ClimateEntityFeature.TARGET_TEMPERATURE
                | ClimateEntityFeature.FAN_MODE
                | ClimateEntityFeature.SWING_MODE
                | ClimateEntityFeature.PRESET_MODE
            )
            self._attr_hvac_modes = [HVACMode.OFF, HVACMode.COOL, HVACMode.HEAT, HVACMode.DRY, HVACMode.FAN_ONLY, HVACMode.AUTO]
            self._attr_fan_modes = FAN_MODE_LIST
            self._attr_swing_modes = SWING_MODE_LIST
            self._attr_preset_modes = PRESET_MODE_LIST

    @property
    def _props(self) -> dict:
        coordinator: SlacCoordinator = self.coordinator
        return coordinator.device_properties.get(self._iot_id, {}).get(self._unit_key, {})

    @property
    def hvac_mode(self) -> HVACMode | None:
        props = self._props
        power = props.get("PowerSwitch", 0)
        if power != 1:
            return HVACMode.OFF
        if self._is_floor:
            return HVACMode.HEAT
        mode = props.get("WorkMode", 0)
        ha_mode = AC_MODE_HA_MAP.get(mode)
        if ha_mode:
            return HVACMode(ha_mode)
        return HVACMode.COOL

    @property
    def hvac_action(self) -> HVACAction | None:
        props = self._props
        power = props.get("PowerSwitch", 0)
        if power != 1:
            return HVACAction.OFF
        if self._is_floor:
            return HVACAction.HEATING
        mode = props.get("WorkMode", 0)
        if mode == 0:
            return HVACAction.IDLE
        action = HVAC_ACTION_MAP.get(mode)
        if action:
            return HVACAction(action)
        return HVACAction.IDLE

    @property
    def current_temperature(self) -> float | None:
        props = self._props
        temp = props.get("CurrentTemperature")
        if temp is not None:
            return float(temp)
        return None

    @property
    def target_temperature(self) -> float | None:
        props = self._props
        temp = props.get("TargetTemperature")
        if temp is not None:
            return float(temp)
        return None

    @property
    def fan_mode(self) -> str | None:
        if self._is_floor:
            return None
        props = self._props
        wind = props.get("WindSpeed", 0)
        return AC_TO_FAN_MODE.get(wind, "自动")

    @property
    def swing_mode(self) -> str | None:
        if self._is_floor:
            return None
        props = self._props
        horizontal = props.get("Horizontal", 0)
        return AC_TO_SWING_MODE.get(horizontal, "auto")

    @property
    def preset_mode(self) -> str | None:
        if self._is_floor:
            return None
        props = self._props
        cd = props.get("CleaningDegerming", 0)
        return AC_TO_PRESET_MODE.get(cd)

    @property
    def extra_state_attributes(self) -> dict:
        props = self._props
        return {
            "fresh_air": props.get("FreshAir", 0),
            "auxiliary_electricity": props.get("AuxiliaryElectricity", 0),
            "water_pump": props.get("WaterPump", 0),
            "controll_mode": props.get("ControllMode", 0),
            "error_code": props.get("ErrorCode", 0),
            "type_code": props.get("TypeCode", -1),
        }

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        coordinator: SlacCoordinator = self.coordinator
        items = {"InternalAddress": self._internal_addr}
        if hvac_mode == HVACMode.OFF:
            items["PowerSwitch"] = 0
        elif self._is_floor:
            items["PowerSwitch"] = 1
        else:
            items["PowerSwitch"] = 1
            ac_mode = HA_MODE_TO_AC.get(str(hvac_mode))
            if ac_mode is not None:
                items["WorkMode"] = ac_mode
        try:
            await coordinator.api.async_set_properties(self._iot_id, items)
            await coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.error("Failed to set HVAC mode: %s", e)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return
        coordinator: SlacCoordinator = self.coordinator
        items = {
            "InternalAddress": self._internal_addr,
            "PowerSwitch": 1,
            "TargetTemperature": temp,
        }
        try:
            await coordinator.api.async_set_properties(self._iot_id, items)
            await coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.error("Failed to set temperature: %s", e)

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        wind = FAN_MODE_TO_AC.get(fan_mode, 0)
        coordinator: SlacCoordinator = self.coordinator
        items = {"InternalAddress": self._internal_addr, "PowerSwitch": 1, "WindSpeed": wind}
        try:
            await coordinator.api.async_set_properties(self._iot_id, items)
            await coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.error("Failed to set fan mode: %s", e)

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        horizontal = SWING_MODE_TO_AC.get(swing_mode, 0)
        coordinator: SlacCoordinator = self.coordinator
        items = {"InternalAddress": self._internal_addr, "PowerSwitch": 1, "Horizontal": horizontal}
        try:
            await coordinator.api.async_set_properties(self._iot_id, items)
            await coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.error("Failed to set swing mode: %s", e)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        cd_value = PRESET_MODE_MAP.get(preset_mode)
        if cd_value is None:
            return
        coordinator: SlacCoordinator = self.coordinator
        items = {"InternalAddress": self._internal_addr, "CleaningDegerming": cd_value}
        try:
            await coordinator.api.async_set_properties(self._iot_id, items)
            await coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.error("Failed to set preset mode: %s", e)

    async def async_turn_on(self) -> None:
        if self._is_floor:
            await self.async_set_hvac_mode(HVACMode.HEAT)
        else:
            await self.async_set_hvac_mode(HVACMode.COOL)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)