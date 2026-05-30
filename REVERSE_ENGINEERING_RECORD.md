# SLAC 集成逆向工程完整记录

> 日期: 2026-05-30
> APK: slac_v2.1.8.apk
> 工具: apktool, Python, HA API
> 技能: `.trae/skills/apk-reverse-engineer/`

---

## 一、目录结构

```
D:\ai-hub\temp\slac_apktool\smali\com\
├── alibaba\
│   ├── cloudapi\sdk\                           # 阿里云 CloudAPI SDK（通用签名框架）
│   │   ├── constant\SdkConstant.smali          # 常量：UTF-8 编码
│   │   ├── enums\HttpMethod.smali              # HTTP 方法枚举（POST_FORM, POST_BODY 等）
│   │   │   ├── POST_FORM:  Content-Type = application/x-www-form-urlencoded; charset=utf-8
│   │   │   └── POST_BODY:  Content-Type = application/octet-stream; charset=utf-8
│   │   ├── model\
│   │   │   ├── ApiHttpMessage.smali            # 基类：addHeader 会 trim + toLowerCase
│   │   │   └── ApiRequest.smali                # 请求对象：headers, querys, formParams, body
│   │   ├── util\
│   │   │   ├── ApiRequestMaker.smali           # 核心：构建请求和签名
│   │   │   ├── SignUtil.smali                  # 签名核心算法
│   │   │   └── HttpCommonUtil.smali            # URL 编码工具
│   │   └── signature\
│   │       ├── SignerFactoryManager.smali      # 签名工厂管理器
│   │       ├── HMacSHA1SignerFactory.smali     # HMAC-SHA1 签名工厂
│   │       └── HMacSHA1SignerFactory$HMacSHA1Signer.smali  # HMAC-SHA1 → Base64
│   └── sdk\android\openaccount\                # 阿里云 Open Account SDK
│       ├── util\safe\
│       │   ├── RSAKey.smali                    # RSA 公钥常量
│       │   └── Rsa.smali                       # RSA 加解密实现
│       ├── util\HmacSHA1Util.smali             # HMAC-SHA1 工具
│       ├── util\ApiEncryptionUtil.smali        # AES/CBC/PKCS5Padding 加密
│       └── rpc\cloudapi\
│           ├── ApiGatewayRpcServiceImpl.smali  # OA API 网关实现
│           └── SecuritySignerFactory.smali     # OA SDK 签名器工厂
│               └── SecuritySigner.smali        # OA 签名：hex → hexStr2Base64Str
└── aliyun\alink\linksdk\securesigner\
    └── SecurityImpl.smali                      # 安全实现（getAppKey, sign）
```

---

## 二、API 端点

### 2.1 IoT API（设备控制）

| 用途 | 端点 | 方法 |
|------|------|------|
| 设备认证 | `/app/aepauth/handle` | POST_BODY |
| Bundle URL 查询 | `/open/app/mobile/base/bundle/url/query` | POST_BODY |
| 插件详情 | `/open/app/mobile/plugin/detail/get` | POST_BODY |
| 区域查询 | `/living/account/region/get` | POST_BODY |
| 创建 Session | `/account/createSessionByAuthCode` | POST_BODY |
| 设备列表 | `/account/device/list` | POST_BODY |
| 设备控制 | `/account/device/realtime/control` | POST_BODY |
| 天气查询 | `/account/device/weather` | POST_BODY |
| 版本检查 | `/account/device/version/checkUpdate` | POST_BODY |

**Host**: `https://aep.cloud.aliyuncs.com`（原始）
**代理**: `http://slacapp2.mhaq.cn:8081`（SLAC 的 nginx 反向代理）
**AppKey**: `34457410`
**AppSecret**: `6cf45cdbeaa4ce6faa204741f3d772ca`

### 2.2 OA API（登录认证）

| 用途 | 端点 | 方法 |
|------|------|------|
| 登录 | `/api/prd/login.json` | POST_FORM |
| 初始化 | `/api/prd/init.json` | POST_BODY |

