"""
SLAC API 客户端 - 手机号密码登录模式
登录后自动获取 identityId / refreshToken / iotToken"""
import asyncio
import base64
import hashlib
import hmac
import json
import logging
import random
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
API_AEP_AUTH = "/app/aepauth/handle"
API_GET_SCENES = "/scene/list/get"
API_FIRE_SCENE = "/scene/fire"
API_GET_TIMING_SCENES = "/scene/timing/list/get"
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
TOKEN_EXPIRE_THRESHOLD = 1 * 3600  # 提前1小时刷新，与 const.py 一致


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
        self._phone: str = ""
        self._password: str = ""
        self._refresh_lock = asyncio.Lock()

    async def _iot_request(self, path: str, body: str) -> dict:
        url = f"{IOT_API_HOST}{path}"
        for attempt in range(MAX_RETRIES + 1):
            try:
                headers = compute_iot_headers(path, body)
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
                if attempt < MAX_RETRIES:
                    _LOGGER.warning("IoT request retry %d/%d: %s", attempt + 1, MAX_RETRIES, e)
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise SlacApiError(f"IoT request failed: {e}") from e

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

    async def _oa_request(self, path: str, form_params: dict) -> dict:
        url = f"{OA_API_HOST}{path}"
        for attempt in range(MAX_RETRIES + 1):
            try:
                sorted_params = sorted(form_params.items())
                body = "&".join(f"{quote(k, safe='')}={quote(v, safe='')}" for k, v in sorted_params)
                headers = compute_cloudapi_headers(path, body, form_params)
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
                if attempt < MAX_RETRIES:
                    _LOGGER.warning("OA request retry %d/%d: %s", attempt + 1, MAX_RETRIES, e)
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise SlacAuthError(f"OA request failed: {e}") from e

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
                    "iot_token": self._iot_token,
                    "iot_token_expire": self._iot_token_expire,
                })
        return result

    async def async_refresh_iot_token(self) -> bool:
        if not self._refresh_token:
            _LOGGER.error("No refresh token available")
            return False
        async with self._refresh_lock:
            # 二次检查：可能其他协程已经刷新完毕
            if self._iot_token and not self.is_token_expiring():
                _LOGGER.debug("Token already refreshed by another task, skipping")
                return True
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
                            "iot_token": self._iot_token,
                            "iot_token_expire": self._iot_token_expire,
                        })
                    return bool(self._iot_token)
                return False
            except Exception as e:
                # 这条失败只说明"用 refreshToken 换新会话"走不通：createSessionByAuthCode
                # 的 authCode 必须是 OA 登录返回的 sid（会话 Id），而 refreshToken 不是
                # 会话 Id，云端固定回 26101「会话 Id 不存在」。此时手上那份 iotToken
                # 很可能仍然可用，绝不能顺手清掉（清掉会导致属性抓不到、空调实体全丢）；
                # 确实需要换会话时，交给 async_ensure_valid_token() 用账号密码重新登录。
                _LOGGER.warning("Token refresh failed: %s", e)
                return False

    async def async_ensure_valid_token(self) -> bool:
        """确保手上有可用的 iotToken：先看现成的够不够用，再刷新，最后才重新登录。

        刷新（createSessionByAuthCode + refreshToken 冒充 OA 会话）在云端走不通，
        实测固定返回 26101「会话 Id 不存在」；真正可靠的办法是拿账号密码重新走一遍
        登录（OA 拿 sid → createSession），这条路才是换会话的正确姿势。
        """
        if self._iot_token and not self.is_token_expiring():
            return True
        if await self.async_refresh_iot_token():
            return True
        if not self.has_login_credentials():
            _LOGGER.warning("无可用 iotToken，且配置里没有账号密码，无法续期")
            return False
        _LOGGER.info("刷新 iotToken 走不通，改用账号密码重新登录换取新会话")
        if not await self.async_auto_login():
            _LOGGER.warning("重新登录失败，账号或密码可能已失效")
            return False
        return bool(self._iot_token)

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

    async def async_get_properties(self, iot_id: str, log_all: bool = False) -> dict:
        _LOGGER.info("Fetching properties for iot_id=%s", iot_id)
        body = make_iot_request_body(
            api_ver="1.0.2",
            params={"iotId": iot_id},
            iot_token=self._iot_token,
        )
        try:
            result = await self._iot_request(API_GET_PROPERTIES, body)
        except SlacApiError as e:
            _LOGGER.warning("IoT API auth error, invaliding token: %s", e)
            self.invalidate_iot_token()
            return {}
        except Exception as e:
            _LOGGER.warning("Failed to fetch properties: %s", e)
            return {}
        if log_all or _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("Full properties response: %s", result)
        return result

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

    async def async_aepauth(self) -> dict:
        """换取长连接 MQTT 三元组（productKey/deviceName/deviceSecret）

        来源：APP 的 MobileAuthHttpRequest → /app/aepauth/handle。
        外层 x-ca-key 固定用 APP_KEY（与通用 IoT 请求一致）；
        内层 authInfo.sign = HmacSHA1(APP_SECRET, appKey+clientId+deviceSn+timestamp) 小写 hex，
        appKey 用 x-ca 同一个 APP_KEY（实测通过）。
        deviceSn/clientId 每次会话随机生成，无需持久化。
        """
        device_sn = uuid.uuid4().hex
        client_id = uuid.uuid4().hex[:8]
        timestamp = str(int(time.time() * 1000))
        to_sign = (
            "appKey" + APP_KEY
            + "clientId" + client_id
            + "deviceSn" + device_sn
            + "timestamp" + timestamp
        )
        sign = hmac.new(APP_SECRET.encode("utf-8"), to_sign.encode("utf-8"), hashlib.sha1).hexdigest()
        body = json.dumps({
            "id": str(uuid.uuid4()),
            "version": "1.0",
            "request": {"apiVer": "1.0.0"},
            "params": {"authInfo": {
                "timestamp": timestamp,
                "clientId": client_id,
                "deviceSn": device_sn,
                "sign": sign,
            }},
        }, ensure_ascii=False, separators=(",", ":"))
        for attempt in range(MAX_RETRIES + 1):
            try:
                headers = compute_iot_headers(API_AEP_AUTH, body)
                async with self._session.post(
                    f"{IOT_API_HOST}{API_AEP_AUTH}", headers=headers, data=body,
                    timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                ) as resp:
                    text = await resp.text()
                    if resp.status != 200:
                        raise SlacApiError(f"aepauth error {resp.status}: {text[:300]}")
                    data = json.loads(text)
                    if data.get("code") != 200:
                        raise SlacApiError(f"aepauth failed: {data.get('message')} (code={data.get('code')})")
                    return data.get("data", {})
            except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError) as e:
                if attempt < MAX_RETRIES:
                    _LOGGER.warning("aepauth retry %d/%d: %s", attempt + 1, MAX_RETRIES, e)
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise SlacApiError(f"aepauth request failed: {e}") from e

    async def async_get_scenes(self) -> list:
        """获取云端场景列表（App /scene/list/get，apiVer 1.0.5，分页 50）"""
        scenes: list = []
        page_no = 1
        while page_no <= 10:  # 上限保护
            body = make_iot_request_body(
                api_ver="1.0.5",
                params={"group": "1", "pageNo": page_no, "pageSize": 50},
                iot_token=self._iot_token,
            )
            data = await self._iot_request(API_GET_SCENES, body)
            if not isinstance(data, dict):
                break
            batch = data.get("scenes") or []
            scenes.extend(batch)
            if not batch or len(scenes) >= int(data.get("total") or 0):
                break
            page_no += 1
        return scenes

    async def async_fire_scene(self, scene_id: str) -> dict:
        """手动执行（触发）一个场景"""
        body = make_iot_request_body(
            api_ver="1.0.2",
            params={"sceneId": scene_id},
            iot_token=self._iot_token,
        )
        return await self._iot_request(API_FIRE_SCENE, body)

    async def async_get_timing_scenes(self, iot_id: str) -> list:
        """获取定时场景列表（需 iotId）"""
        body = make_iot_request_body(
            api_ver="1.0.2",
            params={"iotId": iot_id, "pageNo": 1, "pageSize": 50},
            iot_token=self._iot_token,
        )
        data = await self._iot_request(API_GET_TIMING_SCENES, body)
        if isinstance(data, dict):
            return data.get("scenes") or []
        return []

    async def async_get_notice_config(self) -> dict:
        """获取通知开关配置（异常提醒/到家/离家）"""
        result = await self._custom_request(
            "/devUserConfig/detail", {"userId": self._identity_id})
        if isinstance(result, dict) and result.get("success"):
            return result.get("data") or {}
        return {}

    async def async_set_notice_config(self, notice_type: str, enabled: bool) -> bool:
        """设置通知开关

        notice_type: exceptionNotice / beHomeNotice / leaveHomeNotice
        """
        suffix = "on" if enabled else "off"
        result = await self._custom_request(
            f"/devUserConfig/{notice_type}/{suffix}", {"userId": self._identity_id})
        return bool(isinstance(result, dict) and result.get("success"))

    async def async_get_speaker_code(self) -> str:
        """获取华为音箱配对码（oauth/vcode）"""
        result = await self._custom_request(
            "/oauth/vcode", {"identityId": self._identity_id})
        if isinstance(result, dict) and result.get("success"):
            return str((result.get("data") or {}).get("vcode", ""))
        return ""

    def set_credentials(self, identity_id: str, refresh_token: str):
        self._identity_id = identity_id
        self._refresh_token = refresh_token

    def set_login_credentials(self, phone: str, password: str):
        self._phone = phone
        self._password = password

    def has_login_credentials(self) -> bool:
        return bool(self._phone and self._password)

    async def async_auto_login(self) -> bool:
        if not self.has_login_credentials():
            return False
        try:
            await self.async_login(self._phone, self._password)
            return True
        except Exception as e:
            _LOGGER.warning("Auto login failed: %s", e)
            return False

    def set_iot_token(self, iot_token: str, expires_in: int = 72000):
        self._iot_token = iot_token
        self._iot_token_expire = int(time.time()) + expires_in

    def invalidate_iot_token(self):
        """清空 IoT token，强制下一轮走刷新或重新登录"""
        self._iot_token = ""
        self._iot_token_expire = 0

    @property
    def identity_id(self) -> str:
        return self._identity_id

    @property
    def refresh_token(self) -> str:
        return self._refresh_token

    @property
    def iot_token(self) -> str:
        return self._iot_token

    @property
    def iot_token_expire(self) -> int:
        """iotToken 到期时间戳（秒），供上层持久化用。"""
        return self._iot_token_expire

    def is_token_expiring(self) -> bool:
        return (self._iot_token_expire - int(time.time())) < TOKEN_EXPIRE_THRESHOLD


