---
name: scenario-root-cause-analyst
category: root-cause
tags: [fault, scenario, rca, cmdb, mysql, deadlock, scaffold]
triggers: [场景根因分析, CMDB 添加失败, MySQL 死锁, 死锁 RCA, 场景 RCA]
description: 面向结构化故障场景的场景级 RCA 入口。当前阶段提供统一输出脚手架，后续再接入 veops-cmdb 与 mysql-deadlock-inspector 的真实证据采集。
---

# Scenario Root Cause Analyst

- 面向结构化故障场景分析的 scene-level RCA 入口，不直接承载实时页面操作。
- 当前阶段为 **Task 3 脚手架**：先统一 `scene_code`、步骤和日志结构，暂不执行真实 A2A 编排或数据库取证。
- 首个场景模板为 `cmdb_add_failed_mysql_deadlock`。
- 后续将把 MySQL 死锁证据采集接到 `mysql-deadlock-inspector`，并补齐与 `veops-cmdb` 的协作。
- 默认主入口为 `scripts/analyze_scenario.py`，输出需符合 `references/output-contract.md` 中的结构。
