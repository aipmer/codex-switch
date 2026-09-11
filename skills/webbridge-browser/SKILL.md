---
name: webbridge-browser
description: 操作用户的真实浏览器（自带登录会话）——打开网页、读取页面、点击、填表、执行 JS。当需要浏览网页、操作需要登录的网站、或用户要求"在浏览器里"做某事时使用。本机 WebBridge 守护进程已在 127.0.0.1:10086 运行。
---

# WebBridge 浏览器控制

通过本地守护进程 `http://127.0.0.1:10086/command` 控制用户的真实 Chrome 浏览器（带用户登录态）。**不要**尝试 Codex 内置的 Computer Use / 内嵌浏览器——那是 OpenAI 云端服务，当前模式不可用（报 `Codex auth token is unavailable`）。

## 调用方式

用 `exec_command` 发 curl POST，JSON 请求体：

```bash
curl -s -X POST http://127.0.0.1:10086/command \
  -H 'Content-Type: application/json' \
  -d '{"action":"<动作>","args":{...},"session":"codex"}'
```

`session` 固定用 `"codex"`。返回 `{"ok":true,"data":{...}}`。

## 可用动作

| action | args | 说明 |
|--------|------|------|
| `navigate` | `url`, `newTab`(bool), 首次调用加 `group_title:"Codex 浏览器操作"` | 打开 URL，返回 tabId |
| `snapshot` | 无 | 读取页面可访问性树（文本结构 + 可交互元素的 `@e` 引用），**定位元素优先用它** |
| `click` | `selector` | 点击，selector 用 snapshot 的 `@e` 引用或 CSS |
| `fill` | `selector`, `value` | 输入框/富文本填文本（清空后写入） |
| `evaluate` | `code` | 执行 JS（支持 async/await），仅在 snapshot 不够时用 |
| `list_tabs` | 无 | 列出本会话打开的标签页 |

## 典型流程

1. `navigate` 打开页面（首次带 `group_title`）
2. `snapshot` 读结构，找到目标元素的 `@e` 引用
3. `click` / `fill` 操作；页面跳转后重新 `snapshot`
4. 需要提取数据时优先 `snapshot` 读文本，复杂场景用 `evaluate` 执行 `document.body.innerText` 等

## 注意

- 返回的 snapshot 很大时，用 `evaluate` 精准提取所需部分
- 涉及支付、发帖、发消息等对外可见操作前，先向用户确认
- 守护进程未响应时（connection refused），先执行 `~/.kimi-webbridge/bin/kimi-webbridge start` 再重试
