# BuiltinKB 目录说明

这里存放当前轻量部署服务 `server.py` 使用的内置知识包。

约定：

- 每个知识包一个子目录
- 子目录内必须包含 `manifest.json`
- `server.py` 启动时自动扫描 `builtin_kb/**/manifest.json`
- 仅导入 `enabled=true` 的知识包
- `POST /api/v1/admin/builtin-knowledge/reload` 可手动重载

最小 manifest 示例：

```json
{
  "pack_id": "ops_baseline",
  "version": "2026.04.22",
  "title": "平台基础运维知识包",
  "description": "用于冷启动和通用问题兜底的内置知识。",
  "enabled": true,
  "scope_label": "平台内置知识",
  "files": [
    {
      "path": "slow_sql_baseline.md",
      "title": "慢 SQL 通用排查基线",
      "tags": ["slow_sql", "mysql", "sop"]
    }
  ]
}
```
