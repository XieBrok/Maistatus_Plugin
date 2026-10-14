# MaiStatus MaiBot 插件

把 Android MaiStatus 上传的个人状态提供给 MaiBot 查询。适配 [MaiStatus Server](https://github.com/XieBrok/Maistatus-Server) 的 FastAPI API。

## 功能

- `/mystatus`：查看最新音乐、活动和位置上报摘要
- `/mystatus music`：查看音乐播放状态
- `/mystatus activity`：查看活动识别状态
- `/mystatus location`：查看位置上报情况（默认隐藏坐标）
- `/mystatus history`：查看近期事件
- `/mystatus ping`：检查服务器健康接口
- LLM 工具 `maistatus_get_latest`：自然语言查询最新状态
- LLM 工具 `maistatus_get_history`：查询历史记录，可按事件类别筛选

## 安装

1. 将插件目录放进 MaiBot 使用的第三方插件目录。
2. 重载插件，在插件配置页面的「状态服务器」配置节中设置：
   - `base_url`: `https://maistatus.hhyyyy.cn`
   - `read_token`: 状态服务端接受的 Bearer Token
3. 在私聊中运行 `/mystatus ping`，再试 `/mystatus`。

## 安全

- 插件只发起 GET 请求，不会创建、修改或删除状态数据。
- Token 只在 MaiBot 本地配置；不要提交 Token、`config.toml` 或个人数据。
- 精确位置默认隐藏。除非确认需要，不要启用 `include_exact_location`。
- 建议先在私聊测试，避免在群聊中泄露私人位置或音乐状态。

## API 契约

- `GET /healthz`
- `GET /api/v1/status/latest` 返回顶层 `location`、`activity`、`music`、`last_event_time`
- `GET /api/v1/events?limit=10&event_type=music` 返回 `count`、`events`，每条事件含 `event_time`、`event_type`、`data`

## 测试与兼容性

版本 1.1.0。代码按服务端公开的 `main.py` 返回结构编写。请在你的实际 MaiBot 容器里完成加载、Token 鉴权和聊天联调；API 连接器无法替代线上环境测试。
