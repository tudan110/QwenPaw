---
name: mysql-deadlock-inspector
description: 只读查询 MySQL 死锁、锁等待、阻塞事务与相关 SQL 证据。
---

# MySQL Deadlock Inspector

- 优先使用 `scripts/query_mysql_deadlock.py`。
- 只做只读排查，不执行写操作或终止会话。
- 默认输出结构化 JSON，字段以 `deadlocks`、`lockWaits`、`transactions` 为主。
