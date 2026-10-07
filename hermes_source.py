"""读取 WSL 里 Hermes 的 state.db(只读),按天、按模型汇总 token。

Windows 不能直接打开 WSL 的 SQLite 文件(网络路径不支持它的锁),所以让 WSL 里的 python3 去查,
只取 sessions 表里的汇总列,不碰对话内容。
"""
import json, subprocess

SCRIPT = r'''
import sqlite3, json, os
from datetime import datetime
db = sqlite3.connect("file:" + os.path.expanduser("~/.hermes/state.db") + "?mode=ro", uri=True, timeout=10)
cols = "input_tokens, output_tokens, cache_read_tokens, cache_write_tokens"
# 优先用按模型拆分的 session_model_usage(一个会话中途换模型也能分开),没有拆分记录的旧会话再用 sessions
rows = db.execute("select first_seen, model, " + cols + " from session_model_usage where model != ''").fetchall()
rows += db.execute("select started_at, model, " + cols + " from sessions where model is not null and model != '' "
                   "and id not in (select session_id from session_model_usage)").fetchall()
print(json.dumps([[datetime.fromtimestamp(t).strftime("%Y-%m-%d"), m, i or 0, o or 0, cr or 0, cw or 0]
                  for t, m, i, o, cr, cw in rows if t and (i or 0) + (o or 0) + (cr or 0) + (cw or 0)]))
'''


def read_sessions(distro="Ubuntu"):
    """返回 [(日期, 模型, 输入, 输出, 缓存读, 缓存写)];WSL 不可用时返回空列表。"""
    try:
        r = subprocess.run(["wsl.exe", "-d", distro, "--", "python3", "-c", SCRIPT],
                           capture_output=True, timeout=120, creationflags=0x08000000)
        return [tuple(x) for x in json.loads(r.stdout.decode("utf-8"))]
    except Exception:
        return []


if __name__ == "__main__":
    rows = read_sessions()
    print(len(rows), sum(sum(r[2:]) for r in rows))
