# MaiStatus MaiBot 插件

为 MaiBot 读取 Android MaiStatus 上报的音乐、活动与位置事件，并与 [Mai_life](https://github.com/octmicy/Mai_life) 主动私聊机制联动。

## 功能

- `/mystatus`：查看最新音乐、活动和位置上报摘要
- `/mystatus music`、`activity`、`location`：按类别查询
- `/mystatus history`：近期上报记录
- `/mystatus ping`：服务健康检查
- LLM 工具 `maistatus_get_latest`、`maistatus_get_history`
- LLM 工具 `maistatus_planner_context`：查询主动开场背景
- Hook `maisaka.planner.before_request`：识别 Mai_life 的主动任务标记后，请求最新状态并自动注入 Planner 上下文

## Mai_life 主动开聊联动

插件监听 `maisaka.planner.before_request`，只在看到 Host 生成的 `plugin_proactive_task` 标记且 `plugin_id="maibot-community.mai-life"` 时注入状态；普通被动回复默认不会触发。当前主动任务判定基于 Mai_life 1.20.1 的任务标记格式。

自动联动默认开启，可在 WebUI 的「Mai_life 联动」配置节调整：
- `planner_context_enabled`：总开关
- `auto_inject_planner`：自动注入 Planner 开关
- `proactive_only_context`：仅在主动任务中请求
- `context_cooldown_seconds`：按会话冷却，默认 900 秒
- `max_context_age_hours`：新鲜度参考窗口，默认 24 小时

状态 API 请求失败会 fail-open（不阻断 Planner）；冷却期内跳过本次 API 请求。上下文强调该数据是设备上报，不是主人当前发言，麦麦可以忽略不自然的开场线索。

## 安装和配置

1. 将插件目录放入 MaiBot 的第三方插件目录，重载插件。
2. 在 WebUI 设置：
   - `base_url`: `https://maistatus.hhyyyy.cn`
   - `read_token`: 状态服务器 Bearer Token
3. 私聊运行 `/mystatus ping` 测试接口。
4. 当 Mai_life 主动巡检选中主动私聊任务后，检查 MaiStatus 日志是否出现 `MaiStatus context injected into Mai_life proactive Planner task`。

## 隐私

- 仅使用 GET 请求读取服务端数据。
- Token 仅配置于本地，不要提交至 Git。
- 精确坐标默认隐藏，且 Planner 上下文永远不会包含精确经纬度。
- 插件按会话冷却请求，默认 15 分钟；失败不会阻断主动对话。
- 只在 Mai_life 主动任务标记命中时注入，不要把私人设备状态转发给群聊或朋友。

## API 契约

- `GET /healthz`
- `GET /api/v1/status/latest`
- `GET /api/v1/events?limit=10&event_type=music`

版本：1.2.0。
