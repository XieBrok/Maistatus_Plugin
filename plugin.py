from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from maibot_sdk import MaiBotPlugin, Command, Tool, PluginConfigBase, Field, HookHandler
from maibot_sdk.types import HookMode, HookOrder, ToolParameterInfo, ToolParamType


class PluginSection(PluginConfigBase):
    __ui_label__ = "插件设置"
    __ui_order__ = 0
    enabled: bool = Field(default=True, description="启用插件")
    config_version: str = Field(default="1.2.0", description="插件配置版本")


class ServerSection(PluginConfigBase):
    __ui_label__ = "状态服务器"
    __ui_order__ = 1
    base_url: str = Field(default="https://maistatus.hhyyyy.cn", description="状态服务器根地址")
    read_token: str = Field(default="", description="只读 Bearer Token")
    timeout_seconds: int = Field(default=8, description="请求超时秒数（3-20）")
    history_limit: int = Field(default=10, description="历史默认条数（1-50）")
    include_exact_location: bool = Field(default=False, description="允许输出精确坐标（默认关闭）")


class LifeLinkSection(PluginConfigBase):
    __ui_label__ = "Mai_life 联动"
    __ui_order__ = 2
    planner_context_enabled: bool = Field(default=True, description="启用 Planner 状态上下文工具")
    proactive_only_context: bool = Field(default=True, description="状态上下文仅用于 Mai_life 主动开聊，不主动用于普通被动回复")
    context_cooldown_seconds: int = Field(default=900, description="主动状态查询最小间隔秒数，建议 900")
    max_context_age_hours: int = Field(default=24, description="状态有效时间窗口（小时），过期状态不应视为当前事实")
    auto_inject_planner: bool = Field(default=True, description="在 Mai_life 主动任务的 Planner 阶段自动拉取并注入状态")
    inject_only_owner: bool = Field(default=True, description="无法确认主人身份时不注入状态上下文")
    owner_user_id: str = Field(default="", description="主人 QQ 号，用于校验主动任务目标；开启仅主人模式时建议填写")


class Config(PluginConfigBase):
    plugin: PluginSection = Field(default_factory=PluginSection)
    server: ServerSection = Field(default_factory=ServerSection)
    mai_life: LifeLinkSection = Field(default_factory=LifeLinkSection)


def safe(value: Any, max_len: int = 180) -> str:
    if value is None:
        return ""
    return str(value).replace("\n", " ").replace("\r", " ")[:max_len]


