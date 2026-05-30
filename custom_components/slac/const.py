DOMAIN = "slac"
PLATFORM_NAME = "三菱智能空调"

CONF_IDENTITY_ID = "identity_id"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_IOT_TOKEN = "iot_token"
CONF_PHONE = "phone"
CONF_PASSWORD = "password"
CONF_PROVINCE = "province"
CONF_CITY = "city"
CONF_SUB_LOCALITY = "sub_locality"
CONF_ENABLE_WEATHER = "enable_weather"

DEVICE_TYPE_AC = 0

AC_MODE_HA_MAP = {
    0: "cool",
    1: "dry",
    2: "fan_only",
    3: "heat",
    4: "auto",
}

HA_MODE_TO_AC = {v: k for k, v in AC_MODE_HA_MAP.items() if k <= 4}

COORDINATOR_UPDATE_INTERVAL = 30