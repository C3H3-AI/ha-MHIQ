from homeassistant.const import Platform

DOMAIN = "slac"
PLATFORM_NAME = "三菱智能空调"
PLATFORMS = [Platform.CLIMATE, Platform.SENSOR]

CONF_IDENTITY_ID = "identity_id"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_IOT_TOKEN = "iot_token"
CONF_PHONE = "phone"
CONF_PASSWORD = "password"
CONF_PROVINCE = "province"
CONF_CITY = "city"
CONF_SUB_LOCALITY = "sub_locality"
CONF_ENABLE_WEATHER = "enable_weather"

BASE_URL = "https://slacapp2.mhaq.cn:8081/slzgweb"
IOT_API_HOST = "https://api.link.aliyun.com"
OA_HOST = "https://sdk.openaccount.aliyun.com"

APP_KEY = "34457410"
APP_SECRET = "6cf45cdbeaa4ce6faa204741f3d772ca"

TOKEN_REFRESH_INTERVAL = 3600
TOKEN_EXPIRE_THRESHOLD = 300

API_CREATE_SESSION = "/account/createSessionByAuthCode"
API_REGION_GET = "/living/account/region/get"
API_GET_DEVICE_LIST = "/uc/listBindingByAccount"
API_GET_PROPERTIES = "/thing/properties/get"
API_SET_PROPERTIES = "/thing/properties/set"
API_GET_PRODUCT_INFO = "/thing/productInfo/getByAppKey"
API_LOGIN = "/api/prd/login.json"
API_GET_USER_INFO = "/devUser/getUser"
API_GET_WEATHER = "/weather/getWeather"
API_ADD_DEVICE_LIST = "/devDevice/getDeviceList"
API_QUERY_DEVICE_INFO = "/thing/info/get"

DEVICE_TYPE_AC = 0
DEVICE_TYPE_HP = 1
DEVICE_TYPE_PAU = 2
DEVICE_TYPE_UNKNOWN = -1

DEVICE_TYPE_NAMES = {
    DEVICE_TYPE_AC: "空调",
    DEVICE_TYPE_HP: "水系统",
    DEVICE_TYPE_PAU: "新风",
}

DEVICE_TYPE_ICONS = {
    DEVICE_TYPE_AC: "mdi:air-conditioner",
    DEVICE_TYPE_HP: "mdi:water-pump",
    DEVICE_TYPE_PAU: "mdi:fan",
}

AC_WORK_MODES = {
    0: "制冷",
    1: "除湿",
    2: "送风",
    3: "制热",
    4: "自动",
    5: "Default0",
    6: "Default1",
    7: "Default2",
    8: "Default3",
    9: "Default4",
    10: "Default5",
    11: "Default6",
    12: "Default7",
    13: "Default8",
    14: "Default9",
}

AC_MODE_HA_MAP = {
    0: "cool",
    1: "dry",
    2: "fan_only",
    3: "heat",
    4: "auto",
}

HA_MODE_TO_AC = {v: k for k, v in AC_MODE_HA_MAP.items() if k <= 4}

MAX_RETRIES = 3
REQUEST_TIMEOUT = 30
COORDINATOR_UPDATE_INTERVAL = 30
