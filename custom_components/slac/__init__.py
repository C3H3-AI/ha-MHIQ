import json
import logging
from datetime import timedelta

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SlacApi
from .const import (
    CONF_CITY,
    CONF_ENABLE_WEATHER,
    CONF_IDENTITY_ID,
    CONF_IOT_TOKEN,
    CONF_PROVINCE,
    CONF_REFRESH_TOKEN,
    CONF_SUB_LOCALITY,
    COORDINATOR_UPDATE_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _get_platforms(entry: ConfigEntry) -> list[Platform]:
    platforms = [Platform.CLIMATE]
    if entry.data.get(CONF_ENABLE_WEATHER, True):
        platforms.append(Platform.SENSOR)
    return platforms


async def _get_location_from_hass(hass: HomeAssistant) -> tuple[str, str, str]:
    """从 HA 经纬度反查省市区的懒加载位置。

    使用 Nominatim 免费服务，结果应持久化到 entry.data 避免重复调用。
    """
    try:
        latitude = hass.config.latitude
        longitude = hass.config.longitude
        if not latitude or not longitude:
            return "", "", ""

        session = aiohttp_client.async_get_clientsession(hass)
        url = f"https://nominatim.openstreetmap.org/reverse?lat={latitude}&lon={longitude}&format=json&accept-language=zh-CN"
        headers = {"User-Agent": "slac-ha-integration/1.0"}
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                data = await resp.json()
                display_name = data.get("display_name", "")
                parts = [p.strip() for p in display_name.split(",")]
                if len(parts) >= 5:
                    province = parts[-3]
                    city = parts[-4]
                    district = parts[-5]
                    _LOGGER.info("Reverse geocoded: %s %s %s", province, city, district)
                    return province, city, district
                address = data.get("address", {})
                state = address.get("state", "")
                city = address.get("city", address.get("county", ""))
                suburb = address.get("suburb", address.get("town", address.get("village", "")))
                return state, city, suburb
        return "", "", ""
    except Exception as e:
        _LOGGER.warning("Reverse geocoding failed: %s", e)
        return "", "", ""


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    session = aiohttp_client.async_get_clientsession(hass)
    identity_id = entry.data.get(CONF_IDENTITY_ID, "")
    refresh_token = entry.data.get(CONF_REFRESH_TOKEN, "")
    api = SlacApi(session, identity_id, refresh_token)
    stored_iot = entry.data.get(CONF_IOT_TOKEN, "")
    if stored_iot:
        api.set_iot_token(stored_iot)
        _LOGGER.info("Using stored IoT token")
    elif refresh_token:
        try:
            await api.async_refresh_iot_token()
        except Exception as e:
            _LOGGER.warning("Initial token refresh failed: %s", e)

    devices = []
    device_list_str = entry.data.get("device_list", "")
    if device_list_str:
        try:
            devices = json.loads(device_list_str)
        except (json.JSONDecodeError, TypeError):
            _LOGGER.warning("Failed to parse device list from config")

    if not devices and identity_id:
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

    # 用户未配置地区时，尝试从 HA 经纬度反查并持久化
    location_persisted = False
    if not province and not city:
        ha_province, ha_city, ha_sub = await _get_location_from_hass(hass)
        province = province or ha_province
        city = city or ha_city
        sub_locality = sub_locality or ha_sub
        _LOGGER.info("Using HA location: %s %s %s", province, city, sub_locality)
        # 将反查结果持久化到 entry.data，避免每次重启重复调用 Nominatim
        if province or city:
            new_data = dict(entry.data)
            new_data[CONF_PROVINCE] = province
            new_data[CONF_CITY] = city
            new_data[CONF_SUB_LOCALITY] = sub_locality
            hass.config_entries.async_update_entry(entry, data=new_data)
            location_persisted = True
            _LOGGER.info("Persisted geocoded location to entry data")

    if not province and not city:
        _LOGGER.warning(
            "No location configured and HA geocoding failed. "
            "Weather data will be unavailable. "
            "Configure province/city in integration options."
        )

    api.province = province
    api.city = city
    api.sub_locality = sub_locality

    coordinator = SlacCoordinator(hass, api, entry, devices)
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as e:
        _LOGGER.warning("First refresh failed (token may be expired): %s", e)
        coordinator.last_update_success = False

    hass.data[DOMAIN][entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, _get_platforms(entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, _get_platforms(entry))
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


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

    async def _async_update_data(self) -> dict:
        try:
            if not self.api.iot_token:
                try:
                    await self.api.async_refresh_iot_token()
                except Exception as e:
                    _LOGGER.warning("Token refresh failed: %s", e)
            elif self.api.is_token_expiring():
                _LOGGER.info("IoT token expiring, refreshing...")
                try:
                    await self.api.async_refresh_iot_token()
                except Exception as e:
                    _LOGGER.warning("Token refresh failed: %s", e)

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
                for device in self.devices:
                    iot_id = device.get("iotId", "")
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
                            _LOGGER.debug("Failed to get props for %s: %s", iot_id, e)

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

            data = {"devices": self.devices, "properties": self.device_properties, "weather": weather, "device_detail": self.device_detail}
            _LOGGER.info("Updated %d devices, %d properties, weather=%s",
                         len(self.devices), len(self.device_properties), bool(weather))
            return data
        except Exception as e:
            raise UpdateFailed(f"Update failed: {e}") from e
