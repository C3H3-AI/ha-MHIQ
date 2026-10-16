# Changelog

## [1.3.1] - 2026-10-16

### Fixed

- **空调（climate）实体整个消失**：启动时不再把存下来的 `iotToken` 用 `expires_in=0` 标成"已过期"再强制刷新，改为按配置条目里持久化的真实到期时间恢复（旧条目没有该字段时按云端标称 20h 兜底）
- `async_refresh_iot_token()` 失败时不再调用 `invalidate_iot_token()` 清空现有 token：这条刷新链路是拿 `refreshToken` 冒充 OA 会话（`createSessionByAuthCode` 的 `authCode` 必须是登录返回的 sid），云端固定回 `26101 会话 Id 不存在`，而失败分支会把手上那份好 token 一起丢掉，导致属性抓不到
- 新增 `async_ensure_valid_token()`：刷新走不通时自动改用账号密码重新登录换取新会话（实测可用的换会话路径），续期逻辑在启动与每轮轮询共用
- 首次数据刷新改为在建平台之前 `await` 完成：`climate` 平台靠 `coordinator.device_properties` 里的 `Info{内机地址}` 判断建哪些空调机，而这些属性必须拿有效 `iotToken` 才抓得到，原来"后台刷新 + 立刻建平台"并发会让空调实体整个缺失
- token 的到期时间戳随 token 一起写入配置条目（`iot_token_expire`）

## [1.3.0] - 2026-10-15

### Added

- 接入阿里云 MQTT 长连接推送（属性/上下线/事件实时下发），`iot_class` 改为 `cloud_push`
- 新增 `button` 平台（含"获取音箱配对码"）、场景与通知配置刷新
- 新增服务 `slac.fire_scene` 与 `slac.get_speaker_code`

## [1.2.4] - 2026-09-13

### Added

- hassfest CI (home-assistant/actions/hassfest@master)
- HACS validate CI (hacs/action@main)
- tag-triggered auto Release workflow
- PR template + Issue template

### Fixed

- manifest: remove deprecated keys (authors/icon/homeassistant)
- manifest: canonical key order (domain,name then alphabetical)
- services.yaml: remove deprecated device target filters
