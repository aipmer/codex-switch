#!/usr/bin/env python3
"""Kimi schema 修正垫片：监听 8788，修正 Codex 工具 schema 后转发给 codeproxy(8787)。

背景：Codex 内置 codex_app MCP 工具的 parameters 含 {"$ref": ..., "type": ...}
兄弟字段写法（JSON Schema 2020-12 合法），但 Kimi(moonshot) 校验器拒绝，
报 "tools.function.parameters is not a valid moonshot flavored json schema"。
本垫片把带兄弟字段的 $ref 就地展开合并，其余流量原样透传。

2026-10-22 新增：清理 responses input 里会产生「空 assistant」的条目
（空 reasoning / 空 assistant 消息），修复 Kimi 报错
"the message at position N with role 'assistant' must not be empty"。
详见 clean_input 注释。
"""
import json
import re
import copy
import http.server
import urllib.request
import urllib.error

UPSTREAM = "http://127.0.0.1:8787"
LISTEN = ("127.0.0.1", 8788)

REF_RE = re.compile(r'^#/\$defs/(.+)$')
_stats = {"requests": 0, "fixed": 0, "dropped": 0}


def _text_of(parts):
    """从 content/summary 列表提取拼接文本。"""
    out = ""
    if isinstance(parts, str):
        return parts
    if isinstance(parts, list):
        for p in parts:
            if isinstance(p, str):
                out += p
            elif isinstance(p, dict):
                out += str(p.get("text") or "")
    return out


def clean_input(data):
    """清理 responses input 里会产生「空 assistant」的条目（2026-10-22）。

    codeproxy 转换时，只要上一条不是 assistant 就新建 {role:assistant, content:null}：
    - 完全空的 reasoning（content/summary 都无文字）→ 裸 assistant（content=null，
      reasoning_content=""，不会被占位符回填）→ Kimi 报 "must not be empty"
    - content 为空的 assistant message → 同样产生裸 assistant
    处理：空 reasoning 直接丢弃（不携带任何信息）；summary 有文字但 content 空的
    reasoning 把 summary 文字搬进 content；空 assistant 消息直接丢弃。
    """
    items = data.get("input")
    if not isinstance(items, list):
        return 0
    kept = []
    dropped = 0
    for it in items:
        if not isinstance(it, dict):
            kept.append(it)
            continue
        t = it.get("type")
        if t == "reasoning":
            content_text = _text_of(it.get("content"))
            if not content_text.strip():
                summary_text = _text_of(it.get("summary"))
                if summary_text.strip():
                    it = dict(it)
                    it["content"] = [{"type": "reasoning_text", "text": summary_text}]
                    kept.append(it)
                else:
                    dropped += 1
                continue
        elif t == "message" and it.get("role") == "assistant":
            if not _text_of(it.get("content")).strip():
                dropped += 1
                continue
        kept.append(it)
    if dropped or len(kept) != len(items):
        data["input"] = kept
    return dropped


def fix_schema(node, defs, counter):
    """递归修正：带兄弟字段的 $ref 展开为 目标定义+兄弟字段 的合并副本。"""
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and len(node) > 1:
            m = REF_RE.match(ref)
            if m:
                name = m.group(1)
                target = defs.get(name)
                if isinstance(target, dict):
                    merged = copy.deepcopy(target)
                    for k, v in node.items():
                        if k != "$ref":
                            merged[k] = v
                    counter[0] += 1
                    node.clear()
                    node.update(merged)
                    fix_schema(node, defs, counter)
                    return
        for v in node.values():
            fix_schema(v, defs, counter)
    elif isinstance(node, list):
        for v in node:
            fix_schema(v, defs, counter)


def sanitize(body_bytes):
    try:
        data = json.loads(body_bytes)
    except Exception:
        return body_bytes, 0
    dropped = clean_input(data)
    if dropped:
        _stats["dropped"] += dropped
    tools = data.get("tools")
    if not isinstance(tools, list):
        if dropped:
            return json.dumps(data).encode(), 0
        return body_bytes, 0
    counter = [0]

    def walk(node):
        # 任何带 $defs 的 dict（parameters / namespace 内层 tool 等）都处理
        if isinstance(node, dict):
            defs = node.get("$defs")
            if isinstance(defs, dict):
                fix_schema(node, defs, counter)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(tools)
    if counter[0] or dropped:
        return json.dumps(data).encode(), counter[0]
    return body_bytes, 0


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, status, body, ctype="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _relay(self, body):
        url = UPSTREAM + self.path
        fixed_body, n = sanitize(body)
        _stats["requests"] += 1
        _stats["fixed"] += n
        headers = {"Content-Type": self.headers.get("Content-Type", "application/json")}
        for h in ("authorization", "session-id", "originator", "openai-beta"):
            if self.headers.get(h):
                headers[h] = self.headers[h]
        req = urllib.request.Request(url, data=fixed_body, headers=headers, method=self.command)
        try:
            resp = urllib.request.urlopen(req, timeout=600)
            status, resp_headers = resp.status, resp.headers
        except urllib.error.HTTPError as e:
            status, resp_headers, resp = e.code, e.headers, e
        except Exception as e:
            self._send(502, json.dumps({"error": {"message": f"schema-shim upstream error: {e}"}}).encode())
            return
        # 流式透传（SSE 友好）：不定长，读到底后关闭连接
        self.send_response(status)
        ctype = resp_headers.get("Content-Type")
        if ctype:
            self.send_header("Content-Type", ctype)
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            resp.close()
        self.close_connection = True

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        self._relay(body)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, json.dumps({"ok": True, **_stats}).encode())
            return
        self._relay(b"")


if __name__ == "__main__":
    srv = http.server.ThreadingHTTPServer(LISTEN, Handler)
    print(f"schema-shim listening on http://{LISTEN[0]}:{LISTEN[1]} -> {UPSTREAM}")
    srv.serve_forever()
