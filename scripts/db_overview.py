"""数据库自检小工具，开发时用来看表建好没有、数据落库了没有。

用法（在项目根目录执行）：
    venv/Scripts/python.exe scripts/db_overview.py
"""

import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.core.config import DB_PATH   # noqa: E402


def main():
    if not os.path.exists(DB_PATH):
        print("数据库还没生成：%s" % DB_PATH)
        print("先启动一次后端，会自动建表。")
        return

    conn = sqlite3.connect(DB_PATH)
    tables = [r[0] for r in conn.execute(
        "select name from sqlite_master where type='table' order by name")]

    print("数据库文件：", DB_PATH)
    print("数据表 %d 张：" % len(tables))
    for name in tables:
        count = list(conn.execute("select count(*) from %s" % name))[0][0]
        print("  - %-16s %d 行" % (name, count))

    print("\ndocuments 表结构：")
    for row in conn.execute("PRAGMA table_info(documents)"):
        print("  %-14s %s" % (row[1], row[2]))

    print("\n最近几条问答（拒答标记记在助手的回复上）：")
    rows = list(conn.execute(
        "select u.id, u.session_id, a.refused, substr(u.content, 1, 20), a.content "
        "from messages u "
        "join messages a on a.session_id = u.session_id and a.id = u.id + 1 "
        "where u.role = 'user' and a.role = 'assistant' "
        "order by u.id desc limit 5"))
    if not rows:
        print("  （还没有问答记录）")
    for r in rows:
        print("  消息 %-3s 会话 %-3s 拒答=%s  %-22s -> %s"
              % (r[0], r[1], r[2], r[3], r[4][:20].replace("\n", " ")))

    conn.close()


if __name__ == "__main__":
    main()
