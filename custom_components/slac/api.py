"""
SLAC API 客户端 - V3 手动 Token 模式
用户需要从手机抓包获取 identityId + refreshToken 配置集成
"""
import asyncio
import base64
import hashlib
import hmac
import json
import logging
import time
import uuid
from datetime import datetime
from typing import Any, Callable, Optional
from urllib.parse import quote

import aiohttp

_LOGGER = logging.getLogger(__name__)

APP_KEY = "34457410"
APP_SECRET = "6cf45cdbeaa4ce6faa204741f3d772ca"
IOT_API_HOST = "https://api.link.aliyun.com"
OA_API_HOST = "https://sdk.openaccount.aliyun.com"
BASE_URL = "https://slacapp2.mhaq.cn:8081/slzgweb"

API_LOGIN_OA = "/api/prd/login.json"
API_CREATE_SESSION = "/account/createSessionByAuthCode"
API_IOT_DEVICE_LIST = "/uc/listBindingByAccount"
API_GET_PROPERTIES = "/thing/properties/get"
API_SET_PROPERTIES = "/thing/properties/set"
API_GET_PRODUCT_INFO = "/thing/productInfo/getByAppKey"
API_CUSTOM_DEVICE_LIST = "/devDevice/getDeviceList"

REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
TOKEN_EXPIRE_THRESHOLD = 300


class SlacAuthError(Exception):
    pass


class SlacApiError(Exception):
    pass


def make_iot_request_body(api_ver: str, params: dict, iot_token: str = "") -> str:
    request_id = str(uuid.uuid4())
    body = {
        "a": request_id,
        "b": "1.0",
        "c": {"apiVer": api_ver, "language": "zh-CN"},
        "d": params,
        "id": request_id,
        "params": {"$ref": "$.d"},
        "request": {"$ref": "$.c"},
        "version": "1.0",
    }
    if iot_token:
        body["c"]["iotToken"] = iot_token
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"))


def compute_iot_headers(path: str, body: str = "", method: str = "POST", content_type: str = "application/octet-stream; charset=utf-8") -> dict:
    accept = "application/json; charset=utf-8"
    content_md5 = ""
    if body:
        content_md5 = base64.b64encode(hashlib.md5(body.encode("utf-8")).digest()).decode()
    x_ca_nonce = str(uuid.uuid4())
    x_ca_timestamp = str(int(time.time() * 1000))
    date_str = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT")

    sign_header_names = ["x-ca-key", "x-ca-nonce", "x-ca-signature-method", "x-ca-timestamp"]
    canonicalized_headers = "".join(f"{name}:{APP_KEY if name == 'x-ca-key' else (x_ca_nonce if name == 'x-ca-nonce' else (x_ca_timestamp if name == 'x-ca-timestamp' else 'HmacSHA1'))}\n" for name in sorted(sign_header_names))

    string_to_sign = (
        method.upper() + "\n"
        + accept + "\n"
        + content_md5 + "\n"
        + content_type + "\n"
        + date_str + "\n"
        + canonicalized_headers
        + path
    )

    signature = hmac.new(
        APP_SECRET.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        hashlib.sha1,
    ).digest()
    signature_b64 = base64.b64encode(signature).decode("utf-8")

    headers = {
        "Content-Type": content_type,
        "Accept": accept,
        "Date": date_str,
        "x-ca-key": APP_KEY,
        "x-ca-nonce": x_ca_nonce,
        "x-ca-timestamp": x_ca_timestamp,
        "x-ca-signature-method": "HmacSHA1",
        "x-ca-signature": signature_b64,
        "x-ca-signature-headers": ",".join(sign_header_names),
        "User-Agent": "ALIYUN-ANDROID-DEMO",
    }
    if content_md5:
        headers["Content-MD5"] = content_md5
    headers["ca_version"] = "1"
    return headers


