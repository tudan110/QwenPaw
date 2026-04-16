---
name: scenario-root-cause-analyst
description: 通用故障场景根因分析 skill，通过 A2A 协作 veops-cmdb 与 mysql-deadlock-inspector。
---

# Scenario Root Cause Analyst

- 面向结构化故障场景分析，不直接承载实时页面操作。
- 默认主入口为 `scripts/analyze_scenario.py`。
- 输出需符合 `references/output-contract.md` 中的结构。
