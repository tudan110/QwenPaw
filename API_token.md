# Token 统计 API 文档

本文档描述用于查询 LLM Token 使用统计的接口。

## 概述

- **后端基础路径**: `http://127.0.0.1:8088/api`
- **接口路径**: `/token-usage`
- **完整地址**: `GET /api/token-usage`

## 认证说明

该接口位于 `/api` 路径下，遵循项目统一认证规则：

- 未启用认证时，可直接访问
- 启用认证后，外部请求在 header 中需携带 `Authorization: Bearer <token>`

## 接口说明

### 获取 Token 统计汇总

按日期区间查询 Token 使用情况，并返回总量、按模型聚合、按提供商聚合、按日期聚合的数据。

**请求**

```http
GET /api/token-usage
```

### 查询参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `start_date` | `string` | 否 | 开始日期，格式 `YYYY-MM-DD`，包含当天。默认取 `end_date - 30 天` |
| `end_date` | `string` | 否 | 结束日期，格式 `YYYY-MM-DD`，包含当天。默认取今天 |
| `model` | `string` | 否 | 按模型名精确过滤 |
| `provider` | `string` | 否 | 按提供商 ID 精确过滤 |

### 日期处理规则

- `start_date` / `end_date` 为空时，接口会自动补默认值
- 日期格式非法时，不会报 400，而是回退到默认值
- 若 `start_date > end_date`，接口会自动交换两者

## 响应结构

### TokenUsageStats

```json
{
  "prompt_tokens": 1200,
  "completion_tokens": 340,
  "call_count": 8
}
```

### TokenUsageByModel

```json
{
  "provider_id": "openai",
  "model": "gpt-4o",
  "prompt_tokens": 1200,
  "completion_tokens": 340,
  "call_count": 8
}
```

### TokenUsageSummary

```json
{
  "total_prompt_tokens": 5800,
  "total_completion_tokens": 2100,
  "total_calls": 36,
  "by_model": {
    "openai:gpt-4o": {
      "provider_id": "openai",
      "model": "gpt-4o",
      "prompt_tokens": 2600,
      "completion_tokens": 900,
      "call_count": 12
    },
    "dashscope:qwen-max": {
      "provider_id": "dashscope",
      "model": "qwen-max",
      "prompt_tokens": 3200,
      "completion_tokens": 1200,
      "call_count": 24
    }
  },
  "by_provider": {
    "openai": {
      "prompt_tokens": 2600,
      "completion_tokens": 900,
      "call_count": 12
    },
    "dashscope": {
      "prompt_tokens": 3200,
      "completion_tokens": 1200,
      "call_count": 24
    }
  },
  "by_date": {
    "2026-03-12": {
      "prompt_tokens": 600,
      "completion_tokens": 200,
      "call_count": 4
    },
    "2026-03-13": {
      "prompt_tokens": 800,
      "completion_tokens": 260,
      "call_count": 5
    }
  }
}
```

### 字段说明

| 字段 | 说明 |
|------|------|
| `total_prompt_tokens` | 统计区间内输入 Token 总数 |
| `total_completion_tokens` | 统计区间内输出 Token 总数 |
| `total_calls` | 统计区间内模型调用总次数 |
| `by_model` | 按模型聚合的统计结果，key 通常为 `provider:model`；若 `provider_id` 为空，则 key 为模型名 |
| `by_provider` | 按提供商 ID 聚合的统计结果 |
| `by_date` | 按日期聚合的统计结果，key 为 `YYYY-MM-DD`，按升序返回 |

## 示例

### 1. 查询默认近 30 天统计

```bash
curl "http://127.0.0.1:8088/api/token-usage"
```

### 2. 查询指定日期区间

```bash
curl "http://127.0.0.1:8088/api/token-usage?start_date=2026-03-12&end_date=2026-04-09"
```

### 3. 查询指定提供商

```bash
curl "http://127.0.0.1:8088/api/token-usage?start_date=2026-03-12&end_date=2026-04-09&provider=openai"
```

### 4. 查询指定模型

```bash
curl "http://127.0.0.1:8088/api/token-usage?start_date=2026-03-12&end_date=2026-04-09&model=gpt-4o"
```

### 5. 响应报文示例

```bash
{
    "total_prompt_tokens": 558990,
    "total_completion_tokens": 8901,
    "total_calls": 49,
    "by_model": {
        "ctyun:GLM-5": {
            "prompt_tokens": 551209,
            "completion_tokens": 8892,
            "call_count": 48,
            "provider_id": "ctyun",
            "model": "GLM-5"
        },
        "ctyun:Qwen3.5-397B-A17B": {
            "prompt_tokens": 7781,
            "completion_tokens": 9,
            "call_count": 1,
            "provider_id": "ctyun",
            "model": "Qwen3.5-397B-A17B"
        }
    },
    "by_provider": {
        "ctyun": {
            "prompt_tokens": 558990,
            "completion_tokens": 8901,
            "call_count": 49
        }
    },
    "by_date": {
        "2026-04-06": {
            "prompt_tokens": 29303,
            "completion_tokens": 208,
            "call_count": 3
        },
        "2026-04-07": {
            "prompt_tokens": 305675,
            "completion_tokens": 7643,
            "call_count": 24
        },
        "2026-04-08": {
            "prompt_tokens": 26156,
            "completion_tokens": 211,
            "call_count": 3
        },
        "2026-04-09": {
            "prompt_tokens": 197856,
            "completion_tokens": 839,
            "call_count": 19
        }
    }
}
```