**Host**: `https://living-account.cn-shanghai.aliyuncs.com`
**AppKey**: `34457410`（和 IoT API 相同！）
**AppSecret**: `6cf45cdbeaa4ce6faa204741f3d772ca`（同一对密钥）

---

## 三、登录完整流程

```
┌─────────────────────────────────────────────────────────────┐
│  1. Device Auth (2次)                                       │
│     POST /app/aepauth/handle  → 获取 clientId, sign         │
├─────────────────────────────────────────────────────────────┤
│  2. Bundle URL Query                                        │
│     POST /open/app/mobile/base/bundle/url/query             │
├─────────────────────────────────────────────────────────────┤
│  3. Plugin Detail Get                                       │
│     POST /open/app/mobile/plugin/detail/get                 │
├─────────────────────────────────────────────────────────────┤
│  4. Region Get                                              │
│     POST /living/account/region/get                         │
│     Body: {"d":{"type":"PHONE","phone":"137****6363"}}      │
├─────────────────────────────────────────────────────────────┤
│  5. 🎯 OA Login (核心)                                      │
│     POST https://living-account.cn-shanghai.aliyuncs.com    │
│         /api/prd/login.json                                 │
│     Content-Type: application/x-www-form-urlencoded         │
│     格式: loginRequest=<URL-encoded JSON>                   │
│     JSON 中包含:                                             │
│       - password: RSA 加密后的密码 (base64)                  │
│       - loginId: 手机号                                     │
│       - riskControlInfo: 设备信息                            │
│                                                            │
│     成功响应:                                               │
│     {                                                       │
│       "data": {                                             │
│         "data": {                                           │
│           "loginSuccessResult": {                           │
│             "sid": "c19eabdf889b4941a997d0059e6b3e84",      │
│             "refreshToken": "OA-02db98949613465d9b183c59450c1393"  │
│           }                                                 │
│         }                                                   │
│       }                                                     │
│     }                                                       │
├─────────────────────────────────────────────────────────────┤
│  6. Create Session by AuthCode                              │
│     POST /account/createSessionByAuthCode                   │
│     Body: {"d":{"request":{"authCode":"<sid>",              │
│            "accountType":"OA_SESSION","appKey":"34457410"}} │
├─────────────────────────────────────────────────────────────┤
│  7. 设备操作                                                │
│     GET/POST device/list, realtime/control 等              │
└─────────────────────────────────────────────────────────────┘
```

---

## 四、RSA 密码加密

### 4.1 公钥

来源: `RSAKey.smali` 硬编码，X.509 SubjectPublicKeyInfo 格式，DER 编码的 2048 位 RSA 公钥

```python
RSA_PUB_KEY_B64 = "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAl4EFDk91/ArPHjyX7UBzofPTAD3pcP8FMgOs83hvLEcbFJOVASrPAjbJTuXsSZJd9tYPwKbuqlGqndvdl2Kn2zLFpLOcFAYOyaIDFzDOCWQw/kMjcm1U08BvPE7dbtkGM23lCyTBlDMHWJvUz3JVTZm6ApGWEOGRhs1rECjcS9HXttnllQ2gTtBAW5Xjb8tzDgWR0jMaHzduCcSimHPtQO4Osh4Op3ianRocbb9o/4OR8HgKdbaKO3Sq2+pYV7FveXmfXqUr5lH7oHji+4j5TaU4WXRGKOjHSVXtN0UrfCXtsWE0aGCXXQN78NJUf5VrJMh14mqiSrR07wgu3UG7OwIDAQAB"
```

### 4.2 加密算法

来源: `Rsa.smali`

| 项目 | 值 |
|------|-----|
| 算法 | `RSA/ECB/PKCS1Padding` |
| 块大小 | 245 字节（2048位RSA） |
| 分块 | 每 245 字节加密一次，拼接结果 |
| 输出编码 | Base64 |

### 4.3 Python 实现

```python
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend

def rsa_encrypt_password(password: str) -> str:
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
```

### 4.4 JSON 转义特殊规则

