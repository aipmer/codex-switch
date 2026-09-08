#!/bin/bash
# Codex 供应商一键切换：./codex-switch.sh openai|deepseek|kimi
# 自动完成：退出 Codex 应用 → 替换配置 → 同步会话显示标记 →
#           改写历史会话模型名 → （仅 openai）清理第三方 reasoning 残留 → 重启应用
#
# 注意：如果你同时装了 CC Switch，不要在它的界面里点「启用」来切换——
# 它只改自己的数据库标记，不会写入 ~/.codex/config.toml（v3.19.2 与 v3.20.1
# 均已实测确认，接管模式同样不写）。真实切换只能跑本脚本或双击对应的 .command。
set -e
MODE="$1"
DIR="$(cd "$(dirname "$0")" && pwd)"
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"

# Kimi 本地路由的 launchd 服务名（安装 codeproxy 时使用的 Label，
# 见 README「Kimi 本地路由」一节；不用 Kimi 可忽略）
LAUNCHD_LABEL="${CODEX_SWITCH_LAUNCHD_LABEL:-com.codexswitch.codeproxy-kimi}"

# Codex 应用与 CLI 路径（默认 ChatGPT 桌面应用内置的 codex）
CODEX_APP="${CODEX_SWITCH_APP:-ChatGPT}"
CODEX_CLI="${CODEX_SWITCH_CLI:-/Applications/ChatGPT.app/Contents/Resources/codex}"

if [ "$MODE" != "openai" ] && [ "$MODE" != "deepseek" ] && [ "$MODE" != "kimi" ]; then
  echo "用法: $0 openai|deepseek|kimi"; exit 1
fi

echo "正在退出 Codex 应用..."
osascript -e "tell application \"$CODEX_APP\" to quit" 2>/dev/null || true
sleep 3

if [ "$MODE" = "kimi" ]; then
  echo "确保 Kimi 本地路由运行中..."
  launchctl kickstart -k "gui/$(id -u)/$LAUNCHD_LABEL" 2>/dev/null || \
    launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/$LAUNCHD_LABEL.plist" 2>/dev/null || true
  sleep 2
fi

echo "写入 $MODE 配置..."
cp "$DIR/config-$MODE.toml" "$CODEX_HOME/config.toml"

echo "同步会话显示标记..."
if [ "$MODE" = "openai" ]; then
  FROM="custom"; TO="openai"
else
  FROM="openai"; TO="custom"
fi
python3 - "$CODEX_HOME" "$FROM" "$TO" <<'PYEOF'
import sqlite3, sys, os, shutil
home, frm, to = sys.argv[1], sys.argv[2], sys.argv[3]
db = os.path.join(home, 'state_5.sqlite')
if not os.path.exists(db):
    print("未找到 state_5.sqlite，跳过"); raise SystemExit
shutil.copy(db, db + '.bak-switch')
con = sqlite3.connect(db)
cur = con.execute("update threads set model_provider=? where model_provider=?", (to, frm))
print(f"已更新 {cur.rowcount} 条会话标记: {frm} -> {to}")
con.commit(); con.close()
PYEOF

echo "同步 CC Switch 启用标记（如已安装）..."
python3 - "$MODE" <<'PYEOF'
import sqlite3, sys, os
mode = sys.argv[1]
# 按供应商名字模糊匹配，不同安装里 UUID 各不相同
kw = {'openai': 'openai%', 'deepseek': 'deepseek%', 'kimi': 'kimi%'}[mode]
db = os.path.expanduser('~/.cc-switch/cc-switch.db')
if not os.path.exists(db):
    print("未安装 CC Switch，跳过"); raise SystemExit
try:
    con = sqlite3.connect(db)
    con.execute("update providers set is_current=0 where app_type='codex'")
    cur = con.execute("update providers set is_current=1 where app_type='codex' and lower(name) like ?", (kw,))
    con.commit(); con.close()
    print(f"CC Switch 标记已同步: {mode}（匹配 {cur.rowcount} 个供应商）")
except sqlite3.Error as e:
    print(f"CC Switch db 结构不兼容，跳过: {e}")
PYEOF

echo "改写历史会话模型名（解决续聊 compact 钉死模型名问题）..."
# codex 续聊时的 pre-sampling compact 使用会话 rollout 元数据里记录的模型名，
# 与当前配置无关。跨供应商续聊时对方 API 不认识该名字会报 invalid_request_error
# （在 codex 0.153.4 实测确认）。这里把历史里的模型名统一改写成目标供应商
# 的模型名。只动模型归属元数据，会话内容不受影响；每个文件首次改写前留 .bak-model。
python3 - "$MODE" "$CODEX_HOME" <<'PYEOF'
import os, re, sys, shutil

