---
name: mysql-deadlock-inspector
category: evidence
tags: [fault, mysql, deadlock, lock-wait, transaction, scaffold]
triggers: [MySQL 死锁排查, 锁等待排查, 阻塞事务分析, 死锁证据]
description: 面向 MySQL 死锁、锁等待和阻塞事务证据采集的只读 skill。当前阶段保留 JSON 脚手架，供后续 RCA 链路接线。
---

# MySQL Deadlock Inspector

- 优先使用 `scripts/query_mysql_deadlock.py`。
- 当前阶段仅提供结构化脚手架输出，不接入真实 MySQL。
- 后续接线后仍只做只读排查，不执行写操作或终止会话。
- 默认输出结构化 JSON，字段以 `deadlocks`、`lockWaits`、`transactions` 为主。
