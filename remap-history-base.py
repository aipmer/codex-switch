#!/usr/bin/env python3
# remap-history-base.py <CODEX_HOME>
#
# 背景：codex-switch.sh 原地改写 rollout 文件（剥离 encrypted_content、改写模型名）
# 会改变文件字节长度。分叉（fork）会话文件头部的 history_base.end_byte_offset
# 记录的是改写前源 rollout 的字节偏移，改写后偏移越界，App 报
# "invalid paginated history lineage: cutoff byte offset is past the source rollout"。
#
# 本脚本把每个分叉文件的 cutoff 重新映射到源文件中「同一行」的当前字节位置：
# 2026-09-18 版假设改写只改行内容、不增删行（ordinal 精确匹配）；
# 2026-10-09 v2 清理规则会整行删除 compaction / web_search_call 项，被删行的
# ordinal 不复存在，导致「找不到包含 ordinal N 的源文件」（10-20 切换实测暴露）。
# 现改为：取源文件中 ordinal >= 目标值的最小 ordinal 行的行首偏移
# （等价于「目标行之后第一个幸存行」的行首，即被删行原本的结束位置）；
# 若源文件已无更大 ordinal，则 cutoff 为源文件末尾（包含全部历史）。
#
# 2026-10-21 补充：App 0.163.x 对压缩（.jsonl.zst）源文件按「压缩后字节数」校验
# lineage 偏移，而 history_base.end_byte_offset 记录的是解压后偏移（如 809270），
# 压缩源只有 ~79KB 时必然报 "cutoff byte offset is past the source rollout"（实测：
# 分叉 01a0a8fd 源被维护任务压缩后，App 打开会话反复重新连接、标签页「无法打开文件」）。
# 因此候选源若为 .zst，先解压回 .jsonl（原 .zst 改名 .zst.bak-lineage 留档，
# 不再参与扫描），解压后偏移在校验语境下即恢复合法。
#
# 可独立运行（修复存量问题），也可由 codex-switch.sh 在每次切换后调用（预防）。
import os, re, sys, json, sqlite3, subprocess, shutil

TID_RE = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
OFFSET_RE = re.compile(r'("end_byte_offset":\s*)\d+')
# 新版 Codex 把旧 rollout 压缩为 .jsonl.zst（2026-10-20 实测）；
# zstd 来自 `brew install zstd`，Apple Silicon 在 /opt/homebrew、Intel 在 /usr/local
ZSTD = shutil.which('zstd') or '/opt/homebrew/bin/zstd'

def open_rollout(path):
    """按行迭代 rollout 文件内容；.jsonl.zst 经 zstd -dc 解压（偏移按解压后字节计）。"""
    if path.endswith('.zst'):
        proc = subprocess.Popen([ZSTD, '-dc', path], stdout=subprocess.PIPE)
        return proc.stdout, proc
    return open(path, 'rb'), None

def ensure_decompressed(src):
    """分叉源文件若是 .zst，解压回同名 .jsonl 并返回其路径；
    解压成功后原 .zst 改名 .zst.bak-lineage 留档（不再被扫描）。
    解压失败或文件缺失时原样返回，由调用方按原路径尽力处理。"""
    if not src.endswith('.zst'):
        return src
    plain = src[:-len('.zst')]
    if os.path.exists(plain):
        return plain
    if not os.path.exists(src):
        return src
    with open(plain, 'wb') as out:
        proc = subprocess.run([ZSTD, '-dc', src], stdout=out)
    if proc.returncode != 0 or os.path.getsize(plain) == 0:
        os.unlink(plain)
        return src
    os.rename(src, src + '.bak-lineage')
    print(f'解压 lineage 源 {os.path.basename(src)} -> {os.path.basename(plain)}')
    return plain

def find_line_offset(path, ordinal):
    """返回 (字节偏移, 是否精确匹配)：ordinal >= 指定值的最小 ordinal 行的行首偏移；
    若不存在更大 ordinal，返回 (文件末尾, False)（分叉包含源文件全部历史）。"""
    pat = re.compile(rb'"ordinal":\s*(\d+),')
    off = 0
    best = None
    best_ord = None
    fh, proc = open_rollout(path)
    try:
        for line in fh:
            if pat.search(line):
                try:
                    o = json.loads(line).get('ordinal')
                except Exception:
                    o = None
                if o is not None and o >= ordinal and (best_ord is None or o < best_ord):
                    best, best_ord = off, o
            off += len(line)
    finally:
        fh.close()
        if proc is not None:
            proc.wait()
    if best is None:
        return off, False
    return best, best_ord == ordinal

def main():
    home = sys.argv[1]
    roots = [os.path.join(home, 'sessions'), os.path.join(home, 'archived_sessions')]
    files = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dp, _, fs in os.walk(root):
            for fn in fs:
                if fn.endswith('.jsonl') or fn.endswith('.jsonl.zst'):
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
        if p.endswith('.zst'):
            continue  # 压缩的只作源文件；分叉均为未压缩的新文件
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
        if not cands:
            failed.append((p, '找不到 thread_id %s 的源文件' % tid))
            continue
        # 优先精确匹配 ordinal 的候选源；都没有则用最近候选的
        # 「下一个幸存行 / 文件末尾」回退值（v2 清理删行后 ordinal 可能已不存在）
        new_off, fallback = None, None
        for src in cands:
            src = ensure_decompressed(src)  # 0.163+ 对压缩源按压缩字节校验，必须解压
            off, exact = find_line_offset(src, n)
            if exact:
                new_off = off
                break
            if fallback is None:
                fallback = off
        if new_off is None:
            new_off = fallback
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