def compute_cloudapi_headers(path: str, body: str, form_params: dict) -> dict:
    accept = "application/json; charset=UTF-8"
    content_type = "application/x-www-form-urlencoded; charset=UTF-8"
    content_md5 = base64.b64encode(hashlib.md5(body.encode("utf-8")).digest()).decode()
    date_str = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT")
    x_ca_nonce = str(uuid.uuid4())
    x_ca_timestamp = str(int(time.time() * 1000))

    ca_header_dict = {
        "x-ca-key": APP_KEY,
        "x-ca-nonce": x_ca_nonce,
        "x-ca-signature-method": "HmacSHA1",
        "x-ca-timestamp": x_ca_timestamp,
    }
    sorted_keys = sorted(ca_header_dict.keys())
    ca_headers = "".join(f"{k}:{ca_header_dict[k]}\n" for k in sorted_keys)

    sorted_params = sorted(form_params.items())
    resource_path = path + "?" + "&".join(f"{k}={v}" for k, v in sorted_params)

    string_to_sign = (
        "POST\n" + accept + "\n" + content_md5 + "\n"
        + content_type + "\n" + date_str + "\n"
        + ca_headers + resource_path
    )

    mac = hmac.new(APP_SECRET.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha1).digest()
    signature = base64.b64encode(mac).decode("utf-8")

    return {
        "Content-Type": content_type,
        "Accept": accept,
        "Date": date_str,
        "x-ca-key": APP_KEY,
        "x-ca-nonce": x_ca_nonce,
        "x-ca-timestamp": x_ca_timestamp,
        "X-Ca-Signature-Method": "HmacSHA1",
        "x-ca-signature": signature,
        "x-ca-signature-headers": ",".join(sorted_keys),
        "User-Agent": "ALIYUN-ANDROID-DEMO",
        "Content-MD5": content_md5,
        "CA_VERSION": "1",
    }


