# MaiStatus MaiBot 插件

给 MaiBot 提供 MaiStatus 设备状态查询，并可与 [Mai_life](https://github.com/octmicy/Mai_life) 的主动私聊 Planner 配合使用。

## 功能

- \`/mystatus\`：查看最新音乐、活动和位置上报摘要
- \`/mystatus music\` / \`activity\` / \`location\`：按类型查询
- \`/mystatus history\`：查看近期事件
- \`/mystatus ping\`：健康检查
- 工具 \`maistatus_get_latest\`、\`maistatus_get_history\`
- 工具 \`maistatus_planner_context\`：为准备主动发起私聊的 Planner 提供带新鲜度边界的状态背景

## Mai_life 联动说明

本插件提供 \`maistatus_planner_context\` 专用工具。它返回音乐、活动及状态上报时间；精确坐标不会进入该工具结果。状态过期时会提示 Planner 不要把它说成实时事实。默认冷却 15 分钟。

**要实现“主动发起对话前自动请求并注入 Planner”仍需修改 Mai_life。** Mai_life 由 \`ProactiveEngine.patrol()\` 选择主动候选，通过 Host 主动任务机制触发 Planner，随后由 \`maisaka.planner.before_request\` Hook 加入上下文。其他插件注册工具，不会自动执行该 Hook 中的 HTTP 请求或把工具结果强制注入 Planner。

因此推荐在 Mai_life 的 \`MaiLifePlugin.on_planner\` 中，在确认本轮是普通主动私聊任务后调用 MaiStatus 的受支持接口，将结果追加到 \`suffix\`；群聊、转述、被动回复均跳过。状态请求失败必须 fail-open，不影响原有 Planner。该仓库所有者对 \`octmicy/Mai_life\` 没有写权限，所以不能直接替上游提交其源码改动。

## 安装和配置

1. 将插件目录放进 MaiBot 第三方插件目录并重载。
2. WebUI 配置「状态服务器」：
   - \`base_url\`: \`https://maistatus.hhyyyy.cn\`
   - \`read_token\`: 状态服务器 Bearer Token
3. 「Mai_life 联动」中启用 \`planner_context_enabled\`，调整冷却与状态有效期。
4. 在私聊执行 \`/mystatus ping\` 验证。

注意：工具注册成功不代表 Mai_life 已自动调用。要保证 Planner 每次处理符合条件的主动任务时都获取状态，需要 Mai_life Hook 集成。

## 隐私与安全

- 仅用 GET 请求读取服务端，不修改或删除事件。
- Token 仅放在 MaiBot 本地配置，不要提交到 Git。
- 精确位置默认隐藏，且 \`maistatus_planner_context\` 永远不返回精确坐标。
- 状态只用于自然的开场灵感；过期或不自然时忽略，不要向群聊/朋友泄露主人隐私。

## API

- \`GET /healthz\`
- \`GET /api/v1/status/latest\`
- \`GET /api/v1/events?limit=10&event_type=music\`

版本：1.2.0。
