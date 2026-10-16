import asyncio
import json
import logging
import time
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SlacApi
from .const import (
    CONF_CITY,
    CONF_ENABLE_PUSH,
    CONF_ENABLE_WEATHER,
    CONF_IDENTITY_ID,
    CONF_IOT_TOKEN,
    CONF_IOT_TOKEN_EXPIRE,
    CONF_PASSWORD,
    CONF_PHONE,
    CONF_PROVINCE,
    CONF_REFRESH_TOKEN,
    CONF_SUB_LOCALITY,
    COORDINATOR_PUSH_FALLBACK_INTERVAL,
    COORDINATOR_UPDATE_INTERVAL,
    DEFAULT_IOT_TOKEN_EXPIRE,
    DOMAIN,
    PUSH_RETRY_INTERVAL,
)
from .mqtt_push import SlacPushClient

_LOGGER = logging.getLogger(__name__)

# 场景/通知配置等低频数据的刷新间隔（秒）
EXTRAS_REFRESH_INTERVAL = 1800

# 启动时最多等这么久去备好会话并跑完首轮刷新（单次请求 REQUEST_TIMEOUT=30，留出余量）
PRIME_TIMEOUT = 45

SERVICES_REGISTERED = False


def _get_platforms(entry: ConfigEntry) -> list[Platform]:
    platforms = [Platform.CLIMATE, Platform.SENSOR, Platform.SWITCH, Platform.BINARY_SENSOR, Platform.BUTTON]
    return platforms


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})

    async def _on_tokens_changed(tokens: dict):
        data = dict(entry.data)
        data[CONF_IDENTITY_ID] = tokens.get("identity_id", data.get(CONF_IDENTITY_ID, ""))
        data[CONF_REFRESH_TOKEN] = tokens.get("refresh_token", data.get(CONF_REFRESH_TOKEN, ""))
        iot_token = tokens.get("iot_token")
        if iot_token:
            data[CONF_IOT_TOKEN] = iot_token
        expire = tokens.get("iot_token_expire")
        if expire:
            data[CONF_IOT_TOKEN_EXPIRE] = int(expire)
        hass.config_entries.async_update_entry(entry, data=data)
        _LOGGER.info("Persisted refreshed tokens to config entry")

    session = aiohttp_client.async_get_clientsession(hass)
    identity_id = entry.data.get(CONF_IDENTITY_ID, "")
    refresh_token = entry.data.get(CONF_REFRESH_TOKEN, "")
    api = SlacApi(session, identity_id, refresh_token, on_token_refresh=_on_tokens_changed)

    phone = entry.data.get(CONF_PHONE, "")
    password = entry.data.get(CONF_PASSWORD, "")
    if phone and password:
        api.set_login_credentials(phone, password)
    stored_iot = entry.data.get(CONF_IOT_TOKEN, "")
    if stored_iot:
        # 按条目里存的真实到期时间恢复 token 寿命；旧条目没有该字段时按云端标称
        # 20h 兜底。v1.3.0 用 expires_in=0 把存下来的 token 一律标成"已过期"，
        # 启动即强制刷新；而那条刷新链路必然失败(26101)，失败分支还会把这份好
        # token 清空 —— 属性因此抓不到，空调实体一个都建不出来。
        stored_expire = entry.data.get(CONF_IOT_TOKEN_EXPIRE)
        try:
            expires_in = (
                max(0, int(stored_expire) - int(time.time()))
                if stored_expire
                else DEFAULT_IOT_TOKEN_EXPIRE
            )
        except (TypeError, ValueError):
            expires_in = DEFAULT_IOT_TOKEN_EXPIRE
        api.set_iot_token(stored_iot, expires_in=expires_in)
        _LOGGER.info("已恢复 IoT token，剩余有效期约 %s 秒", expires_in)

    devices = []
    if identity_id:
        try:
            devices = await api.async_get_device_list_custom()
            _LOGGER.info("Got %d devices from API", len(devices))
        except Exception as e:
            _LOGGER.warning("Failed to fetch device list: %s", e)

    province = entry.data.get(CONF_PROVINCE, "")
    city = entry.data.get(CONF_CITY, "")
    sub_locality = entry.data.get(CONF_SUB_LOCALITY, "")
    options_province = entry.options.get(CONF_PROVINCE, "")
    options_city = entry.options.get(CONF_CITY, "")
    options_sub = entry.options.get(CONF_SUB_LOCALITY, "")
    province = options_province or province
    city = options_city or city
    sub_locality = options_sub or sub_locality

    api.province = province
    api.city = city
    api.sub_locality = sub_locality

    coordinator = SlacCoordinator(hass, api, entry, devices)

    # 先把会话和首轮数据准备好，再建平台：climate 平台靠 coordinator.device_properties
    # 里的 Info{内机地址} 判断有哪些空调机，而这些属性必须拿有效 iotToken 才抓得到。
    # 原来是"后台刷新 + 立刻建平台"并发跑，属性还没到手平台就建完了，空调实体会整个缺失。
    try:
        await asyncio.wait_for(api.async_ensure_valid_token(), timeout=PRIME_TIMEOUT)
    except Exception as e:  # noqa: BLE001
        _LOGGER.warning("启动时准备会话失败，交由定时刷新重试：%s", e)

    try:
        await asyncio.wait_for(coordinator.async_refresh(), timeout=PRIME_TIMEOUT)
        _LOGGER.info("First coordinator refresh completed")
    except Exception as e:  # noqa: BLE001
        _LOGGER.warning("First coordinator refresh failed: %s", e)
        coordinator.last_update_success = False

    # 启动长连接推送（后台任务，失败不阻塞配置项加载）
    enable_push = entry.data.get(CONF_ENABLE_PUSH, True)
    if enable_push:
        hass.async_create_background_task(
            coordinator.async_setup_push(), "slac_push_setup")

    hass.data[DOMAIN][entry.entry_id] = coordinator
    _async_register_services(hass)
    await hass.config_entries.async_forward_entry_setups(entry, _get_platforms(entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator: SlacCoordinator | None = hass.data[DOMAIN].get(entry.entry_id)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, _get_platforms(entry))
    if unload_ok:
        if coordinator is not None:
            # stop() 内含 paho 网络收尾与 sleep，放线程池避免阻塞事件循环
            await hass.async_add_executor_job(coordinator.async_stop_push)
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


def _async_register_services(hass: HomeAssistant) -> None:
    """注册集成级服务（全局一次）"""
    global SERVICES_REGISTERED
    if SERVICES_REGISTERED:
        return
    SERVICES_REGISTERED = True

    async def _handle_fire_scene(call: ServiceCall) -> dict:
        entry_id = call.data.get("entry_id") or next(iter(hass.data.get(DOMAIN, {})), None)
        coordinator = hass.data.get(DOMAIN, {}).get(entry_id)
        if coordinator is None:
            raise ValueError("未找到 SLAC 配置项")
        scene_id = call.data["scene_id"]
        result = await coordinator.api.async_fire_scene(scene_id)
        await coordinator.async_request_refresh()
        return {"result": result}

    hass.services.async_register(
        DOMAIN, "fire_scene", _handle_fire_scene,
        schema=None, supports_response=SupportsResponse.OPTIONAL)

    async def _handle_get_speaker_code(call: ServiceCall) -> dict:
        entry_id = call.data.get("entry_id") or next(iter(hass.data.get(DOMAIN, {})), None)
        coordinator = hass.data.get(DOMAIN, {}).get(entry_id)
        if coordinator is None:
            raise ValueError("未找到 SLAC 配置项")
        code = await coordinator.api.async_get_speaker_code()
        return {"vcode": code}

    hass.services.async_register(
        DOMAIN, "get_speaker_code", _handle_get_speaker_code,
        schema=None, supports_response=SupportsResponse.OPTIONAL)


class SlacCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, api: SlacApi, entry: ConfigEntry, devices: list = None) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=COORDINATOR_UPDATE_INTERVAL),
        )
        self.api = api
        self.entry = entry
        self.devices: list[dict] = devices or []
        self.device_properties: dict[str, dict] = {}
        self.device_detail: dict = {}
        # 长连接推送
        self.push_client: SlacPushClient | None = None
        self.push_enabled = entry.data.get(CONF_ENABLE_PUSH, True)
        self.push_bound = False
        self._push_setup_done = False
        self._push_starting = False
        self._last_push_retry = 0.0
        # 低频扩展数据（场景/定时/通知配置）
        self.scenes: list[dict] = []
        self.timing_scenes: list[dict] = []
        self.notice_config: dict = {}
        self._last_extras_refresh = 0.0

    # ---------------- 长连接推送 ----------------

    async def async_setup_push(self) -> None:
        """启动长连接推送；失败则保持轮询并在后续轮询中按间隔重试"""
        if not self.push_enabled or self._push_setup_done or self._push_starting:
            return
        self._push_starting = True
        try:
            await self._async_setup_push_inner()
        finally:
            self._push_starting = False

    async def _async_setup_push_inner(self) -> None:
        if not self.api.iot_token:
            try:
                await self.api.async_refresh_iot_token()
            except Exception as e:  # noqa: BLE001
                _LOGGER.debug("推送启动前刷新 token 失败: %s", e)
        if not self.api.iot_token:
            _LOGGER.warning("无可用 iotToken，跳过长连接推送启动")
            return

        try:
            aepauth = await self.api.async_aepauth()
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning("aepauth 获取 MQTT 三元组失败（将保持轮询）: %s", e)
            self._last_push_retry = time.monotonic()
            return

        client = SlacPushClient(
            get_iot_token=lambda: self.api.iot_token,
            on_properties_pushed=self._handle_properties_push,
            on_bound=self._handle_push_bound,
        )
        self.push_client = client
        try:
            bound = await client.async_start(self.hass.loop, aepauth)
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning("长连接推送启动失败（将保持轮询）: %s", e)
            self._last_push_retry = time.monotonic()
            return
        self._push_setup_done = True
        self.push_bound = bool(bound)
        self._apply_push_interval()

    def _handle_push_bound(self, bound: bool) -> None:
        self.push_bound = bound
        self._apply_push_interval()

    def _apply_push_interval(self):
        """按推送状态调整轮询频率：绑定成功降频兜底，否则保持快速轮询"""
        if self.push_bound:
            new_interval = timedelta(seconds=COORDINATOR_PUSH_FALLBACK_INTERVAL)
        else:
            new_interval = timedelta(seconds=COORDINATOR_UPDATE_INTERVAL)
        if self.update_interval != new_interval:
            self.update_interval = new_interval
            _LOGGER.info("轮询间隔调整为 %s 秒（推送%s）",
                         int(new_interval.total_seconds()),
                         "已绑定" if self.push_bound else "未绑定")

    def _handle_properties_push(self, iot_id: str, items: dict) -> None:
        """收到属性推送：立即合并进本地缓存并通知实体"""
        if not iot_id or not items:
            return
        existing = self.device_properties.get(iot_id, {})
        merged = {**existing, **items}
        # 深合并单元内属性：推送可能只带变化字段，需与已有值叠加
        for key, val in items.items():
            old = existing.get(key)
            if isinstance(old, dict) and isinstance(val, dict):
                merged[key] = {**old, **val}
        self.device_properties[iot_id] = merged
        _LOGGER.debug("推送合并属性 iot_id=%s keys=%s", iot_id, list(items.keys()))
        self.async_update_listeners()

    def async_stop_push(self) -> None:
        if self.push_client is not None:
            try:
                self.push_client.stop()
            except Exception:  # noqa: BLE001
                pass
            self.push_client = None
        self.push_bound = False

    async def _async_refresh_extras(self) -> None:
        """低频刷新场景/定时/通知配置（30 分钟一次，失败不阻塞主刷新）"""
        now = time.monotonic()
        if now - self._last_extras_refresh < EXTRAS_REFRESH_INTERVAL:
            return
        self._last_extras_refresh = now
        iot_id = self.devices[0].get("iotId", "") if self.devices else ""
        try:
            self.scenes = await self.api.async_get_scenes()
            _LOGGER.debug("刷新场景 %d 个", len(self.scenes))
        except Exception as e:  # noqa: BLE001
            _LOGGER.debug("刷新场景失败: %s", e)
        if iot_id:
            try:
                self.timing_scenes = await self.api.async_get_timing_scenes(iot_id)
            except Exception as e:  # noqa: BLE001
                _LOGGER.debug("刷新定时场景失败: %s", e)
        try:
            self.notice_config = await self.api.async_get_notice_config()
        except Exception as e:  # noqa: BLE001
            _LOGGER.debug("刷新通知配置失败: %s", e)

    async def _async_update_data(self) -> dict:
        try:
            # 推送不可用时按间隔重试启动
            if (self.push_enabled and not self.push_bound
                    and time.monotonic() - self._last_push_retry > PUSH_RETRY_INTERVAL):
                await self.async_setup_push()

            # 会话续期：token 缺失或临近过期（剩余 <1h）时确保有一个可用的 iotToken。
            # 刷新链路走不通会自动回落到账号密码重新登录，且不会清掉现有 token。
            if not self.api.iot_token or self.api.is_token_expiring():
                if await self.api.async_ensure_valid_token():
                    _LOGGER.debug("IoT token 已续期")
                else:
                    _LOGGER.warning("IoT token 续期失败，本轮数据可能不完整")

            try:
                device_list = await self.api.async_get_device_list_custom()
                if device_list:
                    self.devices = device_list
                    _LOGGER.info("Got %d devices from custom API", len(self.devices))
            except Exception as e:
                _LOGGER.warning("Custom device list failed, using cached: %s", e)

            if not self.devices:
                raise UpdateFailed("No devices available")

            if self.api.iot_token:
                # 所有设备共享同一个 iotId，一次 API 调用即可获取全部属性
                iot_id = self.devices[0].get("iotId", "")
                if iot_id:
                    try:
                        props = await self.api.async_get_properties(iot_id)
                        if isinstance(props, dict):
                            parsed = {}
                            for key, val in props.items():
                                if isinstance(val, dict) and "value" in val:
                                    try:
                                        inner = json.loads(val["value"])
                                        if isinstance(inner, dict):
                                            parsed[key] = inner
                                        else:
                                            parsed[key] = val
                                    except (json.JSONDecodeError, TypeError):
                                        parsed[key] = val
                                else:
                                    parsed[key] = val
                            self.device_properties[iot_id] = parsed
                    except Exception as e:
                        _LOGGER.warning("Failed to get properties: %s", e)

                if iot_id and not getattr(self, '_log_props_dumped', False):
                    if iot_id in self.device_properties:
                        _LOGGER.info("Full device properties for %s: %s", iot_id, self.device_properties[iot_id])
                        self._log_props_dumped = True

            weather = {}
            # 仅在配置了地区时才请求天气 API，避免空参数白跑一次
            if self.api.province or self.api.city:
                try:
                    weather = await self.api.async_get_weather(
                        self.api.province,
                        self.api.city,
                        self.api.sub_locality,
                    ) or {}
                except Exception as e:
                    _LOGGER.debug("Weather fetch failed: %s", e)
            else:
                _LOGGER.debug("Skipping weather request: no location configured")

            if not self.device_detail:
                try:
                    binding_info = await self.api.async_list_binding_by_account()
                    if binding_info and "data" in binding_info:
                        binding_data = binding_info["data"]
                        _LOGGER.debug("listBindingByAccount data type: %s, len=%s", type(binding_data).__name__, len(binding_data) if hasattr(binding_data, '__len__') else 'N/A')
                        # data 可能是列表（直接是绑定列表）或字典（含 data 字段）
                        if isinstance(binding_data, list) and binding_data:
                            first = binding_data[0]
                            _LOGGER.debug("First item type: %s, keys=%s", type(first).__name__, list(first.keys()) if isinstance(first, dict) else 'not dict')
                            if isinstance(first, dict):
                                self.device_detail = first
                                _LOGGER.info("Got device detail: %s", self.device_detail.get("productName"))
                        elif isinstance(binding_data, dict):
                            inner = binding_data.get("data", [])
                            if inner and isinstance(inner, list):
                                self.device_detail = inner[0]
                                _LOGGER.info("Got device detail: %s", self.device_detail.get("productName"))
                except Exception as e:
                    _LOGGER.debug("Device detail fetch failed: %s", e)

            # 低频刷新场景/通知配置（内部 30 分钟限流）
            await self._async_refresh_extras()

            data = {
                "devices": self.devices,
                "properties": self.device_properties,
                "weather": weather,
                "device_detail": self.device_detail,
                "scenes": self.scenes,
                "timing_scenes": self.timing_scenes,
                "notice_config": self.notice_config,
                "push_bound": self.push_bound,
            }
            _LOGGER.info("Updated %d devices, %d properties, weather=%s, push=%s",
                         len(self.devices), len(self.device_properties), bool(weather),
                         "bound" if self.push_bound else "off")
            return data
        except Exception as e:
            raise UpdateFailed(f"Update failed: {e}") from e