OA SDK 使用 `fastjson` 序列化 JSON，会转义 `/` 为 `\/`：

```python
login_request = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
login_request = login_request.replace("/", "\\/")  # OA SDK 的 fastjson 行为
```

---

## 五、签名算法

### 5.1 通用签名框架 (CloudAPI SDK)

所有请求（IoT + OA）共用同一个签名框架，实现在 `SignUtil.smali` 和 `ApiRequestMaker.smali`。

#### String-to-Sign 格式

```
HTTPMethod\n
Accept\n
Content-MD5\n
Content-Type\n
Date\n
CanonicalizedHeaders\n
CanonicalizedResource
```

##### HTTPMethod
- POST_FORM → `"POST"`
- POST_BODY → `"POST"`

##### Accept
- POST_FORM → `"application/json; charset=utf-8"`
- POST_BODY → `"application/json; charset=utf-8"`

##### Content-MD5
- POST_BODY: `base64(md5(body_bytes))` — 只取前 24 字节（`base64AndMD5` 方法截取）
- POST_FORM: **不设置**（body 为空，表单数据走 URL 编码）
- 空值时在 string-to-sign 中为**空行**（非 null，是 `""`）

##### Content-Type
- POST_FORM → `"application/x-www-form-urlencoded; charset=utf-8"`
- POST_BODY → `"application/octet-stream; charset=utf-8"`

##### Date
- 格式: `EEE, dd MMM yyyy HH:mm:ss z` (RFC 1123, Locale.US)
- 例如: `"Fri, 29 May 2026 21:09:21 GMT"`

##### CanonicalizedHeaders
- 收集所有 `x-ca-*` 头（不含 `x-ca-signature`）
- 放入 **TreeMap** → 按 key 字母序排序
- 格式: `key1:value1\nkey2:value2\n...`

##### CanonicalizedResource
- POST_BODY: `path` + `?` + sorted query params (TreeMap)
- POST_FORM: `path` + `?` + sorted formParams (TreeMap) + sorted query params
- 值是**原始值**（非 URL 编码）
- 无 query/formParams: 只包含 path

#### HMAC 计算

```java
Mac mac = Mac.getInstance("HmacSHA1");
SecretKeySpec key = new SecretKeySpec(secretKey.getBytes("UTF-8"), "HmacSHA1");
mac.init(key);
byte[] result = mac.doFinal(stringToSign.getBytes("UTF-8"));
String signature = Base64.encodeToString(result, Base64.NO_WRAP);
```

#### 头添加顺序（ApiRequestMaker.make）

```
1. date
2. x-ca-timestamp
3. x-ca-nonce
4. user-agent
5. host
6. x-ca-key
7. CA_VERSION
8. content-type
9. accept
10. x-ca-signature-method (如果有)
11. content-md5 (如果 body 有内容)
→ 12. x-ca-signature (最后计算添加)
```

`addHeader` 会将 key trim + toLowerCase(Locale.ENGLISH)。

### 5.2 OA SDK 特殊签名 (SecuritySigner)

`SecuritySigner.sign()` 是 OA SDK 特有的签名器，覆盖默认的 HMacSHA1Signer：

```java
// 原始路径（SecurityGuard 可用时）：
hex = SecurityGuardManager.signRequest(strToSign, appKey)  // 返回 hex string
base64 = hexStr2Base64Str(hex)  // hex → bytes → Base64

// 回退路径（SecurityImpl 可用时）：
hex = SecurityImpl.sign(strToSign, "HmacSHA1")  // 返回 hex string
base64 = hexStr2Base64Str(hex)  // hex → bytes → Base64
```

`hexStr2Base64Str` 方法：将 hex 字符串按每 2 字符解析为 byte，再 Base64 编码。

⚠️ **注意**: final base64 result 与标准路径相同，因为 hex_decode(hex(hmac_bytes)) == hmac_bytes

### 5.3 已知但未验证的细节

