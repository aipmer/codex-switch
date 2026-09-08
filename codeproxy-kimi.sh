#!/bin/bash
# Kimi Code 本地协议路由（Codex Responses API -> Kimi chat/completions）
# 由 launchd（com.codexswitch.codeproxy-kimi）常驻托管
#
# codeproxy 安装见 Kimi Code 官方文档：https://www.kimi.com/code/docs/
# API Key 在 Kimi Code 控制台申请后替换下面的 YOUR_KIMI_API_KEY

exec codeproxy \
  --base-url https://api.kimi.com/coding/v1/chat/completions \
  --apikey "YOUR_KIMI_API_KEY" \
  --port 8787
