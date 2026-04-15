# CoPaw API 接口文档

## 基础配置

- **默认地址**: `http://127.0.0.1:8088`
- **多智能体模式**: 需在请求头添加 `X-Agent-Id: {agentId}` 或使用路径 `/api/agents/{agentId}/...`

## 核心概念

| 字段 | 说明 |
|------|------|
| `chat.id` | 系统自动生成的 UUID，存储层唯一标识一条聊天记录，用于获取历史、更新、删除等操作 |
| `session_id` | 会话逻辑标识符，由用户定义，用于标识对话上下文、保持消息连续性 |
| `user_id` | 用户标识符，区分不同用户 |
| `channel` | 消息来源渠道/平台，如 `console`（Web控制台）、`feishu`（飞书）、`dingtalk`（钉钉）等 |
| `status` | 会话状态：`idle`（空闲）或 `running`（运行中） |

**session_id 与 chat.id 的关系**：
- `session_id` 是用户定义的逻辑标识
- `chat.id` 是系统生成的存储标识
- 一个 `session_id` + `user_id` + `channel` 组合对应一个 chat
- 用户主动创建多个 chat 时，每个有独立的 `chat.id`

## 认证说明

认证**默认关闭**，需设置环境变量 `COPAW_AUTH_ENABLED=true` 才会启用。

启用认证后：
- 本地请求（127.0.0.1 / ::1）无需认证
- 外部请求需在 Header 添加 `Authorization: Bearer {token}`

---

## 核心 API

### 1. 获取智能体列表

**GET** `/api/agents`

**响应**:
```json
{
  "agents": [
    {
      "id": "default",
      "name": "Default Agent",
      "description": "智能体描述",
      "workspace_dir": "/path/to/workspace"
    }
  ]
}
```

**curl 示例**:
```bash
curl http://127.0.0.1:8088/api/agents
```

---

### 2. 获取聊天列表

**GET** `/api/chats`

查询参数：
- `user_id` (可选): 用户 ID
- `channel` (可选): 渠道名称

**响应**:
```json
[
  {
    "id": "chat-uuid",
    "name": "对话名称",
    "session_id": "session-001",
    "user_id": "default",
    "channel": "console",
    "status": "idle|running",
    "meta": {}
  }
]
```

**curl 示例**:
```bash
curl http://127.0.0.1:8088/api/chats \
  -H 'X-Agent-Id: xCZ6nF'
curl "http://127.0.0.1:8088/api/chats?user_id=default" \
  -H 'X-Agent-Id: xCZ6nF'
```

---

### 3. 获取聊天历史

**GET** `/api/chats/{chatId}`

**响应**:
```json
{
  "messages": [
    {
      "role": "user",
      "content": "你好"
    },
    {
      "role": "assistant",
      "content": "你好！有什么可以帮助你的？"
    }
  ],
  "status": "idle|running"
}
```

**curl 示例**:
```bash
curl http://127.0.0.1:8088/api/chats/{chatId} \
  -H 'X-Agent-Id: xCZ6nF'
```

---

### 4. 创建新聊天

**POST** `/api/chats`

请求体：
```json
{
  "name": "新对话",
  "session_id": "new-session",
  "user_id": "default",
  "channel": "console"
}
```

**响应**:
```json
{
  "id": "3283e974-49b0-4874-a92c-4776054e7b49",
  "name": "新对话",
  "session_id": "new-session",
  "user_id": "default",
  "channel": "console",
  "created_at": "2026-03-25T08:46:38.888505Z",
  "updated_at": "2026-03-25T08:46:38.888506Z",
  "meta": {},
  "status": "idle"
}
```

**curl 示例**:
```bash
curl -X POST http://127.0.0.1:8088/api/chats \
  -H "Content-Type: application/json" \
  -H 'X-Agent-Id: xCZ6nF' \
  -d '{"name": "新对话", "session_id": "new-session", "user_id": "default", "channel": "console"}'
```

---

### 5. 发送消息（流式响应）

**POST** `/api/console/chat`

请求体：
```json
{
  "session_id": "session-001",
  "user_id": "default",
  "channel": "console",
  "stream": true,
  "input": [
    {
      "role": "user",
      "type": "message",
      "content": [
        { "type": "text",
          "text": "你好",
          "status": "created"
        }
      ]
    }
  ]
}
```

**响应**: SSE 流（`text/event-stream`）

**重连**: 添加 `"reconnect": true`

**curl 示例**:
```bash
curl 'http://127.0.0.1:8088/api/console/chat' \
  -H 'Content-Type: application/json' \
  -H 'X-Agent-Id: xCZ6nF' \
  --data-raw '{"input":[{"role":"user","type":"message","content":[{"type":"text","text":"现在几点了","status":"created"}]}],"session_id":"1774252559167","user_id":"default","channel":"console","stream":true}'
```

---

### 6. 停止聊天

**POST** `/api/console/chat/stop?chat_id={chatId}`

**curl 示例**:
```bash
curl -X POST "http://127.0.0.1:8088/api/console/chat/stop?chat_id={chatId}" \
  -H 'X-Agent-Id: xCZ6nF'
```

---

### 7. 更新聊天

**PUT** `/api/chats/{chatId}`

---

### 8. 删除聊天

**DELETE** `/api/chats/{chatId}`

---

### 9. 批量删除聊天

**POST** `/api/chats/batch-delete`

请求体：
```json
["chat-id-1", "chat-id-2"]
```

---

### 10. 文件上传

**POST** `/api/console/upload`

Content-Type: `multipart/form-data`

