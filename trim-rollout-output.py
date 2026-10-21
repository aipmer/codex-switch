#!/usr/bin/env python3
# trim-rollout-output.py <rollout.jsonl> [选项]
#
# 用途：巨型会话续聊时报 "Your input exceeds the context window of this model"，
# 因为 App 把全量历史回放给模型。本工具做「智能修剪」——只裁掉历史中的大体积
# 工具输出，对话文字（user/assistant 消息）原样保留，让模型仍记得「做过什么、
# 结论是什么」，只是看不到当年命令的原始回显。
#
# 修剪对象（仅当超过阈值、且不在最近保护区内）：
#   1. item_completed 的大体积结果：图像生成 base64（item.result；图片本体在
#      savedPath 指向的本地文件里，不丢）、McpToolCall 输出（result.content[].text）、
#      CommandExecution 输出（aggregated_output）
#   2. custom_tool_call_output / function_call_output 的超长输出文本
#   3. compacted 窗口记录 replacement_history 里的超长粘贴文本（>--max-msg-chars，
#      正常对话消息远小于此值，不受影响）
#
# 保护机制：
#   - 文件尾部 --keep-recent-mb 的「最近工作区」完全不动
#   - 原文件备份为 .bak-trim-<时间戳>，随时可恢复
#   - 修剪后自动失效相关线程（含分叉）的 GUI 投影缓存
#
# 修剪改变了字节偏移，请接着运行 remap-history-base.py 修复分叉 lineage：
#   python3 remap-history-base.py ~/.codex
#
# 示例：
#   python3 trim-rollout-output.py ~/.codex/sessions/2026/08/19/rollout-....jsonl
#   python3 trim-rollout-output.py <file> --keep-recent-mb 2 --max-field-chars 4000
import os, re, sys, json, glob, sqlite3, shutil, argparse, datetime

TID_RE = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')

# 1x1 透明 PNG，用于替换历史里的 base64 粘贴图（保持 input_image 结构合法，
# 不触发回放校验；图片本身多半是剪贴板截图，对话文字已说明其内容）
TINY_PNG = ('data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ'
            'AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==')

def trim_images(content, max_field):
    """content 列表里 input_image 的超长 data: URL 换成 1x1 占位图，返回节省字符数。"""
    saved = 0
    if not isinstance(content, list):
        return 0
    for c in content:
        if not isinstance(c, dict) or c.get('type') != 'input_image':
            continue
        u = c.get('image_url')
        if isinstance(u, str) and len(u) > max_field and u.startswith('data:'):
            c['image_url'] = TINY_PNG
            saved += len(u) - len(TINY_PNG)
        elif isinstance(u, dict) and isinstance(u.get('url'), str) and len(u['url']) > max_field and u['url'].startswith('data:'):
            old = u['url']
            u['url'] = TINY_PNG
            saved += len(old) - len(TINY_PNG)
    return saved

def trim_text(s, keep_head, note):
    """超长文本：保留开头 keep_head 字符作上下文提示，其余替换为占位说明。"""
    return s[:keep_head] + f'\n…[{note}，原 {len(s)} 字符，由 trim-rollout-output.py 修剪]'

def trim_history_items(items, max_field, max_msg, head):
    """修剪一份历史条目列表（replacement_history / guardian_history 共用）：
    换 base64 图片、裁超长粘贴文本、裁其中的工具输出。返回节省字符数。"""
    saved = 0
    if not isinstance(items, list):
        return 0
    for it in items:
        if not isinstance(it, dict):
            continue
        saved += trim_images(it.get('content'), max_field)
        content = it.get('content')
        if isinstance(content, list):
            for c in content:
                if isinstance(c, dict) and isinstance(c.get('text'), str) and len(c['text']) > max_msg:
                    old = c['text']
                    c['text'] = trim_text(old, head, '早期粘贴的大段资料已省略')
                    saved += len(old) - len(c['text'])
        out = it.get('output')
        if isinstance(out, str) and len(out) > max_field:
            it['output'] = trim_text(out, head, '历史工具输出已省略')
            saved += len(out) - len(it['output'])
    return saved

def process_obj(obj, max_field, max_msg, head):
    """就地修剪单个解析后的 JSON 对象，返回节省的字符数。"""
    saved = 0
    p = obj.get('payload')
    if not isinstance(p, dict):
        return 0
    pt = p.get('type')

    # 1) item_completed：图像生成 base64（result 为 str）、McpToolCall
    #    （result 为 dict，content[].text 存输出）、CommandExecution（aggregated_output）
    if pt == 'item_completed':
        item = p.get('item')
        if isinstance(item, dict):
            r = item.get('result')
            if isinstance(r, str) and len(r) > max_field:
                note = '历史工具结果已省略'
                sp = item.get('savedPath')
                if sp:
                    note = f'历史工具结果已省略（产物已保存于 {sp}）'
                item['result'] = trim_text(r, head, note)
                saved += len(r) - len(item['result'])
            elif isinstance(r, dict):
                content = r.get('content')
                if isinstance(content, list):
                    for c in content:
                        if isinstance(c, dict) and isinstance(c.get('text'), str) and len(c['text']) > max_field:
                            old = c['text']
                            c['text'] = trim_text(old, head, '历史工具输出已省略')
                            saved += len(old) - len(c['text'])
            ao = item.get('aggregated_output')
            if isinstance(ao, str) and len(ao) > max_field:
                item['aggregated_output'] = trim_text(ao, head, '历史命令输出已省略')
                saved += len(ao) - len(item['aggregated_output'])

    # 2) 工具输出：custom_tool_call_output / function_call_output
    if pt in ('custom_tool_call_output', 'function_call_output'):
        out = p.get('output')
        if isinstance(out, str) and len(out) > max_field:
            p['output'] = trim_text(out, head, '历史工具输出已省略')
            saved += len(out) - len(p['output'])
        elif isinstance(out, list):
            for part in out:
                if isinstance(part, dict) and isinstance(part.get('text'), str) and len(part['text']) > max_field:
                    old = part['text']
                    part['text'] = trim_text(old, head, '历史工具输出已省略')
                    saved += len(old) - len(part['text'])

    # 3) compacted 窗口记录：replacement_history（回放正文）与 guardian_history
    #    （审查副本，体积往往更大）里的超长粘贴文本、base64 图片、工具输出
    if obj.get('type') == 'compacted':
        saved += trim_history_items(p.get('replacement_history'), max_field, max_msg, head)
        saved += trim_history_items(p.get('guardian_history'), max_field, max_msg, head)

    # 4) 普通消息：只换 base64 粘贴图，文字一律不动
    if pt == 'message':
        saved += trim_images(p.get('content'), max_field)
    return saved

