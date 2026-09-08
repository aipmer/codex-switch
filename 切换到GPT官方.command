#!/bin/bash
# 注意：切换请只用本入口，不要在 CC Switch 界面点「启用」（它不写实际配置，详见 README.md）
"$(cd "$(dirname "$0")" && pwd)/codex-switch.sh" openai
read -n 1 -s -r -p "按任意键关闭窗口..."