def format_time(value: Any) -> str:
    try:
        stamp = int(value) / 1000
        return datetime.fromtimestamp(stamp, tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    except (TypeError, ValueError, OverflowError, OSError):
        return safe(value, 60) or "时间未知"


def _event_age_hours(value: Any) -> float | None:
    try:
        stamp = int(value) / 1000
        if stamp <= 0:
            return None
        return max(0.0, time.time() - stamp) / 3600
    except (TypeError, ValueError, OverflowError):
        return None


def _proactive_task_from_payload(kwargs: dict[str, Any]) -> bool:
    """Recognize only the structured host-generated Mai_life task marker."""
    payload = kwargs.get("items")
    if not isinstance(payload, list):
        payload = kwargs.get("messages")
    if not isinstance(payload, list):
        return False
    for item in payload:
        if not isinstance(item, dict):
            continue
        parts = item.get("parts")
        texts: list[str] = []
        if isinstance(parts, list):
            texts.extend(str(part.get("text") or "") for part in parts
                         if isinstance(part, dict) and str(part.get("type") or "").lower() == "text")
        else:
            content = item.get("content")
            if isinstance(content, str):
                texts.append(content)
            elif isinstance(content, list):
                texts.extend(str(part.get("text") or "") for part in content if isinstance(part, dict))
        for text in texts:
            if re.search(r'<plugin_proactive_task\b[^>]*plugin_id="maibot-community\.mai-life"[^>]*>', text, flags=re.I):
                return True
    return str(kwargs.get("intent") or "") == "mai_life_proactive"


class MaiStatusPlugin(MaiBotPlugin):
    config_model = Config

    def __init__(self) -> None:
        super().__init__()
        self._last_linked_context_at = 0.0
        self._last_linked_context_by_session: dict[str, float] = {}

    async def on_load(self) -> None:
        self.ctx.logger.info("MaiStatus 插件已加载（Mai_life 联动可按配置启用）")

    async def on_unload(self) -> None:
        """Release plugin-owned state when MaiBot unloads or reloads this plugin."""
        self._last_linked_context_by_session.clear()
        self._last_linked_context_at = 0.0
        self.ctx.logger.info("MaiStatus 插件已卸载")

    def _request(self, path: str) -> dict[str, Any]:
        cfg = self.config.server
        base = cfg.base_url.strip().rstrip("/")
        if not base.startswith("https://") and not base.startswith("http://127.0.0.1"):
            raise ValueError("服务器地址必须使用 HTTPS（本机回环地址除外）")
        if not cfg.read_token.strip():
            raise ValueError("请先配置状态服务器只读 Token")
        req = urllib.request.Request(
            base + path,
            headers={"Authorization": "Bearer " + cfg.read_token.strip(),
                     "Accept": "application/json", "User-Agent": "MaiStatus-MaiBot/1.2"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=max(3, min(int(cfg.timeout_seconds), 20))) as response:
                payload = json.loads(response.read(1024 * 1024).decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("服务器返回的 JSON 不是对象")
                return payload
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise RuntimeError("鉴权失败，请检查只读 Token") from exc
            raise RuntimeError(f"服务器 HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"无法连接服务器：{safe(exc.reason, 100)}") from exc

    def _latest_text(self, payload: dict[str, Any], category: str = "all", *, planner: bool = False) -> str:
        labels = {"location": "位置", "activity": "活动", "music": "音乐"}
        keys = [category] if category in labels else ["music", "activity", "location"]
        lines = ["【主人设备状态｜来自 MaiStatus API】" if planner else "📡 个人状态摘要"]
        found = False
        for key in keys:
            item = payload.get(key)
            if not isinstance(item, dict):
                continue
            found = True
            age = _event_age_hours(item.get("event_time"))
            freshness = "时间未知" if age is None else (f"{age:.1f} 小时前" if age < 24 else f"约 {age:.0f} 小时前")
            lines.append(f"\n【{labels[key]}】上报时间：{format_time(item.get('event_time'))}（{freshness}）")
            if key == "music":
                state = safe(item.get("state"), 30) or "未知"
                title = safe(item.get("title"), 120) or "未知曲目"
                artist = safe(item.get("artist"), 100)
                lines.append(f"播放状态：{state}；曲目：{title}" + (f"；歌手：{artist}" if artist else ""))
            elif key == "activity":
                lines.append(f"活动类型代码：{safe(item.get('activity_type'), 20) or '未知'}；置信度：{safe(item.get('confidence'), 8) or '未知'}%")
            elif key == "location":
                if self.config.server.include_exact_location and not planner:
                    lat, lon = item.get("latitude"), item.get("longitude")
                    if lat is not None and lon is not None:
                        lines.append(f"坐标：{safe(lat, 24)}, {safe(lon, 24)}")
                else:
                    lines.append("收到过位置上报；不向 Planner 提供精确坐标。")
        if not found:
            lines.append("服务器尚无状态记录。")
        if payload.get("last_event_time"):
            lines.append(f"\n最近一次状态上报：{format_time(payload['last_event_time'])}")
        if planner:
            max_age = max(1, int(self.config.mai_life.max_context_age_hours))
            ages = [_event_age_hours(payload.get(key, {}).get("event_time"))
                    for key in ("music", "activity", "location") if isinstance(payload.get(key), dict)]
            if not ages or all(age is None or age > max_age for age in ages):
                lines.append(f"\n【新鲜度边界】全部或部分状态可能已过期（参考窗口 {max_age} 小时）；不可断言主人此刻仍在做这些事。")
            lines.append(
                "\n【Planner 使用规则】这只是设备上报背景，不是主人刚刚发来的消息。"
                "可以据此形成自然、低压力的开场，但不要逐项播报、不要推断精确行踪。"
                "只有音乐或活动等线索自然相关时才提及；状态过期、信息空缺或话题不自然时可忽略。"
            )
        else:
            lines.append("\n隐私提示：位置坐标默认隐藏。")
        return "\n".join(lines)

    def _history_text(self, payload: dict[str, Any]) -> str:
        events = payload.get("events", [])
        if not isinstance(events, list) or not events:
            return "暂时没有历史上报记录。"
        lines = [f"🗂️ 最近上报记录（{len(events)} 条）"]
        for index, event in enumerate(events, 1):
            if not isinstance(event, dict):
                continue
            kind = safe(event.get("event_type"), 30) or "未知"
            when = format_time(event.get("event_time"))
            data = event.get("data") if isinstance(event.get("data"), dict) else {}
            summary = ""
            if kind == "music":
                summary = safe(data.get("title"), 100)
                artist = safe(data.get("artist"), 80)
                if artist:
                    summary += " - " + artist
                state = safe(data.get("state"), 20)
                if state:
                    summary += f" ({state})"
            elif kind == "activity":
                summary = f"活动代码 {safe(data.get('activity_type'), 20)}，置信度 {safe(data.get('confidence'), 8)}%"
            elif kind == "location":
                summary = "位置事件（坐标已隐藏）"
                if self.config.server.include_exact_location:
                    summary = f"坐标 {safe(data.get('latitude'), 20)}, {safe(data.get('longitude'), 20)}"
            lines.append(f"{index}. {when}｜{kind}" + (f"｜{summary}" if summary else ""))
        return "\n".join(lines)

    @Tool("maistatus_get_latest", brief_description="查询主人上传到个人状态服务器的最新音乐、活动和位置状态。")
    async def tool_get_latest(self, **kwargs: Any) -> dict[str, Any]:
        del kwargs
        try:
            return {"content": self._latest_text(self._request("/api/v1/status/latest"))}
        except Exception as exc:
            self.ctx.logger.warning("MaiStatus latest query failed: %s", exc)
            return {"content": "查询个人状态失败：" + safe(exc, 180)}

    @Tool(
        "maistatus_get_history",
        brief_description="查询个人状态服务器的近期上报记录，可按音乐、活动或位置筛选。",
        parameters=[
            ToolParameterInfo(name="limit", param_type=ToolParamType.INTEGER, description="记录条数，1-50", required=False),
            ToolParameterInfo(name="event_type", param_type=ToolParamType.STRING, description="可选：music、activity、location", required=False),
        ],
    )
    async def tool_get_history(self, limit: int = 10, event_type: str = "", **kwargs: Any) -> dict[str, Any]:
        del kwargs
        try:
            limit = max(1, min(int(limit), 50))
            params: dict[str, Any] = {"limit": limit}
            if event_type in {"music", "activity", "location"}:
                params["event_type"] = event_type
            return {"content": self._history_text(self._request("/api/v1/events?" + urllib.parse.urlencode(params)))}
        except Exception as exc:
            self.ctx.logger.warning("MaiStatus history query failed: %s", exc)
            return {"content": "查询历史记录失败：" + safe(exc, 180)}

    @Tool(
        "maistatus_planner_context",
        brief_description="供 Mai_life 主动私聊 Planner 获取主人最近上报的音乐/活动状态；仅在准备主动找主人时调用。",
        detailed_description=(
            "用于 Mai_life 与 MaiStatus 的主动聊天联动。仅当本轮是 Mai_life 已选择的主动私聊任务，"
            "且确实需要一个自然开场线索时调用。返回主人设备近期状态和新鲜度边界。"
            "不要每次普通回复调用；不要把旧状态说成实时事实；不要向群聊或其他朋友泄露；"
            "精确位置永远不进入此工具返回结果。无关或不自然时可以忽略状态。"
        ),
    )
    async def tool_planner_context(self, **kwargs: Any) -> dict[str, Any]:
        del kwargs
        cfg = self.config.mai_life
        if not cfg.planner_context_enabled:
            return {"content": "MaiStatus 的 Planner 联动工具已关闭。"}
        now = time.time()
        cooldown = max(0, min(int(cfg.context_cooldown_seconds), 86400))
        if cooldown and now - self._last_linked_context_at < cooldown:
            remain = int(cooldown - (now - self._last_linked_context_at))
            return {"content": f"状态上下文处于冷却中，约 {remain} 秒后可再次请求。"}
        try:
            payload = self._request("/api/v1/status/latest")
            result = self._latest_text(payload, planner=True)
            self._last_linked_context_at = now
            return {"content": result}
        except Exception as exc:
            self.ctx.logger.warning("MaiStatus Planner context query failed: %s", exc)
            return {"content": "状态上下文暂时不可用：" + safe(exc, 180)}


    @staticmethod
    def _append_context(kwargs: dict[str, Any], note: str) -> bool:
        """Append context to MaiBot planner payloads (legacy messages or Item-first)."""
        items = kwargs.get("items")
        if isinstance(items, list):
            for item in reversed(items):
                if not isinstance(item, dict) or item.get("item_type") != "SystemMessageItem":
                    continue
                parts = item.get("parts")
                if not isinstance(parts, list):
                    item["parts"] = [{"type": "text", "text": note}]
                    return True
                if parts and isinstance(parts[-1], dict) and parts[-1].get("type") == "text":
                    parts[-1]["text"] = str(parts[-1].get("text") or "") + "\n\n" + note
                else:
                    parts.append({"type": "text", "text": note})
                return True
            from datetime import datetime
            import uuid
            items.insert(0, {
                "item_type": "SystemMessageItem",
                "meta": {"item_id": f"maistatus-{uuid.uuid4().hex}", "logical_turn_id": None,
                         "timestamp": datetime.now().isoformat()},
                "parts": [{"type": "text", "text": note}],
            })
            return True
        messages = kwargs.get("messages")
        if isinstance(messages, list):
            for item in messages:
                if isinstance(item, dict) and str(item.get("role") or "").lower() == "system" and isinstance(item.get("content"), str):
                    item["content"] += "\n\n" + note
                    return True
            messages.insert(0, {"role": "system", "content": note})
            return True
        return False

    @HookHandler("maisaka.planner.before_request", mode=HookMode.BLOCKING, order=HookOrder.LATE, timeout_ms=12000)
    async def on_planner_before_request(self, **kwargs: Any) -> dict[str, Any]:
        """Inject latest device context only into Mai_life proactive private planner tasks."""
        cfg = self.config.mai_life
        if not self.config.plugin.enabled or not cfg.planner_context_enabled or not cfg.auto_inject_planner:
            return {"action": "continue"}
        is_proactive = _proactive_task_from_payload(kwargs)
        if cfg.proactive_only_context and not is_proactive:
            return {"action": "continue"}

        payload = kwargs.get("items")
        if not isinstance(payload, list):
            payload = kwargs.get("messages")
        marker_found = False
        if isinstance(payload, list):
            for item in payload:
                if not isinstance(item, dict):
                    continue
                parts = item.get("parts")
                texts: list[str] = []
                if isinstance(parts, list):
                    texts.extend(str(part.get("text") or "") for part in parts
                                 if isinstance(part, dict) and str(part.get("type") or "").lower() == "text")
                else:
                    content = item.get("content")
                    if isinstance(content, str):
                        texts.append(content)
                    elif isinstance(content, list):
                        texts.extend(str(part.get("text") or "") for part in content if isinstance(part, dict))
                for text in texts:
                    if "<plugin_proactive_task" in text:
                        marker_found = True
                        if not re.search(r'<plugin_proactive_task\b[^>]*plugin_id="maibot-community\.mai-life"[^>]*>', text, flags=re.I):
                            return {"action": "continue"}
        if not marker_found and str(kwargs.get("intent") or "") != "mai_life_proactive":
            return {"action": "continue"}
        # Do not inject into group-like planner sessions if the host exposes chat type.
        chat_type = str(kwargs.get("chat_type") or kwargs.get("session_type") or "").lower()
        if chat_type in {"group", "guild", "channel"}:
            return {"action": "continue"}

        session = str(kwargs.get("session_id") or "")
        if cfg.inject_only_owner:
            owner_id = "".join(ch for ch in str(cfg.owner_user_id or "") if ch.isdigit())
            target_id = str(kwargs.get("user_id") or kwargs.get("target_user_id") or kwargs.get("recipient_id") or "")
            session_digits = "".join(ch for ch in session if ch.isdigit())
            # Fail closed unless the hook can match a configured owner identifier against
            # host-supplied recipient metadata or the private session ID.
            if not owner_id or not (
                target_id == owner_id or
                (session_digits and session_digits.endswith(owner_id))
            ):
                return {"action": "continue"}
        now = time.time()
        cooldown = max(0, min(int(cfg.context_cooldown_seconds), 86400))
        if cooldown:
            last = self._last_linked_context_by_session.get(session, 0.0)
            if now - last < cooldown:
                return {"action": "continue"}
        try:
            status_payload = self._request("/api/v1/status/latest")
            note = self._latest_text(status_payload, planner=True)
            if self._append_context(kwargs, note):
                self._last_linked_context_at = now
                if session:
                    self._last_linked_context_by_session[session] = now
                self.ctx.logger.info("MaiStatus context injected into Mai_life proactive Planner task")
                return {"action": "continue", "modified_kwargs": kwargs}
        except Exception as exc:
            self.ctx.logger.warning("MaiStatus automatic Planner injection skipped: %s", safe(exc, 180))
        return {"action": "continue"}


    @Command("mystatus", description="查看个人状态：最新状态、音乐、活动、位置或历史", pattern=r"^/mystatus(?:\s+(?P<action>music|activity|location|history|ping))?\s*$", aliases=["/我的状态"])
    async def command_mystatus(self, **kwargs: Any):
        stream_id = kwargs.get("stream_id", "")
        action = ((kwargs.get("matched_groups") or {}).get("action") or "").strip().lower()
        try:
            if action == "ping":
                data = self._request("/healthz")
                text = "✅ 状态服务器可访问：" + safe(data.get("service"), 80) + " v" + safe(data.get("version"), 30)
            elif action == "history":
                limit = max(1, min(int(self.config.server.history_limit), 50))
                data = self._request("/api/v1/events?" + urllib.parse.urlencode({"limit": limit}))
                text = self._history_text(data)
            else:
                data = self._request("/api/v1/status/latest")
                text = self._latest_text(data, action or "all")
        except Exception as exc:
            text = "❌ MaiStatus 查询失败：" + safe(exc, 180)
        if stream_id:
            await self.ctx.send.text(text, stream_id)
        return True, text, 2


def create_plugin() -> MaiStatusPlugin:
    return MaiStatusPlugin()