def invalidate_projections(home, root_tid):
    """失效被修剪线程及其分叉（文件名含根 tid）的 GUI 投影缓存。"""
    tids = set()
    for root in ('sessions', 'archived_sessions'):
        base = os.path.join(home, root)
        if not os.path.isdir(base):
            continue
        for dp, _, fs in os.walk(base):
            for fn in fs:
                if root_tid in fn:
                    for m in TID_RE.finditer(fn):
                        tids.add(m.group(0))
    db = os.path.join(home, 'thread_history_1.sqlite')
    if tids and os.path.exists(db):
        tids = sorted(tids)
        con = sqlite3.connect(db)
        for t in ('thread_items', 'thread_turns', 'thread_history_projection_state', 'thread_realtime_items'):
            con.execute(f"delete from {t} where thread_id in ({','.join('?' * len(tids))})", tids)
        con.commit(); con.close()
    return len(tids)

def main():
    ap = argparse.ArgumentParser(description='智能修剪 rollout：裁旧工具输出，保对话文字')
    ap.add_argument('file', help='rollout .jsonl 文件路径（.zst 请先解压）')
    ap.add_argument('--keep-recent-mb', type=float, default=2.0,
                    help='文件尾部完全不动的最近保护区大小，MB（默认 2）')
    ap.add_argument('--max-field-chars', type=int, default=4000,
                    help='工具输出超过此字符数才修剪（默认 4000）')
    ap.add_argument('--max-msg-chars', type=int, default=20000,
                    help='compacted 窗口内粘贴文本超过此字符数才修剪（默认 20000）')
    ap.add_argument('--keep-head', type=int, default=500,
                    help='修剪时保留开头多少字符作提示（默认 500）')
    args = ap.parse_args()

    path = os.path.abspath(os.path.expanduser(args.file))
    if path.endswith('.zst'):
        sys.exit('错误：不接受 .zst，请先解压（remap-history-base.py 会对分叉源自动解压）')
    if not os.path.exists(path):
        sys.exit(f'错误：文件不存在 {path}')

    with open(path, 'rb') as f:
        lines = f.readlines()
    total = sum(len(l) for l in lines)

    # 计算最近保护区：从尾部累积 keep_recent_mb 的字节数
    keep_bytes = int(args.keep_recent_mb * 1e6)
    acc = 0
    protect_from = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        if acc >= keep_bytes:
            break
        acc += len(lines[i])
        protect_from = i

    new_lines = []
    trimmed = 0
    saved_chars = 0
    for i, line in enumerate(lines):
        # compacted 窗口记录不受尾部保护：它是「已压缩的历史记忆」，回放时整体发送，
        # 恰恰是最需要修剪的部分（窗口里的粘贴资料动辄几百 KB，对话文字则保留）
        if i >= protect_from and b'"type":"compacted"' not in line and b'"type": "compacted"' not in line:
            new_lines.append(line)
            continue
        try:
            obj = json.loads(line)
        except Exception:
            new_lines.append(line)
            continue
        s = process_obj(obj, args.max_field_chars, args.max_msg_chars, args.keep_head)
        if s > 0:
            trimmed += 1
            saved_chars += s
            new_lines.append((json.dumps(obj, ensure_ascii=False) + '\n').encode('utf-8'))
        else:
            new_lines.append(line)

    if trimmed == 0:
        print('没有需要修剪的内容（可能全部在最近保护区内，可调小 --keep-recent-mb）')
        return

    ts = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    bak = f'{path}.bak-trim-{ts}'
    shutil.copy2(path, bak)
    with open(path, 'wb') as f:
        f.writelines(new_lines)
    new_total = sum(len(l) for l in new_lines)

    m = TID_RE.search(os.path.basename(path))
    home = os.path.expanduser('~/.codex')
    n_proj = invalidate_projections(home, m.group(0)) if m else 0

    print(f'修剪 {trimmed} 行：{total/1e6:.1f}MB -> {new_total/1e6:.1f}MB'
          f'（省去 {saved_chars/1e6:.1f}M 字符，保护区为最后 {(len(lines)-protect_from)} 行）')
    print(f'原文件备份：{bak}')
    print(f'已失效 {n_proj} 个相关线程的投影缓存')
    print('下一步：python3 %s %s' % (os.path.join(os.path.dirname(os.path.abspath(__file__)), 'remap-history-base.py'), home))

if __name__ == '__main__':
    main()
