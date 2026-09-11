#!/usr/bin/env python3
"""Codex MCP 桥接：把 Kimi WebBridge（127.0.0.1:10086）暴露为 Codex 可用的浏览器工具。

背景：Codex 官方内嵌浏览器 / Computer Use 是 OpenAI 云端服务，第三方
（kimi/deepseek）模式下报 "Codex auth token is unavailable" 不可用。
本桥接让 Codex 通过 Kimi 浏览器插件操作用户真实浏览器（自带登录态）。

协议：MCP stdio（换行分隔的 JSON-RPC）。仅依赖 Python 标准库。
"""
import json
import sys
import urllib.request

DAEMON = "http://127.0.0.1:10086/command"
SESSION = "codex"

TOOLS = [
    {
        "name": "browser_navigate",
        "description": "在用户真实浏览器中打开 URL（自带用户的登录会话）。返回 {url, tabId}。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "要打开的完整 URL"},
                "newTab": {"type": "boolean", "description": "是否新标签页打开，默认 true", "default": True},
            },
            "required": ["url"],
        },
    },
    {
        "name": "browser_snapshot",
        "description": "读取当前页面的可访问性树（文本结构 + 可交互元素的 @e 引用），用于理解页面内容和定位元素。优先于 evaluate。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "browser_click",
        "description": "点击元素。selector 用 browser_snapshot 返回的 @e 引用（如 @e123）或 CSS 选择器。",
        "inputSchema": {
            "type": "object",
            "properties": {"selector": {"type": "string"}},
            "required": ["selector"],
        },
    },
    {
        "name": "browser_fill",
        "description": "向输入框/富文本编辑器填入文本（清空后写入）。selector 用 @e 引用或 CSS 选择器。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string"},
                "value": {"type": "string"},
            },
            "required": ["selector", "value"],
        },
    },
    {
        "name": "browser_evaluate",
        "description": "在当前页面执行 JavaScript（支持 async/await），返回 JSON 序列化结果。仅在 snapshot 无法满足时使用。",
        "inputSchema": {
            "type": "object",
            "properties": {"code": {"type": "string"}},
            "required": ["code"],
        },
    },
    {
        "name": "browser_list_tabs",
        "description": "列出本次会话打开的所有标签页。",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def call_daemon(action, args):
    body = json.dumps({"action": action, "args": args, "session": SESSION}).encode()
    req = urllib.request.Request(DAEMON, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())
    if not data.get("ok"):
        raise RuntimeError(data.get("error") or data)
    return data.get("data")


def tool_call(name, args):
    if name == "browser_navigate":
        return call_daemon("navigate", {"url": args["url"], "newTab": args.get("newTab", True)})
    if name == "browser_snapshot":
        return call_daemon("snapshot", {})
    if name == "browser_click":
        return call_daemon("click", {"selector": args["selector"]})
    if name == "browser_fill":
        return call_daemon("fill", {"selector": args["selector"], "value": args["value"]})
    if name == "browser_evaluate":
        return call_daemon("evaluate", {"code": args["code"]})
    if name == "browser_list_tabs":
        return call_daemon("list_tabs", {})
    raise ValueError(f"unknown tool: {name}")


def send(msg):
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        rid = req.get("id")
        method = req.get("method", "")
        params = req.get("params") or {}

        if method == "initialize":
            send({
                "jsonrpc": "2.0", "id": rid,
                "result": {
                    "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "webbridge-mcp", "version": "1.0.0"},
                },
            })
        elif method == "notifications/initialized":
            pass
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            try:
                result = tool_call(params.get("name", ""), params.get("arguments") or {})
                text = json.dumps(result, ensure_ascii=False)
                # 防止超大 snapshot 撑爆上下文，截断到 15000 字符
                if len(text) > 15000:
                    text = text[:15000] + "…[truncated]"
                send({
                    "jsonrpc": "2.0", "id": rid,
                    "result": {"content": [{"type": "text", "text": text}]},
                })
            except Exception as e:
                send({
                    "jsonrpc": "2.0", "id": rid,
                    "result": {"content": [{"type": "text", "text": f"error: {e}"}], "isError": True},
                })
        elif rid is not None:
            send({"jsonrpc": "2.0", "id": rid, "result": {}})


if __name__ == "__main__":
    main()
