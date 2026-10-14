# MaiStatus MaiBot 插件

为 MaiBot 读取 Android MaiStatus 上报的音乐、活动与位置事件，并与 [Mai_life](https://github.com/octmicy/Mai_life) 主动私聊机制联动。

## 功能

- `/mystatus`：查看最新音乐、活动和位置上报摘要
- `/mystatus music`、`activity`、`location`：按类别查询
- `/mystatus history`：近期上报记录
- `/mystatus ping`：服务健康检查
- LLM 工具 `maistatus_get_latest`、`maistatus_get_history`
- LLM 工具 `maistatus_planner_context`
- Hook `maisaka.planner.before_request`：检测 Mai_life 主动任务后请求最新状态并注入 Planner 上下文

## Mai_life 主动开聊联动

插件监听 `maisaka.planner.before_request`，只有检测到 Host 生成的 `plugin_proactive_task` 标记且插件 ID 为 `maibot-community.mai-life` 时，才考虑注入；普通被动回复不触发。适配基于 Mai_life 1.20.1 的任务标记格式。

WebUI「Mai_life 联动」配置：
- `planner_context_enabled`：联动总开关
- `auto_inject_planner`：自动注入 Planner 开关
- `proactive_only_context`：限制仅用于主动任务
- `context_cooldown_seconds`：每会话冷却，默认 900 秒
- `max_context_age_hours`：状态新鲜度参考窗口，默认 24 小时
- `inject_only_owner`：仅向主人主动任务注入，默认开启
- `owner_user_id`：主人 QQ 号，默认空

**要启用仅主人模式，请填写 `owner_user_id`。** 插件在无法确认主动任务目标是主人时会跳过注入，避免把私人状态带给朋友。目标匹配使用 Host 提供的用户 ID 或会话 ID；如果你的 MaiBot 会话 ID 不包含主人 QQ 号，需检查日志/会话格式并调整适配，不能直接关闭安全检查来绕过。

状态请求失败会 fail-open（不阻断 Planner）；冷却期内跳过请求。上下文强调这些内容是设备上报，不是主人刚刚发来的消息。麦麦可忽略不自然的开场线索。

## 安装和配置

1. 将插件目录放入 MaiBot 第三方插件目录并重载。
2. WebUI 配置「状态服务器」：
   - `base_url`: `https://maistatus.hhyyyy.cn`
   - `read_token`: 服务端 Bearer Token
3. 「Mai_life 联动」中确认 `planner_context_enabled` 和 `auto_inject_planner` 已启用，并填写主人 QQ 号。
4. 私聊运行 `/mystatus ping`。
5. 等 Mai_life 主动巡检选中主人后，查看日志是否出现 `MaiStatus context injected into Mai_life proactive Planner task`。

## 隐私

- 只发送 GET 请求读取状态。
- Token 只配置在 MaiBot 本地，不要提交 Git。
- 精确坐标默认隐藏，Planner 上下文不会包含精确经纬度。
- 默认按会话限频 15 分钟；失败不阻断主动对话。
- 不向群聊或朋友注入主人设备状态。

## API 契约

- `GET /healthz`
- `GET /api/v1/status/latest`
- `GET /api/v1/events?limit=10&event_type=music`

版本：1.2.0。
