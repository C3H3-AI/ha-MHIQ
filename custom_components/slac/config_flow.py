import json
import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig

from .api import SlacApi, SlacAuthError
from .const import (
    CONF_CITY,
    CONF_ENABLE_WEATHER,
    CONF_IDENTITY_ID,
    CONF_IOT_TOKEN,
    CONF_PASSWORD,
    CONF_PHONE,
    CONF_PROVINCE,
    CONF_REFRESH_TOKEN,
    CONF_SUB_LOCALITY,
    DOMAIN,
    PLATFORM_NAME,
)

_LOGGER = logging.getLogger(__name__)


class SlacConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._identity_id: str = ""
        self._refresh_token: str = ""
        self._iot_token: str = ""
        self._phone: str = ""
        self._password: str = ""

    @staticmethod
    def async_get_options_flow(config_entry):
        return SlacOptionsFlow(config_entry)

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        return await self.async_step_login(user_input if user_input and CONF_PHONE in user_input else None)

    async def async_step_login(self, user_input: dict | None = None) -> FlowResult:
        errors = {}
        if user_input is not None:
            phone = user_input[CONF_PHONE]
            password = user_input[CONF_PASSWORD]
            session = aiohttp_client.async_get_clientsession(self.hass)
            api = SlacApi(session)
            try:
                login_result = await api.async_login(phone, password)
                _LOGGER.info("Login result: %s", login_result)
            except SlacAuthError as e:
                _LOGGER.error("Login failed: %s", e)
                errors["base"] = "login_failed"
            except Exception as e:
                _LOGGER.error("Login error: %s", e)
                errors["base"] = "cannot_connect"
            if not errors:
                self._identity_id = api.identity_id
                self._refresh_token = api.refresh_token
                self._iot_token = api.iot_token
                self._phone = user_input[CONF_PHONE]
                self._password = user_input[CONF_PASSWORD]
                self._enable_weather = user_input.get(CONF_ENABLE_WEATHER, True)
                return await self._finalize()
        return self.async_show_form(
            step_id="login",
            data_schema=vol.Schema({
                vol.Required(CONF_PHONE): TextSelector(TextSelectorConfig(type="text")),
                vol.Required(CONF_PASSWORD): TextSelector(TextSelectorConfig(type="password")),
                vol.Optional(CONF_ENABLE_WEATHER, default=True): bool,
            }),
            errors=errors,
            description_placeholders={"name": PLATFORM_NAME},
        )

    async def _finalize(self) -> FlowResult:
        if not self._enable_weather:
            return await self._async_create_entry()
        return await self.async_step_location()

    async def _async_create_entry(self) -> FlowResult:
        session = aiohttp_client.async_get_clientsession(self.hass)
        api = SlacApi(session, self._identity_id, self._refresh_token)
        if self._iot_token:
            api.set_iot_token(self._iot_token)

        devices = []
        try:
            devices = await api.async_get_device_list_custom()
        except Exception as e:
            _LOGGER.warning("Could not fetch device list: %s", e)

        data = {
            CONF_IDENTITY_ID: self._identity_id,
            CONF_REFRESH_TOKEN: self._refresh_token,
            CONF_ENABLE_WEATHER: self._enable_weather,
            CONF_PROVINCE: "",
            CONF_CITY: "",
            CONF_SUB_LOCALITY: "",
            CONF_PHONE: self._phone,
            CONF_PASSWORD: self._password,
        }
        if self._iot_token:
            data[CONF_IOT_TOKEN] = self._iot_token
        if devices:
            data["device_count"] = len(devices)
            data["device_list"] = json.dumps(devices)

        _LOGGER.info("Creating entry with data keys: %s (weather=%s)", list(data.keys()), self._enable_weather)
        return self.async_create_entry(title="三菱智能空调 (Mitsubishi Smart AC)", data=data)

    async def async_step_location(self, user_input: dict | None = None) -> FlowResult:
        errors = {}
        if user_input is not None:
            province = user_input.get(CONF_PROVINCE, "")
            city = user_input.get(CONF_CITY, "")
            sub_locality = user_input.get(CONF_SUB_LOCALITY, "")
            if not province and not city:
                _LOGGER.warning("Location empty, disabling weather service")
                self._enable_weather = False
                return await self._async_create_entry()

            session = aiohttp_client.async_get_clientsession(self.hass)
            api = SlacApi(session, self._identity_id, self._refresh_token)
            if self._iot_token:
                api.set_iot_token(self._iot_token)

            devices = []
            try:
                devices = await api.async_get_device_list_custom()
            except Exception as e:
                _LOGGER.warning("Could not fetch device list: %s", e)

            data = {
                CONF_IDENTITY_ID: self._identity_id,
                CONF_REFRESH_TOKEN: self._refresh_token,
                CONF_ENABLE_WEATHER: self._enable_weather,
                CONF_PROVINCE: province,
                CONF_CITY: city,
                CONF_SUB_LOCALITY: sub_locality,
                CONF_PHONE: self._phone,
                CONF_PASSWORD: self._password,
            }
            if self._iot_token:
                data[CONF_IOT_TOKEN] = self._iot_token
            if devices:
                data["device_count"] = len(devices)
                data["device_list"] = json.dumps(devices)

            _LOGGER.info("Creating entry with data keys: %s", list(data.keys()))
            return self.async_create_entry(title="三菱智能空调 (Mitsubishi Smart AC)", data=data)

        return self.async_show_form(
            step_id="location",
            data_schema=vol.Schema({
                vol.Optional(CONF_PROVINCE, default=""): TextSelector(TextSelectorConfig(type="text")),
                vol.Optional(CONF_CITY, default=""): TextSelector(TextSelectorConfig(type="text")),
                vol.Optional(CONF_SUB_LOCALITY, default=""): TextSelector(TextSelectorConfig(type="text")),
            }),
            errors=errors,
            description_placeholders={"name": "天气地区设置（留空则不启用）"},
        )


class SlacOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry):
        self._reload_after_location = False

    async def async_step_init(self, user_input: dict | None = None) -> FlowResult:
        if user_input is not None:
            action = user_input.get("action", "location")
            if action == "relogin":
                return await self.async_step_relogin()
            if action == "weather_toggle":
                return await self.async_step_weather_toggle()
            return await self.async_step_location(None)

        current_weather = self.config_entry.data.get(CONF_ENABLE_WEATHER, True)
        weather_status = "已开启" if current_weather else "已关闭"
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required("action", default="location"): vol.In({
                    "location": "设置天气地区",
                    "weather_toggle": f"天气服务（当前{weather_status}）",
                    "relogin": "重新登录（手机+密码）",
                }),
            }),
        )

    async def async_step_weather_toggle(self, user_input: dict | None = None) -> FlowResult:
        if user_input is not None:
            data = dict(self.config_entry.data)
            data[CONF_ENABLE_WEATHER] = user_input[CONF_ENABLE_WEATHER]
            self.hass.config_entries.async_update_entry(self.config_entry, data=data)

            if user_input[CONF_ENABLE_WEATHER]:
                has_province = data.get(CONF_PROVINCE, "") or self.config_entry.options.get(CONF_PROVINCE, "")
                has_city = data.get(CONF_CITY, "") or self.config_entry.options.get(CONF_CITY, "")
                if not has_province and not has_city:
                    self._reload_after_location = True
                    return await self.async_step_location()

            await self.hass.config_entries.async_reload(self.config_entry.entry_id)
            return self.async_create_entry(title="", data={})

        current = self.config_entry.data.get(CONF_ENABLE_WEATHER, True)
        return self.async_show_form(
            step_id="weather_toggle",
            data_schema=vol.Schema({
                vol.Required(CONF_ENABLE_WEATHER, default=current): bool,
            }),
            description_placeholders={"current": "开启" if current else "关闭"},
        )

    async def async_step_location(self, user_input: dict | None = None) -> FlowResult:
        if user_input is not None:
            data = dict(self.config_entry.data)
            data[CONF_PROVINCE] = user_input.get(CONF_PROVINCE, "")
            data[CONF_CITY] = user_input.get(CONF_CITY, "")
            data[CONF_SUB_LOCALITY] = user_input.get(CONF_SUB_LOCALITY, "")
            if self._reload_after_location:
                self._reload_after_location = False
                if not data.get(CONF_PROVINCE, "") and not data.get(CONF_CITY, ""):
                    data[CONF_ENABLE_WEATHER] = False
                self.hass.config_entries.async_update_entry(self.config_entry, data=data)
                await self.hass.config_entries.async_reload(self.config_entry.entry_id)
            else:
                self.hass.config_entries.async_update_entry(self.config_entry, data=data)
            return self.async_create_entry(title="", data={})
        current_province = self.config_entry.data.get(CONF_PROVINCE, "")
        current_city = self.config_entry.data.get(CONF_CITY, "")
        current_sub = self.config_entry.data.get(CONF_SUB_LOCALITY, "")
        return self.async_show_form(
            step_id="location",
            data_schema=vol.Schema({
                vol.Optional(CONF_PROVINCE, default=current_province): TextSelector(TextSelectorConfig(type="text")),
                vol.Optional(CONF_CITY, default=current_city): TextSelector(TextSelectorConfig(type="text")),
                vol.Optional(CONF_SUB_LOCALITY, default=current_sub): TextSelector(TextSelectorConfig(type="text")),
            }),
            description_placeholders={"name": "天气地区设置（留空则不启用）"},
        )

    async def async_step_relogin(self, user_input: dict | None = None) -> FlowResult:
        errors = {}
        if user_input is not None:
            phone = user_input[CONF_PHONE]
            password = user_input[CONF_PASSWORD]
            session = aiohttp_client.async_get_clientsession(self.hass)
            api = SlacApi(session)
            try:
                await api.async_login(phone, password)
                data = dict(self.config_entry.data)
                data[CONF_IDENTITY_ID] = api.identity_id
                data[CONF_REFRESH_TOKEN] = api.refresh_token
                data[CONF_IOT_TOKEN] = api.iot_token
                self.hass.config_entries.async_update_entry(self.config_entry, data=data)
                await self.hass.config_entries.async_reload(self.config_entry.entry_id)
                return self.async_create_entry(title="", data={})
            except SlacAuthError as e:
                _LOGGER.error("Re-login failed: %s", e)
                errors["base"] = "login_failed"
            except Exception as e:
                _LOGGER.error("Re-login error: %s", e)
                errors["base"] = "cannot_connect"
        return self.async_show_form(
            step_id="relogin",
            data_schema=vol.Schema({
                vol.Required(CONF_PHONE): TextSelector(TextSelectorConfig(type="text")),
                vol.Required(CONF_PASSWORD): TextSelector(TextSelectorConfig(type="password")),
            }),
            errors=errors,
        )
