#!/usr/bin/env python3
# remap-history-base.py <CODEX_HOME>
#
# 背景：codex-switch.sh 原地改写 rollout 文件（剥离 encrypted_content、改写模型名）
# 会改变文件字节长度。分叉（fork）会话文件头部的 history_base.end_byte_offset
# 记录的是改写前源 rollout 的字节偏移，改写后偏移越界，App 报
# "invalid paginated history lineage: cutoff byte offset is past the source rollout"。
#
# 本脚本把每个分叉文件的 cutoff 重新映射到源文件中「同一行」的当前字节位置：
# 改写只改行内容、不增删行，因此 ordinal == end_ordinal_exclusive 的那一行
# 在源文件里的行首偏移就是新的 cutoff（2026-09-18 用 .bak-model 原始备份验证确认）。
#
# 可独立运行（修复存量问题），也可由 codex-switch.sh 在每次切换后调用（预防）。
import os, re, sys, json, sqlite3

TID_RE = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
OFFSET_RE = re.compile(r'("end_byte_offset":\s*)\d+')

def find_line_offset(path, ordinal):
    """返回顶层 ordinal == 指定值的行在文件中的行首字节偏移；找不到返回 None。"""
    pat = re.compile(rb'"ordinal":\s*%d,' % ordinal)
    off = 0
    with open(path, 'rb') as fh:
        for line in fh:
            if pat.search(line):
                try:
                    if json.loads(line).get('ordinal') == ordinal:
                        return off
                except Exception:
                    pass
            off += len(line)
    return None

def main():
    home = sys.argv[1]
    roots = [os.path.join(home, 'sessions'), os.path.join(home, 'archived_sessions')]
    files = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dp, _, fs in os.walk(root):
            for fn in fs:
                if fn.endswith('.jsonl'):
                    files.append(os.path.join(dp, fn))

    by_tid = {}
    for p in files:
        # 分叉文件名含两个 UUID：根线程 id 与父分叉 id；history_base.thread_id
        # 指向直接来源（父分叉或根线程），因此每个 UUID 都要登记
        for m in TID_RE.finditer(os.path.basename(p)):
            by_tid.setdefault(m.group(0), []).append(p)

    fixed, skipped, failed = 0, 0, []
    fixed_tids = set()
    for p in files:
        try:
            with open(p, 'rb') as fh:
                first = fh.readline()
            hb = json.loads(first).get('payload', {}).get('history_base')
        except Exception:
            continue
        if not hb or 'end_byte_offset' not in hb or 'end_ordinal_exclusive' not in hb:
            continue
        tid, n, cutoff = hb['thread_id'], hb['end_ordinal_exclusive'], hb['end_byte_offset']
        # 候选源文件：同线程、非自身、文件名时间戳早于分叉文件（字典序即时间序）
        cands = sorted((q for q in by_tid.get(tid, [])
                        if q != p and os.path.basename(q) < os.path.basename(p)),
                       key=os.path.basename, reverse=True)
        new_off = None
        for src in cands:
            # cutoff 未越界且偏移正确时无需处理：先快速判断
            new_off = find_line_offset(src, n)
            if new_off is not None:
                break
        if new_off is None:
            failed.append((p, '找不到包含 ordinal %d 的源文件' % n))
            continue
        if new_off == cutoff:
            skipped += 1
            continue
        first_line = first.decode('utf-8')
        if not OFFSET_RE.search(first_line):
            failed.append((p, '首行未找到 end_byte_offset 字段'))
            continue
        new_first, cnt = OFFSET_RE.subn(r'\g<1>%d' % new_off, first_line, count=1)
        assert cnt == 1
        with open(p, 'r', encoding='utf-8') as fh:
            lines = fh.readlines()
        lines[0] = new_first
        with open(p, 'w', encoding='utf-8') as fh:
            fh.writelines(lines)
        fixed += 1
        # 投影缓存按根线程 id（对话 id）索引，取文件名第一个 UUID
        fixed_tids.add(TID_RE.search(os.path.basename(p)).group(0))
        print(f'重映射 {os.path.basename(p)}: {cutoff} -> {new_off}')

    # 失效被修改线程的 GUI 投影缓存，重启后 App 自动重建
    if fixed_tids:
        db = os.path.join(home, 'thread_history_1.sqlite')
        if os.path.exists(db):
            tids = sorted(fixed_tids)
            con = sqlite3.connect(db)
            for t in ('thread_items', 'thread_turns', 'thread_history_projection_state', 'thread_realtime_items'):
                con.execute(f"delete from {t} where thread_id in ({','.join('?' * len(tids))})", tids)
            con.commit(); con.close()
    print(f'完成：重映射 {fixed} 个分叉会话，{skipped} 个无需处理')
    for p, why in failed:
        print(f'⚠️ 未能修复 {p}: {why}')

if __name__ == '__main__':
    main()
