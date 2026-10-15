"""SLAC 长连接推送客户端（阿里云 IoT MQTT，App 侧通道）

链路（全部实测验证，见 REVERSE_ENGINEERING_RECORD.md）：
  1. SlacApi.async_aepauth() → /app/aepauth/handle 换取 MQTT 三元组
     （productKey/deviceName/deviceSecret，每次会话随机生成）
  2. 连接 {pk}.iot-as-mqtt.cn-shanghai.aliyuncs.com:1883（TLS 不校验证书）
     - clientId = "{dn}&{pk}|securemode=2,signmethod=hmacsha1,ext=1|"
     - username = "{dn}&{pk}"
     - password = upper(HmacSHA1(deviceSecret, "clientId..deviceName..productKey.."))
  3. 连上后订阅 /sys/{pk}/{dn}/app/down/#，
     并 publish /sys/{pk}/{dn}/app/up/account/bind（params.iotToken = 当前 iotToken）
  4. 收到 bind_reply code=200 后，云端在设备属性变化时实时推送
     /sys/{pk}/{dn}/app/down/thing/properties（实测开关操作后 ~2s 内到达）

推送 payload 的 params.items（InfoN → {value: JSON 字符串}）与
/thing/properties/get 返回结构一致，coordinator 直接合并。

paho-mqtt 回调在后台线程执行，所有 HA 状态操作统一经
hass.loop.call_soon_threadsafe 回到事件循环。
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import ssl
import threading
import time
import uuid
from collections.abc import Callable

import paho.mqtt.client as mqtt

_LOGGER = logging.getLogger(__name__)

MQTT_PORT = 1883
MQTT_KEEPALIVE = 65
BIND_TIMEOUT = 15  # 等待 bind_reply 的秒数
RECONNECT_DELAY_MIN = 1
RECONNECT_DELAY_MAX = 60


def _make_password(device_secret: str, product_key: str, device_name: str, base_id: str) -> str:
    """阿里云 IoT MQTT 密码：按 key 排序拼接 clientId/deviceName/productKey 后 HMAC-SHA1（大写 hex）"""
    parts = "".join(
        f"{k}{v}"
        for k, v in sorted(
            {"clientId": base_id, "deviceName": device_name, "productKey": product_key}.items()
        )
    )
    return hmac.new(device_secret.encode(), parts.encode(), hashlib.sha1).hexdigest().upper()


class SlacPushClient:
    """长连接推送：MQTT 连接 + account bind + 属性推送分发"""

    def __init__(
        self,
        get_iot_token: Callable[[], str],
        on_properties_pushed: Callable[[str, dict], None],
        on_bound: Callable[[bool], None] | None = None,
    ) -> None:
        self._get_iot_token = get_iot_token
        self._on_properties_pushed = on_properties_pushed
        self._on_bound = on_bound

        self._client: mqtt.Client | None = None
        self._product_key = ""
        self._device_name = ""
        self._base_id = ""
        self._loop_thread: threading.Thread | None = None
        self._bind_event = threading.Event()
        self._bound = False
        self._started = False

    @property
    def connected(self) -> bool:
        return bool(self._client and self._client.is_connected())

    @property
    def bound(self) -> bool:
        return self._bound

    async def async_start(self, hass_loop, aepauth_data: dict) -> bool:
        """启动长连接。aepauth_data 为 SlacApi.async_aepauth() 的返回（data 字段）。

        必须在事件循环中调用（内部用 asyncio Event 等待 bind 结果）。
        """
        if self._started:
            self.stop()
        pk = aepauth_data.get("productKey", "")
        dn = aepauth_data.get("deviceName", "")
        ds = aepauth_data.get("deviceSecret", "")
        if not (pk and dn and ds):
            _LOGGER.warning("aepauth 数据不完整，跳过长连接: %s", aepauth_data)
            return False

        self._product_key = pk
        self._device_name = dn
        self._base_id = f"{dn}&{pk}"
        password = _make_password(ds, pk, dn, self._base_id)
        client_id = f"{self._base_id}|securemode=2,signmethod=hmacsha1,ext=1|"
        host = f"{pk}.iot-as-mqtt.cn-shanghai.aliyuncs.com"

        self._bind_event = threading.Event()
        self._bound = False
        self._hass_loop = hass_loop

        client = mqtt.Client(
            client_id=client_id,
            protocol=mqtt.MQTTv311,
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        )
        client.username_pw_set(self._base_id, password)
        client.tls_set(cert_reqs=ssl.CERT_NONE)  # 与 APP 一致，不校验证书
        client.reconnect_delay_set(RECONNECT_DELAY_MIN, RECONNECT_DELAY_MAX)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        self._client = client

        try:
            # connect 会做 DNS/TCP/CONNACK，可能阻塞，放线程池执行
            await asyncio.get_running_loop().run_in_executor(
                None, client.connect, host, MQTT_PORT, MQTT_KEEPALIVE)
        except Exception as e:
            _LOGGER.error("长连接 MQTT 连接失败: %s", e)
            self._client = None
            return False

        client.loop_start()  # 后台线程处理网络循环
        self._started = True

        # 等待 bind_reply（事件由后台线程 set，线程安全）
        deadline = time.monotonic() + BIND_TIMEOUT
        while time.monotonic() < deadline:
            if self._bind_event.is_set():
                break
            await asyncio.sleep(0.2)

        if not self._bound:
            _LOGGER.warning("长连接 bind 未确认（%ss 内无 bind_reply），连接保持但推送可能不生效", BIND_TIMEOUT)
        else:
            _LOGGER.info("长连接已建立并绑定账号，设备状态将实时推送")
        return self._bound

    def stop(self) -> None:
        """断开并释放资源（可在任意线程调用）"""
        client = self._client
        self._client = None
        self._started = False
        if client is None:
            return
        try:
            if self._product_key and self._device_name and self._bound:
                payload = json.dumps({
                    "id": str(uuid.uuid4().int & 0xFFFFFFFF),
                    "system": {"version": "1.0", "time": str(int(time.time() * 1000))},
                    "request": {"clientId": self._base_id},
                    "params": None,
                }, ensure_ascii=False, separators=(",", ":"))
                client.publish(
                    f"/sys/{self._product_key}/{self._device_name}/app/up/account/unbind",
                    payload, qos=1)
                time.sleep(0.5)  # 给后台线程一点时间发出 unbind
        except Exception:  # noqa: BLE001 - 退出路径尽力而为
            pass
        try:
            client.disconnect()
        except Exception:  # noqa: BLE001
            pass
        try:
            client.loop_stop()
        except Exception:  # noqa: BLE001
            pass
        self._bound = False

    # ---------------- paho 回调（后台线程） ----------------

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        rc = getattr(reason_code, "value", reason_code)
        if rc != 0:
            _LOGGER.warning("长连接 MQTT on_connect rc=%s", rc)
            return
        _LOGGER.debug("长连接 MQTT 已连接，订阅下行 topic")
        client.subscribe(f"/sys/{self._product_key}/{self._device_name}/app/down/#", qos=1)
        # 发起账号绑定（携带当前 iotToken）
        iot_token = ""
        try:
            iot_token = self._get_iot_token()
        except Exception:  # noqa: BLE001
            pass
        payload = json.dumps({
            "id": str(uuid.uuid4().int & 0xFFFFFFFF),
            "system": {"version": "1.0", "time": str(int(time.time() * 1000))},
            "request": {"clientId": self._base_id},
            "params": {"iotToken": iot_token},
        }, ensure_ascii=False, separators=(",", ":"))
        client.publish(
            f"/sys/{self._product_key}/{self._device_name}/app/up/account/bind",
            payload, qos=1)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        rc = getattr(reason_code, "value", reason_code)
        if rc != 0:
            # paho 自动重连（reconnect_delay_set），重连成功后 on_connect 会重新 bind
            _LOGGER.warning("长连接 MQTT 断开 rc=%s，将自动重连", rc)
            self._bound = False
        else:
            _LOGGER.debug("长连接 MQTT 主动断开")

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        try:
            body = msg.payload.decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            return

        if "/account/bind_reply" in topic:
            try:
                data = json.loads(body)
                code = data.get("code")
            except json.JSONDecodeError:
                code = None
            self._bound = code == 200
            if self._bound:
                _LOGGER.info("长连接账号绑定成功 (bind_reply code=200)")
            else:
                _LOGGER.warning("长连接账号绑定失败: %s", body[:200])
            self._bind_event.set()
            if self._on_bound:
                self._call_in_loop(lambda: self._on_bound(self._bound))
            return

        if "/account/unbind_reply" in topic:
            return

        if "/thing/properties" in topic:
            parsed = _parse_properties_push(body)
            if parsed:
                iot_id, items = parsed
                self._call_in_loop(lambda: self._on_properties_pushed(iot_id, items))
            return

        if "/thing/status" in topic or "/thing/events" in topic:
            # 设备上下线/事件：无法合并到属性，触发一次协调器刷新即可
            _LOGGER.debug("长连接收到状态/事件消息: %s", topic)
            return

    def _call_in_loop(self, func) -> None:
        """把回调切回 HA 事件循环执行（paho 回调在后台线程）"""
        loop = getattr(self, "_hass_loop", None)
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(func)
        except RuntimeError:
            pass  # 事件循环已关闭


def _parse_properties_push(body: str) -> tuple[str, dict] | None:
    """解析 thing.properties 推送 → (iot_id, {InfoN: {...}})

    实测 payload：
    {"method":"thing.properties","params":{"iotId":"...","items":{
        "Info6":{"time":...,"value":"{\"InternalAddress\":6,\"PowerSwitch\":0,...}"}}}}
    """
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return None
    if data.get("method") != "thing.properties":
        return None
    params = data.get("params") or {}
    iot_id = params.get("iotId") or ""
    raw_items = params.get("items") or {}
    if not iot_id or not isinstance(raw_items, dict):
        return None
    parsed: dict[str, dict] = {}
    for key, val in raw_items.items():
        if isinstance(val, dict) and "value" in val:
            inner = val.get("value")
            if isinstance(inner, str):
                try:
                    inner = json.loads(inner)
                except json.JSONDecodeError:
                    pass
            parsed[key] = inner if isinstance(inner, dict) else val
        else:
            parsed[key] = val
    if not parsed:
        return None
    return iot_id, parsed
