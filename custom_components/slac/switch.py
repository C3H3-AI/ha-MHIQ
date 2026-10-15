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

# 账户级通知开关（/devUserConfig/{type}/on|off，App NotifactionSettingActivity）
NOTICE_SWITCHES = {
    "notice_exception": {
        "notice_key": "exceptionNotice",
        "label": "故障异常提醒",
        "icon": "mdi:alert-circle",
    },
    "notice_be_home": {
        "notice_key": "beHomeNotice",
        "label": "到家提醒",
        "icon": "mdi:home-alert",
    },
    "notice_leave_home": {
        "notice_key": "leaveHomeNotice",
        "label": "离家提醒",
        "icon": "mdi:home-export-outline",
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

    # 账户级通知开关（挂到首个模块设备）
    if coordinator.devices:
        first_iot_id = coordinator.devices[0].get("iotId", "")
        for switch_type, config in NOTICE_SWITCHES.items():
            entities.append(SlacNoticeSwitch(coordinator, first_iot_id, switch_type, config))

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


class SlacNoticeSwitch(CoordinatorEntity, SwitchEntity):
    """账户级通知开关（状态来自 /devUserConfig/detail，写走 /devUserConfig/{type}/on|off）"""

    _attr_has_entity_name = False

    def __init__(
        self,
        coordinator: SlacCoordinator,
        iot_id: str,
        switch_type: str,
        config: dict,
    ) -> None:
        super().__init__(coordinator)
        self._iot_id = iot_id
        self._switch_type = switch_type
        self._notice_key = config["notice_key"]
        self._local_state: bool | None = None

        self._attr_unique_id = f"slac_{switch_type}"
        self._attr_name = config["label"]
        self._attr_icon = config["icon"]
        self._attr_device_info = {
            "identifiers": {(DOMAIN, iot_id)},
        }

    @property
    def is_on(self) -> bool | None:
        cfg = self.coordinator.notice_config or {}
        if self._notice_key in cfg:
            return bool(cfg[self._notice_key])
        return self._local_state

    async def _async_set(self, enabled: bool) -> None:
        try:
            ok = await self.coordinator.api.async_set_notice_config(self._notice_key, enabled)
            if ok:
                self._local_state = enabled
                # 通知配置刷新限流 30 分钟，强制立即刷新
                self.coordinator._last_extras_refresh = 0.0
                await self.coordinator.async_request_refresh()
            else:
                _LOGGER.error("设置通知开关 %s=%s 服务端返回失败", self._notice_key, enabled)
        except Exception as e:
            _LOGGER.error("设置通知开关 %s 失败: %s", self._notice_key, e)

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_set(False)