**String-to-sign 的 CanonicalizedHeaders 部分**还有一些细节未在本地 Python 验证中匹配成功：
- POST_FORM 的 formParams 是否被加入 CanonicalizedResource 需要验证
- `x-ca-signature-headers` 的值（HashMap 迭代顺序）不影响签名结果，但作为请求头发送
- content-md5 为空时，string-to-sign 中为 `\n\n`（两个换行之间是空行）

---

## 六、验证的请求示例

### 6.1 OA 登录 (已验证在 HA 服务器上 HTTP 200)

```bash
curl -X POST 'https://living-account.cn-shanghai.aliyuncs.com/api/prd/login.json' \
  -H 'date: Fri, 29 May 2026 21:09:21 GMT' \
  -H 'x-ca-signature: LjG/8J8SLsomCrosW6zA/8ueGX0=' \
  -H 'x-ca-nonce: e3f05fc2-949b-4ce6-87cc-52fd301fc80d' \
  -H 'x-ca-key: 34457410' \
  -H 'ca_version: 1' \
  -H 'accept: application/json; charset=utf-8' \
  -H 'vid: V-34ae6c31-479c-4b88-92da-e10ee655e587' \
  -H 'x-ca-timestamp: 1780088961696' \
  -H 'x-ca-signature-headers: x-ca-nonce,x-ca-timestamp,x-ca-key,x-ca-signature-method' \
  -H 'x-ca-signature-method: HmacSHA1' \
  -H 'Content-Type: application/x-www-form-urlencoded; charset=utf-8' \
  -d 'loginRequest=%7B%22password%22%3A%22...%22%2C%22loginId%22%3A%2213736776363%22...%7D'
```

**200 OK 响应**:
```json
{
  "data": {
    "traceId": "0bc16eb717800942223581657eae59",
    "code": 1,
    "data": {
      "loginSuccessResult": {
        "sid": "c19eabdf889b4941a997d0059e6b3e84",
        "refreshToken": "OA-02db98949613465d9b183c59450c1393",
        "reTokenExpireIn": 7776000,
        "sidExpireIn": 86400,
        "token": "yCtakJYR29c-NU5CQ6K1Mg",
        "openAccount": {
          "id": 191286884,
          "mobile": "13736776363",
          "domainId": 9758267,
          "status": 1
        }
      }
    },
    "subCode": 0,
    "message": "SUCCESS",
    "successful": "true"
  },
  "success": "true",
  "api": "/account/api/login.json"
}
```

### 6.2 IoT API (已验证)

```bash
POST /living/account/region/get HTTP/1.1
Host: slacapp2.mhaq.cn:8081
x-ca-signature: sYf2iU/+s3hokUHz1XoEiW43xaM=
x-ca-timestamp: 1780061740291
x-ca-key: 34457410
x-ca-nonce: aad68cde-1a4c-462c-8c37-d8321b4aacf8
x-ca-signature-method: HmacSHA1
content-md5: lmGP7mhG7wh1NdbssXvKLA==
content-type: application/octet-stream; charset=utf-8
```

---

## 七、已知测试文件

| 文件 | 用途 | 状态 |
|------|------|------|
| `temp/test_rsa_login.py` | 测试 RSA 加密密码 | ✅ 加密成功 |
| `temp/verify_signature_v2.py` | 验证 IoT API 签名 | ❌ 不匹配 |
| `temp/verify_oa_signature.py` | 验证 OA 签名 | ❌ 不匹配 |
| `temp/verify_oa_signature_v3.py` | 穷举 OA 签名参数 | ❌ 未找到 |
| `temp/find_signature.py` | 系统化穷举 154+ 组合 | ❌ 未找到 |
| `temp/test_ha_login.py` | HA 服务器测试用户抓包 curl | ✅ HTTP 200 |
| `temp/test_captured_curl.py` | HA 服务器测试精确 curl | ✅ HTTP 200 |
| `temp/test_full_flow_ha.py` | HA 服务器完整流程 | ✅ 登录成功 |
| `temp/test_full_flow.py` | 本地完整流程 | ❌ 403（本机限制） |
| `temp/test_oa_init.py` | 探索 OA 初始化端点 | ⏳ |
| `temp/deploy_and_login.py` | 部署到 HA + 配置流 | ❌ login_failed |