mode, home = sys.argv[1], sys.argv[2]
# 各供应商认识的模型名（不在白名单里的会被改写成默认名，按需修改）
cfg = {
    'openai':   (re.compile(r'^gpt-'), 'gpt-5.6-sol'),
    'deepseek': (re.compile(r'^deepseek-'), 'deepseek-v4-flash'),
    'kimi':     (re.compile(r'^(kimi-|k3-)'), 'kimi-for-coding'),
}
keep, default = cfg[mode]
pat = re.compile(r'"model":"([^"]+)"')
roots = [os.path.join(home, 'sessions'), os.path.join(home, 'archived_sessions')]
changed_files, changed_names = 0, set()

for root in roots:
    if not os.path.isdir(root):
        continue
    for dirpath, _, files in os.walk(root):
        for fn in files:
            if not fn.endswith('.jsonl'):
                continue
            p = os.path.join(dirpath, fn)
            try:
                with open(p, 'r', encoding='utf-8') as fh:
                    text = fh.read()
            except (OSError, UnicodeDecodeError):
                continue
            def repl(m):
                name = m.group(1)
                if keep.match(name):
                    return m.group(0)
                changed_names.add(name)
                return f'"model":"{default}"'
            new = pat.sub(repl, text)
            if new != text:
                bak = p + '.bak-model'
                if not os.path.exists(bak):
                    shutil.copy(p, bak)  # 只保留首次备份，避免覆盖原始版本
                with open(p, 'w', encoding='utf-8') as fh:
                    fh.write(new)
                changed_files += 1

if changed_files:
    print(f"已改写 {changed_files} 个会话文件: {sorted(changed_names)} -> {default}")
else:
    print("无需改写（历史会话模型名均已匹配）")
PYEOF

if [ "$MODE" = "openai" ]; then
  echo "清理第三方 reasoning 残留（解决官方续聊校验报错）..."
  # DeepSeek 等第三方直连 /responses 产生的 reasoning 项带 content 数组和
  # 本地 Fernet 加密的 encrypted_content，重放到 OpenAI 官方 API 会报
  # array_above_max_length / invalid_encrypted_content（0.153.4 仍未覆盖）。
  # 切回官方前递归剥离所有 reasoning 项的这两个字段（含 compacted 的
  # replacement_history 嵌套项）。剥离后官方只拿到 summary，可正常续聊；
  # 首次清理前留 .bak-reasoning。
  python3 - "$CODEX_HOME" <<'PYEOF'
import os, sys, json, shutil

home = sys.argv[1]
roots = [os.path.join(home, 'sessions'), os.path.join(home, 'archived_sessions')]

def clean(node, stats):
    if isinstance(node, dict):
        if node.get('type') == 'reasoning':
            for k in ('content', 'encrypted_content'):
                if k in node:
                    del node[k]; stats[k] += 1
        for v in node.values():
            clean(v, stats)
    elif isinstance(node, list):
        for v in node:
            clean(v, stats)

changed = 0; total = {'content': 0, 'encrypted_content': 0}
for root in roots:
    if not os.path.isdir(root):
        continue
    for dirpath, _, files in os.walk(root):
        for fn in files:
            if not fn.endswith('.jsonl'):
                continue
            p = os.path.join(dirpath, fn)
            try:
                head = open(p, encoding='utf-8', errors='ignore').read()
            except OSError:
                continue
            if '"encrypted_content"' not in head and '"content":[' not in head:
                continue
            stats = {'content': 0, 'encrypted_content': 0}
            out = []
            for line in head.splitlines(keepends=True):
                if 'reasoning' not in line:
                    out.append(line); continue
                try:
                    d = json.loads(line)
                    clean(d, stats)
                    out.append(json.dumps(d, ensure_ascii=False) + '\n')
                except Exception:
                    out.append(line)
            if stats['content'] or stats['encrypted_content']:
                bak = p + '.bak-reasoning'
                if not os.path.exists(bak):
                    shutil.copy(p, bak)
                open(p, 'w', encoding='utf-8').writelines(out)
                changed += 1
                total['content'] += stats['content']
                total['encrypted_content'] += stats['encrypted_content']

if changed:
    print(f"已清理 {changed} 个会话文件: content {total['content']} 处, encrypted_content {total['encrypted_content']} 处")
else:
    print("无需清理（无第三方 reasoning 残留）")
PYEOF
fi

echo "Codex CLI 版本: $("$CODEX_CLI" --version 2>/dev/null | head -1 || echo 未知)"

echo "重启 Codex 应用..."
open -a "$CODEX_APP"
echo "完成！当前模式: $MODE"
