# 飞书 Webhook 调用参数示例

本文说明如何调用飞书群机器人 webhook 接口，并给出文本消息、`interactive` 卡片消息的参数示例。

## 1. 请求地址

```text
POST https://open.feishu.cn/open-apis/bot/v2/hook/{your_webhook_token}
```

如果机器人开启了签名校验，请在请求体中额外传入：

- `timestamp`
- `sign`

## 2. 请求头

```http
Content-Type: application/json
```

## 3. 顶层参数说明

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `msg_type` | string | 是 | 消息类型，例如 `text`、`interactive` |
| `content` | object | text 时必填 | 文本消息体 |
| `card` | object | interactive 时必填 | 卡片消息体 |
| `timestamp` | string | 否 | 开启签名校验时必填 |
| `sign` | string | 否 | 开启签名校验时必填 |

## 4. text 消息示例

```json
{
  "msg_type": "text",
  "content": {
    "text": "这是一条飞书 webhook 测试消息"
  }
}
```

## 5. interactive 卡片消息示例

```json
{
  "msg_type": "interactive",
  "card": {
    "config": {
      "wide_screen_mode": true,
      "enable_forward": true
    },
    "header": {
      "template": "green",
      "title": {
        "tag": "plain_text",
        "content": "AI巡检报告 — db_mysql_001"
      }
    },
    "elements": [
      {
        "tag": "div",
        "text": {
          "tag": "lark_md",
          "content": "<at id=all></at>"
        }
      },
      {
        "tag": "div",
        "fields": [
          {
            "is_short": true,
            "text": {
              "tag": "lark_md",
              "content": "**巡检对象**\n数据库"
            }
          },
          {
            "is_short": true,
            "text": {
              "tag": "lark_md",
              "content": "**资源 ID (CI ID)**\n3094"
            }
          },
          {
            "is_short": true,
            "text": {
              "tag": "lark_md",
              "content": "**资源名称**\ndb_mysql_001"
            }
          },
          {
            "is_short": true,
            "text": {
              "tag": "lark_md",
              "content": "**资源类型**\nmysql"
            }
          }
        ]
      },
      {
        "tag": "hr"
      },
      {
        "tag": "div",
        "text": {
          "tag": "lark_md",
          "content": "**整体状态**\n🟢 正常"
        }
      },
      {
        "tag": "hr"
      },
      {
        "tag": "div",
        "text": {
          "tag": "lark_md",
          "content": "**巡检摘要**\n- 整体状态：正常\n- 指标总数：12\n- 指标定义来源：live\n- 指标数据来源：live\n- 巡检时间：2026-04-27 11:22:41"
        }
      },
      {
        "tag": "hr"
      },
      {
        "tag": "div",
        "text": {
          "tag": "lark_md",
          "content": "**指标值明细**"
        }
      },
      {
        "tag": "table",
        "page_size": 10,
        "columns": [
          {
            "name": "metric_name",
            "display_name": "指标名",
            "width": "auto",
            "horizontal_align": "left"
          },
          {
            "name": "metric_code",
            "display_name": "指标编码",
            "width": "auto",
            "horizontal_align": "left"
          },
          {
            "name": "latest_value",
            "display_name": "最近值",
            "width": "auto",
            "horizontal_align": "left"
          }
        ],
        "rows": [
          {
            "metric_name": "连接数",
            "metric_code": "mysql_connections",
            "latest_value": "152"
          },
          {
            "metric_name": "QPS",
            "metric_code": "mysql_qps",
            "latest_value": "350"
          }
        ]
      },
      {
        "tag": "hr"
      },
      {
        "tag": "div",
        "text": {
          "tag": "lark_md",
          "content": "**巡检结论**\n- 各项指标均在正常范围，数据库运行健康。"
        }
      },
      {
        "tag": "note",
        "elements": [
          {
            "tag": "plain_text",
            "content": "巡检时间：2026-04-27 11:22:41"
          },
          {
            "tag": "plain_text",
            "content": "此结果由 AI 自动巡检生成，请及时关注。"
          }
        ]
      }
    ]
  }
}
```

## 6. 开启签名校验时的请求体示例

```json
{
  "msg_type": "interactive",
  "card": {
    "config": {
      "wide_screen_mode": true
    },
    "header": {
      "template": "blue",
      "title": {
        "tag": "plain_text",
        "content": "测试卡片"
      }
    },
    "elements": []
  },
  "timestamp": "1714205400",
  "sign": "base64-sign-value"
}
```

## 7. curl 调用示例

### 7.1 发送 text

```bash
curl -X POST "https://open.feishu.cn/open-apis/bot/v2/hook/xxx" \
  -H "Content-Type: application/json" \
  -d '{
    "msg_type": "text",
    "content": {
      "text": "飞书 webhook 测试"
    }
  }'
```

### 7.2 发送 interactive

```bash
curl -X POST "https://open.feishu.cn/open-apis/bot/v2/hook/xxx" \
  -H "Content-Type: application/json" \
  -d '{
    "msg_type": "interactive",
    "card": {
      "config": {
        "wide_screen_mode": true,
        "enable_forward": true
      },
      "header": {
        "template": "green",
        "title": {
          "tag": "plain_text",
          "content": "AI巡检报告 — db_mysql_001"
        }
      },
      "elements": [
        {
          "tag": "div",
          "text": {
            "tag": "lark_md",
            "content": "**整体状态**\n🟢 正常"
          }
        }
      ]
    }
  }'
```

## 8. 当前巡检通知使用的核心结构

当前巡检飞书通知主要使用以下几类卡片元素：

- `header`
- `div.fields`
- `hr`
- `div.text` + `lark_md`
- `table`
- `note`

适合展示：

- 资源基础信息
- 整体状态
- 指标表格
- 巡检结论
- 底部说明
