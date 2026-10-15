"""SLAC 场景与工具按钮

- 每个云端场景一个“执行场景”按钮（/scene/fire）
- 华为音箱配对码按钮（点击获取 /oauth/vcode vcode，见 entity 属性）
- 场景列表由 coordinator 每 30 分钟低频刷新，也可在服务调用后触发刷新
"""
import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DOMAIN, SlacCoordinator

_LOGGER = logging.getLogger(__name__)

# App 内部生成的单设备定时场景（SceneBiz 过滤条件），不作为按钮展示
INTERNAL_SCENE_NAME_TOKEN = "single_device_schedule"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SlacCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list = []

    entities.append(SlacSpeakerCodeButton(coordinator))
    added_scene_ids: set[str] = set()
    for scene in coordinator.scenes or []:
        scene_id = str(scene.get("sceneId") or scene.get("id") or "")
        name = str(scene.get("name") or "")
        if not scene_id or scene_id in added_scene_ids:
            continue
        if INTERNAL_SCENE_NAME_TOKEN in name:
            continue
        added_scene_ids.add(scene_id)
        entities.append(SlacSceneButton(coordinator, scene_id, name))

    _LOGGER.info("SLAC button creating %d entities (scenes=%d)",
                 len(entities), len(added_scene_ids))
    if entities:
        async_add_entities(entities)

    # 场景在首次刷新后才加载到 coordinator 时，补建实体
    def _add_late_scenes() -> None:
        late = []
        for scene in coordinator.scenes or []:
            scene_id = str(scene.get("sceneId") or scene.get("id") or "")
            name = str(scene.get("name") or "")
            if not scene_id or scene_id in added_scene_ids:
                continue
            if INTERNAL_SCENE_NAME_TOKEN in name:
                continue
            added_scene_ids.add(scene_id)
            late.append(SlacSceneButton(coordinator, scene_id, name))
        if late:
            _LOGGER.info("SLAC button adding %d late scenes", len(late))
            async_add_entities(late)

    if not coordinator.scenes:
        entry.async_on_unload(coordinator.async_add_listener(_add_late_scenes))


class SlacSceneButton(CoordinatorEntity, ButtonEntity):
    _attr_has_entity_name = False

    def __init__(self, coordinator: SlacCoordinator, scene_id: str, name: str) -> None:
        super().__init__(coordinator)
        self._scene_id = scene_id
        self._attr_unique_id = f"slac_scene_{scene_id}"
        self._attr_name = f"场景: {name}"
        self._attr_icon = "mdi:play-circle"
        iot_id = coordinator.devices[0].get("iotId", "") if coordinator.devices else ""
        self._attr_device_info = {
            "identifiers": {(DOMAIN, iot_id)},
        }

    async def async_press(self) -> None:
        try:
            await self.coordinator.api.async_fire_scene(self._scene_id)
            _LOGGER.info("触发场景 %s", self._scene_id)
            await self.coordinator.async_request_refresh()
        except Exception as e:  # noqa: BLE001
            _LOGGER.error("触发场景 %s 失败: %s", self._scene_id, e)


class SlacSpeakerCodeButton(CoordinatorEntity, ButtonEntity):
    _attr_has_entity_name = False

    def __init__(self, coordinator: SlacCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = "slac_speaker_code"
        self._attr_name = "获取音箱配对码"
        self._attr_icon = "mdi:speaker"
        iot_id = coordinator.devices[0].get("iotId", "") if coordinator.devices else ""
        self._attr_device_info = {
            "identifiers": {(DOMAIN, iot_id)},
        }
        self._vcode: str = ""

    @property
    def extra_state_attributes(self) -> dict:
        return {"vcode": self._vcode}

    async def async_press(self) -> None:
        try:
            self._vcode = await self.coordinator.api.async_get_speaker_code()
            _LOGGER.info("获取音箱配对码: %s", self._vcode or "(空)")
            self.async_write_ha_state()
        except Exception as e:  # noqa: BLE001
            _LOGGER.error("获取音箱配对码失败: %s", e)