class SlacApi:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        identity_id: str = "",
        refresh_token: str = "",
        on_token_refresh: Optional[Callable] = None,
    ):
        self._session = session
        self._identity_id = identity_id
        self._refresh_token = refresh_token
        self._iot_token = ""
        self._iot_token_expire = 0
        self._on_token_refresh = on_token_refresh

    async def _iot_request(self, path: str, body: str, retry: int = 0) -> dict:
        url = f"{IOT_API_HOST}{path}"
        headers = compute_iot_headers(path, body)
        try:
            async with self._session.post(
                url, headers=headers, data=body,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                text = await resp.text()
                if resp.status != 200:
                    raise SlacApiError(f"IoT API error {resp.status}: {text[:300]}")
                data = json.loads(text)
                code = data.get("code")
                if code not in (200, 20000, None):
                    msg = data.get("message", data.get("msg", "unknown"))
                    raise SlacApiError(f"IoT API error: {msg} (code={code})")
                return data.get("data", data)
        except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError) as e:
            if retry < MAX_RETRIES:
                _LOGGER.warning("IoT request retry %d/%d: %s", retry + 1, MAX_RETRIES, e)
                await asyncio.sleep(2 ** retry)
                return await self._iot_request(path, body, retry + 1)
            raise SlacApiError(f"IoT request failed: {e}")

    async def _custom_request(self, endpoint: str, params: dict = None) -> dict:
        url = f"{BASE_URL}{endpoint}"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 12)",
        }
        try:
            async with self._session.post(
                url, headers=headers, data=params,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                text = await resp.text()
                if resp.status != 200:
                    raise SlacApiError(f"Custom API {resp.status}: {text[:200]}")
                return json.loads(text)
        except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError) as e:
            raise SlacApiError(f"Custom request failed: {e}")

    async def _oa_request(self, path: str, form_params: dict, retry: int = 0) -> dict:
        sorted_params = sorted(form_params.items())
        body = "&".join(f"{quote(k, safe='')}={quote(v, safe='')}" for k, v in sorted_params)
        headers = compute_cloudapi_headers(path, body, form_params)
        url = f"{OA_API_HOST}{path}"
        try:
            async with self._session.post(
                url, headers=headers, data=body.encode("utf-8"),
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                raw = await resp.read()
                if resp.status != 200:
                    raise SlacAuthError(f"OA API error {resp.status}: {raw[:300]}")
                data = json.loads(raw)
                inner = data.get("data", {})
                if inner.get("code") != 1:
                    msg = inner.get("message", "unknown")
                    raise SlacAuthError(f"OA login failed: {msg}")
                return data
        except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError) as e:
            if retry < MAX_RETRIES:
                _LOGGER.warning("OA request retry %d/%d: %s", retry + 1, MAX_RETRIES, e)
                await asyncio.sleep(2 ** retry)
                return await self._oa_request(path, form_params, retry + 1)
            raise SlacAuthError(f"OA request failed: {e}")

    async def async_login(self, phone: str, password: str) -> dict:
        encrypted_pwd = rsa_encrypt_password(password)
        login_json = json.dumps({
            "password": encrypted_pwd,
            "loginId": phone,
            "riskControlInfo": {
                "appVersion": "47",
                "USE_OA_PWD_ENCRYPT": "true",
                "utdid": "ffffffffffffffffffffffff",
                "netType": "wifi",
                "locale": "zh_CN",
                "appVersionName": "V2.1.8",
                "deviceId": str(uuid.uuid4()),
                "platformVersion": "32",
                "appAuthToken": "",
                "appID": "com.limap.slac",
                "signType": "RSA",
                "sdkVersion": "3.4.2",
                "model": "SM-G9900",
                "USE_H5_NC": "false",
                "platformName": "android",
                "brand": "Samsung",
                "yunOSId": "",
            }
        }, ensure_ascii=False, separators=(",", ":")).replace("/", "\\/")
        form_params = {"loginRequest": login_json}
        oa_data = await self._oa_request(API_LOGIN_OA, form_params)
        inner_data = oa_data.get("data", {}).get("data", {})
        login_result = inner_data.get("loginSuccessResult", {})
        auth_code = login_result.get("sid")
        if not auth_code:
            raise SlacAuthError(f"No sid in OA response: {oa_data}")
        result = await self.async_create_session(auth_code)
        return result

    async def async_create_session(self, auth_code: str) -> dict:
        body = make_iot_request_body(
            api_ver="1.0.4",
            params={
                "request": {
                    "authCode": auth_code,
                    "accountType": "OA_SESSION",
                    "appKey": APP_KEY,
                }
            },
        )
        result = await self._iot_request(API_CREATE_SESSION, body)
        if isinstance(result, dict):
            self._identity_id = result.get("identityId", self._identity_id)
            self._iot_token = result.get("iotToken", self._iot_token)
            self._refresh_token = result.get("refreshToken", self._refresh_token)
            self._iot_token_expire = int(time.time()) + result.get("iotTokenExpire", 72000)
            if self._on_token_refresh:
                await self._on_token_refresh({
                    "identity_id": self._identity_id,
                    "refresh_token": self._refresh_token,
                })
        return result

    async def async_refresh_iot_token(self) -> bool:
        if not self._refresh_token:
            _LOGGER.error("No refresh token available")
            return False
        try:
            body = make_iot_request_body(
                api_ver="1.0.4",
                params={
                    "request": {
                        "authCode": self._refresh_token,
                        "accountType": "OA_SESSION",
                        "appKey": APP_KEY,
                    }
                },
            )
            result = await self._iot_request(API_CREATE_SESSION, body)
            if isinstance(result, dict):
                new_iot = result.get("iotToken")
                new_refresh = result.get("refreshToken")
                new_identity = result.get("identityId")
                if new_iot:
                    self._iot_token = new_iot
                    self._iot_token_expire = int(time.time()) + result.get("iotTokenExpire", 72000)
                if new_refresh:
                    self._refresh_token = new_refresh
                if new_identity:
                    self._identity_id = new_identity
                if self._on_token_refresh:
                    await self._on_token_refresh({
                        "identity_id": self._identity_id,
                        "refresh_token": self._refresh_token,
                    })
                return bool(self._iot_token)
            return False
        except Exception as e:
            _LOGGER.error("Token refresh failed: %s", e)
            return False

    async def async_get_device_list(self) -> list:
        body = make_iot_request_body(
            api_ver="1.0.2",
            params={"pageSize": 1000, "pageNo": 1},
            iot_token=self._iot_token,
        )
        result = await self._iot_request(API_IOT_DEVICE_LIST, body)
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return result.get("list", [])
        return []

    async def async_get_device_list_custom(self) -> list:
        """使用 SLAC 自定义 API 获取设备列表（仅需 identityId）"""
        result = await self._custom_request(API_CUSTOM_DEVICE_LIST, {"identityId": self._identity_id})
        device_list = result.get("data", {}).get("deviceList", [])
        if not device_list and isinstance(result, list):
            device_list = result
        return device_list

    async def async_get_properties(self, iot_id: str) -> dict:
        body = make_iot_request_body(
            api_ver="1.0.2",
            params={"iotId": iot_id},
            iot_token=self._iot_token,
        )
        return await self._iot_request(API_GET_PROPERTIES, body)

    async def async_set_properties(self, iot_id: str, items: dict) -> dict:
        body = make_iot_request_body(
            api_ver="1.0.2",
            params={"items": items, "iotId": iot_id},
            iot_token=self._iot_token,
        )
        return await self._iot_request(API_SET_PROPERTIES, body)

    async def async_get_weather(self, province: str = "", city: str = "", sub_locality: str = "") -> dict | None:
        url = f"{BASE_URL}/weather/getWeather"
        data = {
            "province": province,
            "city": city,
            "subLocality": sub_locality,
        }
        resp = await self._custom_request("/weather/getWeather", data)
        if resp.get("success"):
            return resp.get("data", {})
        return None

    async def async_list_binding_by_account(self) -> dict | None:
        body = make_iot_request_body(
            api_ver="1.0.2",
            params={"pageSize": 1000, "pageNo": 1},
            iot_token=self._iot_token,
        )
        resp = await self._iot_request("/uc/listBindingByAccount", body)
        if resp and "data" in resp:
            return resp
        return None

    def set_credentials(self, identity_id: str, refresh_token: str):
        self._identity_id = identity_id
        self._refresh_token = refresh_token

    def set_iot_token(self, iot_token: str, expires_in: int = 72000):
        self._iot_token = iot_token
        self._iot_token_expire = int(time.time()) + expires_in

    @property
    def identity_id(self) -> str:
        return self._identity_id

    @property
    def refresh_token(self) -> str:
        return self._refresh_token

    @property
    def iot_token(self) -> str:
        return self._iot_token

    def is_token_expiring(self) -> bool:
        return (self._iot_token_expire - int(time.time())) < TOKEN_EXPIRE_THRESHOLD