**响应**:
```json
{
  "url": "xxx_filename.pdf",
  "file_name": "filename.pdf",
  "size": 12345
}
```

**curl 示例**:
```bash
curl -X POST http://127.0.0.1:8088/api/console/upload \
  -H 'X-Agent-Id: xCZ6nF' \
  -F "file=@/path/to/file.pdf"
```

---

### 11. 获取上传文件

**GET** `/api/console/files/{agent_id}/{filename}`

---

### 12. 获取推送消息

**GET** `/api/console/push-messages?session_id={sessionId}`

---

## SSE 事件格式

聊天响应为 SSE 流，事件格式：

```
data: {"type": "text", "text": "你好"}
data: {"type": "tool_use", "name": "read_file", "arguments": {...}}
data: {"type": "tool_result", "content": [...]}
data: {"type": "round_end"}
```

事件类型：
- `text`: 文本内容
- `tool_use`: 工具调用
- `tool_result`: 工具返回结果
- `round_end`: 本轮对话结束
- `error`: 错误信息

---

## 前端示例代码

### TypeScript

```typescript
// 发送消息（流式）
async function sendMessage(content: string, sessionId: string) {
  const response = await fetch('http://127.0.0.1:8088/api/console/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: sessionId,
      user_id: 'default',
      channel: 'console',
      input: [{ role: 'user', content: [{ type: 'text', text: content }] }]
    })
  });

  // SSE 流处理
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    const chunk = decoder.decode(value);
    // 解析 SSE: "data: {...}\n\n"
    const lines = chunk.split('\n');
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const data = JSON.parse(line.slice(6));
        console.log('Event:', data);

        if (data.type === 'text') {
          // 追加文本到 UI
        } else if (data.type === 'round_end') {
          // 对话结束
        }
      }
    }
  }
}

// 获取聊天列表
async function getChats() {
  const response = await fetch('http://127.0.0.1:8088/api/chats');
  return response.json();
}

// 获取聊天历史
async function getChatHistory(chatId: string) {
  const response = await fetch(`http://127.0.0.1:8088/api/chats/${chatId}`);
  return response.json();
}

// 上传文件
async function uploadFile(file: File) {
  const formData = new FormData();
  formData.append('file', file);

  const response = await fetch('http://127.0.0.1:8088/api/console/upload', {
    method: 'POST',
    body: formData
  });

  return response.json();
}
```

---

## 前端开发指南

### 完整交互流程

```
1. 获取智能体列表 → 展示可选智能体
2. 获取聊天列表 → 展示历史对话
3. 选择/创建聊天 → 进入对话界面
4. 发送消息（SSE 流）→ 实时展示回复
5. 停止聊天（可选）→ 中断正在进行的对话
```

### 推荐实现方案

#### 步骤 1：获取智能体列表

```bash
GET /api/agents
```

展示智能体列表供用户选择，记录选中的 `agent.id`，后续请求都带上 `X-Agent-Id: {agentId}`。

#### 步骤 2：获取聊天列表

```bash
GET /api/chats
Header: X-Agent-Id: {agentId}
```

展示历史对话列表，每个聊天显示 `name`、`status` 等信息。

#### 步骤 3：创建新聊天（推荐做法）

```bash
POST /api/chats
Header: X-Agent-Id: {agentId}
Body: {
  "name": "新对话",
  "session_id": "时间戳或自定义ID",
  "user_id": "default",
  "channel": "console"
}
```

返回的 `id`（chat.id）用于后续获取历史；`session_id` 用于发送消息。

> **简化做法**：也可以不预先创建，直接发送消息时后端会自动创建聊天。

#### 步骤 4：获取聊天历史

```bash
GET /api/chats/{chatId}
Header: X-Agent-Id: {agentId}
```

展示该聊天的历史消息。

#### 步骤 5：发送消息（SSE 流式）

```bash
POST /api/console/chat
Header: X-Agent-Id: {agentId}
Body: {
  "session_id": "创建时使用的session_id",
  "user_id": "default",
  "channel": "console",
  "stream": true,
  "input": [{
    "role": "user",
    "type": "message",
    "content": [{"type": "text", "text": "你好", "status": "created"}]
  }]
}
```

响应为 SSE 流，逐条解析事件更新 UI。

#### 步骤 6：停止聊天（可选）

```bash
POST /api/console/chat/stop?chat_id={chatId}
Header: X-Agent-Id: {agentId}
```

中断正在进行的对话。

### 关键字段对照

| 场景 | 使用字段 |
|------|----------|
| 获取历史、删除聊天 | `chat.id`（UUID） |
| 发送消息、重连对话 | `session_id`（用户定义） |
| 指定智能体 | Header `X-Agent-Id` |

### 前端 session_id 生成建议

推荐使用时间戳作为 `session_id`：

```typescript
const sessionId = Date.now().toString(); // 如 "1742889998887"
```

---

## 多智能体模式

使用多智能体时，有两种方式指定 Agent：

### 方式 1: Header

```bash
curl http://127.0.0.1:8088/api/chats \
  -H 'X-Agent-Id: xCZ6nF'
```

### 方式 2: URL 路径

```bash
curl http://127.0.0.1:8088/api/agents/default/chats
```

---

## OpenAPI 文档

启动时设置环境变量可访问 Swagger 文档：

```bash
COPAW_OPENAPI_DOCS=true copaw app
```

然后访问：
- Swagger UI: `http://127.0.0.1:8088/docs`
- ReDoc: `http://127.0.0.1:8088/redoc`
- OpenAPI JSON: `http://127.0.0.1:8088/openapi.json`
