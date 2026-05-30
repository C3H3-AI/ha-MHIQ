# SLAC 集成项目完整状态记录

> 最后更新: 2026-05-30 08:35
> APK: slac_v2.1.8.apk
> 环境: MuMu模拟器 + mitmproxy (端口8888) + HA OS

---

## 一、当前掌握的 Tokens

| Token | 值 | 有效期 | 状态 |
|-------|-----|--------|------|
| identityId | `50e6opd48458f4ad34fc7f0e8ef7fbde02d97465` | 永久 | ✅ 可用 |
| iotToken (fallback) | `24e2f4512c959ce028b73fe591eab352` | ~20h (到 05-31 01:00) | ⚠️ 接近过期 |
| refreshToken | `C017E61F1919BF8CB10BB4A2F0CF7969` | 抓到时就已过期 | ❌ 过期 |
| 历史有效 refreshToken | `32AE1EA75A717BCEBEAD239840955018` | 2026-05-29 抓取的 | ❌ 过期 |
| 历史有效 refreshToken | `FA3A42D43AD80C81B2445F1C3C69C0F1` | 2026-05-29 抓取的 | ❌ 过期 |

---

## 二、全套 API 清单

### Group A: Custom API — 仅需 identityId ✅ 当前可用

这些 API 走 `slacapp2.mhaq.cn:8081`，不需要 token，只需要 identityId。

| 端点 | 方法 | 参数 | 功能 | 已验证 |
|------|------|------|------|--------|
| `/slzgweb/devDevice/getDeviceList` | POST | `identityId` | 获取设备列表（9台） | ✅ 200 |
| `/slzgweb/devAddressStore/Tree` | GET | `userId=` | 获取地址树/房间分组 | ❌ |
| `/slzgweb/devUser/getUser` | POST | `userId` | 获取用户信息 | ❌ |
| `/slzgweb/devUserConfig/detail` | POST | `userId` | 获取用户配置详情 | ❌ |
| `/slzgweb/sys/device/list` | GET | `userId=` | 系统设备列表 | ❌ |
| `/slzgweb/appVersion/checkUpdate` | POST | `clientVersion`, `sysType` | 检查版本更新 | ❌ |

**调用频率**: `getDeviceList` 被调用了 1172 次（轮询），`devAddressStore/Tree` 321 次

### Group B: Custom API — 需要 iotToken (HMAC 签名) ⚠️ 被 403 阻塞

这些 API 也走 `slacapp2.mhaq.cn:8081`，但 body 是 IoT 协议格式（含 iotToken）。

| 端点 | 方法 | 参数 | 功能 |
|------|------|------|------|
| `/slzgweb/weather/getWeather` | POST | IoT 协议 body（含 iotToken） | 获取天气 |
| `/slzgweb/weather/getImage` | GET | `filePath=` | 获取天气图标图片 |

**阻塞原因**: 同 Group C，HMAC 签名缺 Content-MD5 头

### Group C: 阿里云 IoT API — 需要 HMAC 签名 + iotToken ❌ 全部被 403 阻塞

这些 API 走 `api.link.aliyun.com`。

| 端点 | 方法 | 功能 |
|------|------|------|
| `/account/createSessionByAuthCode` | POST | 用 authCode 换取 iotToken + refreshToken |
| `/thing/properties/get` | POST | 读取设备属性/状态 |
| `/thing/properties/set` | POST | 设置设备属性/控制空调 |
| `/uc/listBindingByAccount` | POST | 获取绑定设备列表 |
| `/thing/productInfo/getByAppKey` | POST | 获取产品信息 |

**阻塞原因**: HMAC 签名函数 `compute_iot_headers()` 的代码 bug
- **`Content-MD5` 头已算入签名但未发送到请求中** → API 网关计算签名时 Content-MD5 为空 → 签名不匹配 → 403
- APP 原始请求包含 `content-md5` 头 ✅，我们的代码缺失 ❌
- 次要问题：APP 的 URL 带 `?x-ca-request-id=xxx`，我们没带

### Group D: OA API — 需要 OA 特殊签名 ❌ 签名算法未破解

| 端点 | Host | 功能 |
|------|------|------|
| `/api/prd/login.json` | `living-account.cn-shanghai.aliyuncs.com` | 手机号+密码登录 |
| `/api/prd/init.json` | 同上 | SDK 初始化 |

**阻塞原因**: OA SDK 使用 `SecuritySigner` 替代标准 HMAC-SHA1，签名算法不同
- 可能使用动态获取的 AppSecret（非 `6cf45cdbeaa4ce6faa204741f3d772ca`）
- `SecurityImpl.sign()` 的 hex → base64 路径输出应与标准相同，但实测不匹配

---

## 三、当前本地测试结果

| 测试项 | 结果 | 说明 |
|--------|------|------|
| `getDeviceList` (custom) | ✅ 200, 9台 | 仅需 identityId |
| `refreshToken → createSessionByAuthCode` | ❌ 403 | ① HMAC 签名缺 Content-MD5 头 ② refreshToken 已过期 |
| `iotToken → getProperties` | ❌ 403 | 同上，HMAC 签名问题 |
| `iotToken → setProperties` | ❌ 未测试 | 必然也 403 |
| OA 登录 (手机+密码) | ❌ 签名不匹配 | OA SDK 使用不同的签名 Secret |
| config flow (HA前端) | ⚠️ 代码已修复但未重新测试 | fallback iotToken 已加 |
| 设备详情 (getUser) | ❌ 未测试 | 可先用 identityId 测试 |
| 地址树 (devAddressStore) | ❌ 未测试 | 可先用 identityId 测试 |