def _parse_der_rsa_pubkey(der_bytes: bytes) -> tuple[int, int]:
    """解析 DER 编码的 RSA 公钥，返回 (n, e)

    SubjectPublicKeyInfo 结构：
      SEQUENCE {
        SEQUENCE { OID rsaEncryption, NULL }
        BIT STRING {
          SEQUENCE {
            INTEGER n
            INTEGER e
          }
        }
      }
    简化实现，跳过外层 SEQUENCE 和 OID，直接定位到 BIT STRING 中的 RSAPublicKey。
    """
    pos = 0
    # 跳过 SubjectPublicKeyInfo 外层 SEQUENCE
    if der_bytes[pos] != 0x30:
        raise ValueError("Expected SEQUENCE at start")
    pos += 1
    if der_bytes[pos] & 0x80:
        # 长格式长度
        length_bytes = der_bytes[pos] & 0x7F
        pos += 1 + length_bytes
    else:
        pos += 1

    # 跳过 AlgorithmIdentifier SEQUENCE (OID + NULL)
    if der_bytes[pos] != 0x30:
        raise ValueError("Expected AlgorithmIdentifier SEQUENCE")
    pos += 1
    if der_bytes[pos] & 0x80:
        alg_len = int.from_bytes(der_bytes[pos+1:pos+1+(der_bytes[pos] & 0x7F)], "big")
        pos += 1 + (der_bytes[pos] & 0x7F) + alg_len
    else:
        pos += 1 + der_bytes[pos]

    # BIT STRING
    if der_bytes[pos] != 0x03:
        raise ValueError("Expected BIT STRING")
    pos += 1
    if der_bytes[pos] & 0x80:
        bs_len = int.from_bytes(der_bytes[pos+1:pos+1+(der_bytes[pos] & 0x7F)], "big")
        pos += 1 + (der_bytes[pos] & 0x7F)
    else:
        bs_len = der_bytes[pos]
        pos += 1
    # 跳过 unused bits 字节
    bitstring_data = der_bytes[pos+1:pos+bs_len]
    pos += bs_len

    # RSAPublicKey SEQUENCE
    if bitstring_data[0] != 0x30:
        raise ValueError("Expected RSAPublicKey SEQUENCE")
    inner = bitstring_data
    inner_pos = 0
    if inner[inner_pos] != 0x30:
        raise ValueError("Expected SEQUENCE inside BIT STRING")
    inner_pos += 1
    if inner[inner_pos] & 0x80:
        inner_len = int.from_bytes(inner[inner_pos+1:inner_pos+1+(inner[inner_pos] & 0x7F)], "big")
        inner_pos += 1 + (inner[inner_pos] & 0x7F)
    else:
        inner_len = inner[inner_pos]
        inner_pos += 1
    seq_data = inner[inner_pos:inner_pos+inner_len]

    # 解析第一个 INTEGER (n)
    seq_pos = 0
    if seq_data[seq_pos] != 0x02:
        raise ValueError("Expected INTEGER n")
    seq_pos += 1
    if seq_data[seq_pos] & 0x80:
        n_len = int.from_bytes(seq_data[seq_pos+1:seq_pos+1+(seq_data[seq_pos] & 0x7F)], "big")
        seq_pos += 1 + (seq_data[seq_pos] & 0x7F)
    else:
        n_len = seq_data[seq_pos]
        seq_pos += 1
    n_bytes = seq_data[seq_pos:seq_pos+n_len]
    n = int.from_bytes(n_bytes, "big")
    seq_pos += n_len

    # 解析第二个 INTEGER (e)
    if seq_data[seq_pos] != 0x02:
        raise ValueError("Expected INTEGER e")
    seq_pos += 1
    if seq_data[seq_pos] & 0x80:
        e_len = int.from_bytes(seq_data[seq_pos+1:seq_pos+1+(seq_data[seq_pos] & 0x7F)], "big")
        seq_pos += 1 + (seq_data[seq_pos] & 0x7F)
    else:
        e_len = seq_data[seq_pos]
        seq_pos += 1
    e_bytes = seq_data[seq_pos:seq_pos+e_len]
    e = int.from_bytes(e_bytes, "big")

    return n, e