---

## 八、签名未匹配的问题

### 8.1 现象

用用户抓包中的 exact parameters（nonce, timestamp, date, body）计算的 HMAC-SHA1 签名与请求中的签名不匹配：

```
Computed: njyHgNwZ7/POdPV3AXHc+t/zZdo=
Expected: LjG/8J8SLsomCrosW6zA/8ueGX0=
```

### 8.2 已确认一致的参数

| 参数 | 值 |
|------|-----|
| AppSecret | `6cf45cdbeaa4ce6faa204741f3d772ca` |
| 编码 | UTF-8 |
| 算法 | HmacSHA1 + Base64 |
| Date 格式 | RFC 1123 |

### 8.3 可能的原因

1. **String-to-sign 顺序或格式**: APK 源码已确认格式，但可能存在某条额外的 `\n` 或不同分隔符
2. **CanonicalizedHeaders 中 x-ca-signature-headers 头的处理**: `x-ca-signature-headers` 本身也是 `x-ca-` 开头，是否被包含？
3. **POST_FORM formParams 处理**: 在 `buildResource` 中 formParams 被加入了 canonicalized resource，但用原始 JSON 值计算后仍不匹配
4. **OA SDK 的签名器与标准签名器输出差异**: 即使是 fallback 路径，`SecurityImpl.sign()` 的 hex → hexStr2Base64Str 结果理论上与标准 Base64 相同
5. **`x-ca-signature-method` 头的 key 名称**: 代码中用的是 `"X-Ca-Signature-Method"`，但 `addHeader` 会 lower case

### 8.4 猜测的最可能原因

`SecurityImpl.sign()` 可能使用了**不同的 AppSecret** 而非 `6cf45cdbeaa4ce6faa204741f3d772ca`。OA SDK 的 AppKey/Secret 可能通过 SecurityGuard 或 SecurityImpl 动态获取，而非硬编码。

---

## 九、环境限制

| 限制 | 说明 |
|------|------|
| **本机无法访问 OA 端点** | `living-account.cn-shanghai.aliyuncs.com` 从 Windows 返回 HTTP 403，从 HA 服务器返回 200 |
| **RSA 加密密码有时效性** | 抓包中的 RSA 加密密码不能重用，必须实时加密 |
| **HA 重启后 SSH 断开** | `ha core restart` 会丢失 SSH 连接，需通过 REST API 重启 |
| **Trae 的 python 命令走 Shim** | 必须用完整路径 `C:\Users\duola\AppData\Local\Programs\Python\Python311\python.exe` |

---

## 十、当前集成的核心 API 实现

```python
# api.py 中的关键方法
LIVING_ACCOUNT_HOST = "https://living-account.cn-shanghai.aliyuncs.com"
API_LOGIN_OA = "/api/prd/login.json"
IOT_HOST = "http://slacapp2.mhaq.cn:8081"
APP_KEY = "34457410"
APP_SECRET = "6cf45cdbeaa4ce6faa204741f3d772ca"

async def async_login(phone, password):
    """登录流程"""
    # 1. RSA 加密密码
    encrypted_pwd = rsa_encrypt(password)
    
    # 2. 构建 loginRequest JSON
    login_request = json.dumps({
        "password": encrypted_pwd,
        "loginId": phone,
        "riskControlInfo": {...}
    }, ensure_ascii=False, separators=(",", ":"))
    login_request = login_request.replace("/", "\\/")
    
    # 3. URL-encode body
    body = f"loginRequest={urllib.parse.quote(login_request)}"
    
    # 4. 计算签名, POST 到 OA API
    oa_response = await _oa_request("/api/prd/login.json", body)
    
    # 5. 提取 authCode (sid)
    auth_code = oa_response["data"]["data"]["loginSuccessResult"]["sid"]
    
    # 6. 调用 createSessionByAuthCode
    iot_result = await create_session(auth_code)
    
    return iot_result
```