---

## 四、APK 反编译成果

### 4.1 成功解析的文件（7个）

| 文件 | 路径 (smali) | 收获 |
|------|-------------|------|
| **SecSecurityImpl.smali** | `com/alibaba/sdk/android/openaccount/rpc/cloudapi/` | OA SDK 安全实现（SecurityGuard 已废弃时会 fallback 到 SecurityImpl） |
| **SecurityImpl.smali** | `com/aliyun/alink/linksdk/securesigner/` | `sign()` 方法：hex 签名 → hexStr2Base64Str |
| **SignUtil.smali** | `com/alibaba/cloudapi/sdk/util/` | **签名核心算法**：string-to-sign 格式完全确认（Method + Accept + Content-MD5 + Content-Type + Date + CanonicalizedHeaders + CanonicalizedResource） |
| **LoginServiceImpl.smali** | 区域查询、OA 登录的 RPC 参数构造 | 登录请求的 JSON 结构完整提取 |
| **RpcServiceImpl.smali** | 发送请求 + 解析响应 | HMAC 签名流程确认 |
| **SessionManager.smali** | token 存储管理 | refreshToken/iotToken 刷新机制确认 |
| **IndividualSdk.smali** | SDK 初始化 | 动态 AppKey 加载逻辑 |

### 4.2 确定的密钥

| 密钥 | 值 | 用途 |
|------|-----|------|
| IoT AppKey | `34457410` | HMAC-SHA1 签名的 x-ca-key |
| IoT AppSecret | `6cf45cdbeaa4ce6faa204741f3d772ca` | HMAC-SHA1 签名的密钥 |
| RSA 公钥 | `MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgK...` | 密码 RSA 加密（2048位, PKCS1Padding） |

### 4.3 已确认的认证流程

```
手机号+密码登录:
  1. RSA 加密密码 (PKCS1Padding, 分块245字节)
  2. 构造 loginRequest JSON (含 riskControlInfo 设备信息)
  3. fastjson 序列化 → 转义 / → URL encode
  4. HMAC 签名 → POST → OA API /api/prd/login.json
  5. 返回 sid (authCode) + refreshToken(OAuth)
  6. sid → createSessionByAuthCode → iotToken + refreshToken(IoT)

Token 刷新:
  refreshToken → ? → OA API → 新 sid → createSessionByAuthCode → 新 iotToken
  
设备读取:
  iotToken + HMAC 签名 → thing/properties/get → 设备当前状态
  
设备控制:
  iotToken + HMAC 签名 → thing/properties/set → 发送控制指令
```

### 4.4 未破解的

- **OA 登录的 HMAC 签名** — 计算值与抓包签名不匹配
  - 猜测：OA SDK 使用不同的 AppSecret（可能动态获取，非 `6cf45cdbeaa4ce6faa204741f3d772ca`）
- **refreshToken 刷新流程** — 需要用 OA SDK 的 refresh 接口（不是直接用 refreshToken 调 createSessionByAuthCode）

---

## 五、代码实现状态

| 文件 | 路径 | 功能 | 状态 |
|------|------|------|------|
| api.py | `custom_components/slac/api.py` | 所有 API 调用逻辑 | ⚠️ HMAC 签名缺 Content-MD5 头 |
| config_flow.py | `custom_components/slac/config_flow.py` | HA 配置流 | ✅ 含 fallback，用户未重新测试 |
| __init__.py | `custom_components/slac/__init__.py` | HA 集成初始化 | ✅ 含 coordinator 轮询 |
| const.py | `custom_components/slac/const.py` | 常量 | ✅ |
| climate.py | `custom_components/slac/climate.py` | 空调实体 | ⏳ 未测试 |
| sensor.py | `custom_components/slac/sensor.py` | 传感器实体 | ⏳ 未测试 |
| manifest.json | `custom_components/slac/manifest.json` | 集成清单 | ✅ 已部署 |
| REVERSE_ENGINEERING_RECORD.md | `slac_ha/REVERSE_ENGINEERING_RECORD.md` | 逆向记录 | ✅ |

---

## 六、下一步修复优先级

| 优先级 | 任务 | 预期效果 |
|--------|------|----------|
| 🔴 P0 | 修 `compute_iot_headers` 加 `Content-MD5` 头 | IoT API 不再 403，能读设备状态、能控制空调 |
| 🟡 P1 | 抓取新的有效 refreshToken | 拿到有效的 refreshToken，验证 token 刷新流程 |
| 🟡 P2 | HA 前端测试添加集成 | 验证 "Unknown error" 是否已解决 |
| 🟢 P3 | 测试 Group A 其他端点 | 看 getUser / devAddressStore 能否提供更多信息 |
| 🟢 P4 | OA 签名破解 | 实现手机号+密码登录（长期目标） |

---

## 七、测试环境信息

| 项目 | 配置 |
|------|------|
| MuMu ADB | `D:\Program Files\Netease\MuMu\nx_main\adb.exe` |
| 模拟器 | `127.0.0.1:16384` |
| mitmproxy | 端口 8888，模拟器代理已设到 `192.168.3.55:8888` |
| SLAC 包名 | `com.limap.slac` |
| HA 地址 | `http://api.homediy.top:8123` |
| HA Python | HA OS (aarch64) 自带 |
| 本地 Python | `C:\Users\duola\AppData\Local\Programs\Python\Python311\python.exe` |
| 抓包文件 | `D:\ai-hub\temp\slac_captured.txt` (~5MB) |
| 集成代码 | `D:\ai-hub\integrations\slac_ha\custom_components\slac\` |
| HA 部署 | `/config/custom_components/slac/` |