def _pkcs1_v15_encrypt(plaintext: bytes, n: int, e: int) -> bytes:
    """PKCS#1 v1.5 加密（type 02），使用 Python 内置大整数运算，不依赖 cryptography"""
    k = (n.bit_length() + 7) // 8  # 模数字节长度
    if len(plaintext) > k - 11:
        raise ValueError("Plaintext too long for RSA PKCS1v15")

    # PKCS#1 v1.5 type 02 填充：0x00 || 0x02 || PS || 0x00 || M
    ps_len = k - len(plaintext) - 3
    ps = bytes([random.randint(1, 255) for _ in range(ps_len)])
    padded = b"\x00\x02" + ps + b"\x00" + plaintext

    # m = int.from_bytes(padded, "big")
    m = int.from_bytes(padded, "big")
    c = pow(m, e, n)  # 模幂运算
    return c.to_bytes(k, "big")


def rsa_encrypt_password(password: str) -> str:
    RSA_PUB_KEY_B64 = "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAl4EFDk91/ArPHjyX7UBzofPTAD3pcP8FMgOs83hvLEcbFJOVASrPAjbJTuXsSZJd9tYPwKbuqlGqndvdl2Kn2zLFpLOcFAYOyaIDFzDOCWQw/kMjcm1U08BvPE7dbtkGM23lCyTBlDMHWJvUz3JVTZm6ApGWEOGRhs1rECjcS9HXttnllQ2gTtBAW5Xjb8tzDgWR0jMaHzduCcSimHPtQO4Osh4Op3ianRocbb9o/4OR8HgKdbaKO3Sq2+pYV7FveXmfXqUr5lH7oHji+4j5TaU4WXRGKOjHSVXtN0UrfCXtsWE0aGCXXQN78NJUf5VrJMh14mqiSrR07wgu3UG7OwIDAQAB"

    pub_key_bytes = base64.b64decode(RSA_PUB_KEY_B64)
    n, e = _parse_der_rsa_pubkey(pub_key_bytes)
    password_bytes = password.encode("utf-8")
    block_size = 245  # 2048位RSA的PKCS1v15最大明文块大小
    encrypted_blocks = []
    for i in range(0, len(password_bytes), block_size):
        block = password_bytes[i:i + block_size]
        encrypted = _pkcs1_v15_encrypt(block, n, e)
        encrypted_blocks.append(encrypted)
    encrypted_data = b"".join(encrypted_blocks)
    return base64.b64encode(encrypted_data).decode()