def rsa_encrypt_password(password: str) -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.backends import default_backend

    RSA_PUB_KEY_B64 = "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAl4EFDk91/ArPHjyX7UBzofPTAD3pcP8FMgOs83hvLEcbFJOVASrPAjbJTuXsSZJd9tYPwKbuqlGqndvdl2Kn2zLFpLOcFAYOyaIDFzDOCWQw/kMjcm1U08BvPE7dbtkGM23lCyTBlDMHWJvUz3JVTZm6ApGWEOGRhs1rECjcS9HXttnllQ2gTtBAW5Xjb8tzDgWR0jMaHzduCcSimHPtQO4Osh4Op3ianRocbb9o/4OR8HgKdbaKO3Sq2+pYV7FveXmfXqUr5lH7oHji+4j5TaU4WXRGKOjHSVXtN0UrfCXtsWE0aGCXXQN78NJUf5VrJMh14mqiSrR07wgu3UG7OwIDAQAB"

    pub_key_bytes = base64.b64decode(RSA_PUB_KEY_B64)
    public_key = serialization.load_der_public_key(pub_key_bytes)
    password_bytes = password.encode("utf-8")
    block_size = 245
    encrypted_blocks = []
    for i in range(0, len(password_bytes), block_size):
        block = password_bytes[i:i + block_size]
        encrypted = public_key.encrypt(block, padding.PKCS1v15())
        encrypted_blocks.append(encrypted)
    encrypted_data = b"".join(encrypted_blocks)
    return base64.b64encode(encrypted_data).decode()