# CoPaw 模型提供商与模型管理 API 文档

本文档描述了 CoPaw 中用于管理模型提供商和模型的 REST API 接口。

## 目录

- [概述](#概述)
- [数据模型](#数据模型)
- [提供商管理](#提供商管理)
- [模型管理](#模型管理)
- [活动模型管理](#活动模型管理)
- [本地模型管理](#本地模型管理)

## 概述

所有 API 接口均以 `/api` 为前缀，需要认证（除了公开路由）。

**Base URL**: `http://localhost:8088/api`

**认证**: 需要在请求头中携带 `Authorization: Bearer <token>`

## 数据模型

### ProviderInfo

```json
{
  "id": "string",              // 提供商唯一标识符
  "name": "string",            // 提供商显示名称
  "base_url": "string",        // API 基础 URL
  "api_key": "string",         // API 密钥
  "chat_model": "string",      // AgentScope ChatModel 名称，可选值: "OpenAIChatModel", "AnthropicChatModel", "GeminiChatModel"
  "models": [object Object] } } }, "api_key": "string",        // API 密钥（响应时可能被隐藏）
  "chat_model": "string",      // 聊天模型类名（OpenAIChatModel, AnthropicChatModel, GeminiChatModel）
  "models": [                  // 预定义模型列表
    {
      "id": "string",
      "name": "string",
      "supports_multimodal": "boolean | null",
      "supports_image": "boolean | null",
      "supports_video": "boolean | null",
      "probe_source": "string | null"
    }
  ],
  "extra_models": [],          // 用户添加的模型列表
  "api_key_prefix": "string",  // API 密钥前缀（如 "sk-"）
  "is_local": "boolean",       // 是否为本地提供商
  "freeze_url": "boolean",     // 是否冻结 base_url（不可编辑）
  "require_api_key": "boolean", // 是否需要 API 密钥
  "is_custom": "boolean",      // 是否为用户创建的自定义提供商
  "support_model_discovery": "boolean", // 是否支持模型发现
  "support_connection_check": "boolean", // 是否支持连接检查
  "generate_kwargs": {}        // 生成参数（如 temperature, top_p 等）
}
```

### ModelInfo

```json
{
  "id": "string",                   // 模型标识符（用于 API 调用）
  "name": "string",                 // 模型显示名称
  "supports_multimodal": "boolean | null",  // 是否支持多模态输入
  "supports_image": "boolean | null",       // 是否支持图像输入
  "supports_video": "boolean | null",       // 是否支持视频输入
  "probe_source": "string | null"   // 探测结果来源（'documentation' 或 'probed'）
}
```

### ActiveModelsInfo

```json
{
  "active_llm": {
    "provider_id": "string",  // 提供商 ID
    "model": "string"         // 模型 ID
  }
}
```

## 提供商管理

### 列出所有提供商

获取所有可用提供商的列表（包括内置和自定义）。

**请求**

```http
GET /api/models
```

**响应**

```json
[
  {
    "id": "openai",
    "name": "OpenAI",
    "base_url": "https://api.openai.com/v1",
    "chat_model": "OpenAIChatModel",
    "models": [
      {"id": "gpt-4", "name": "GPT-4"},
      {"id": "gpt-3.5-turbo", "name": "GPT-3.5 Turbo"}
    ],
    "is_local": false,
    "require_api_key": true,
    "support_model_discovery": true
  },
  {
    "id": "my-custom-provider",
    "name": "My Custom Provider",
    "base_url": "http://localhost:8000/v1",
    "chat_model": "OpenAIChatModel",
    "is_custom": true,
    "models": []
  }
]
```

---

### 配置提供商

配置提供商的 API 密钥、Base URL 等参数。

**请求**

```http
PUT /api/models/{provider_id}/config
Content-Type: application/json

{
  "api_key": "sk-xxxxx",
  "base_url": "https://api.openai.com/v1",
  "chat_model": "OpenAIChatModel",
  "generate_kwargs": {
    "temperature": 0.7,
    "top_p": 0.9,
    "max_tokens": 2048
  }
}
```

**参数说明**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `api_key` | string | 否 | API 密钥 |
| `base_url` | string | 否 | API Base URL |
| `chat_model` | string | 否 | 聊天模型类名（OpenAIChatModel, AnthropicChatModel, GeminiChatModel） |
| `generate_kwargs` | object | 否 | 生成参数，将在调用时传递给模型 |

**响应**

返回更新后的 `ProviderInfo` 对象。

---

### 创建自定义提供商

创建一个新的自定义模型提供商。

**请求**

```http
POST /api/models/custom-providers
Content-Type: application/json

{
  "id": "vllm-local",
  "name": "vLLM Local",
  "default_base_url": "http://localhost:8000/v1",
  "api_key_prefix": "",
  "chat_model": "OpenAIChatModel",
  "models": [
    {
      "id": "/path/to/model",
      "name": "My Model"
    }
  ]
}
```

**参数说明**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | string | 是 | 提供商唯一标识符 |
| `name` | string | 是 | 提供商显示名称 |
| `default_base_url` | string | 否 | 默认 Base URL |
| `api_key_prefix` | string | 否 | API 密钥前缀 |
| `chat_model` | string | 否 | 聊天模型类名（默认 OpenAIChatModel） |
| `models` | array | 否 | 初始模型列表 |

**响应**

返回创建的 `ProviderInfo` 对象，状态码 201。

---

### 删除自定义提供商

删除一个自定义提供商及其所有模型。

**请求**

```http
DELETE /api/models/custom-providers/{provider_id}
```

**响应**

返回更新后的提供商列表。

---

### 测试提供商连接

测试提供商的 API 密钥和 Base URL 是否有效。

**请求**

```http
POST /api/models/{provider_id}/test
Content-Type: application/json

{
  "api_key": "sk-test-key",
  "base_url": "https://api.openai.com/v1",
  "chat_model": "OpenAIChatModel"
}
```

**参数说明**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `api_key` | string | 否 | 测试用的 API 密钥（可选，不提供则使用已配置的） |
| `base_url` | string | 否 | 测试用的 Base URL（可选） |
| `chat_model` | string | 否 | 测试用的聊天模型类名（可选） |

**响应**

```json
{
  "success": true,
  "message": "Connection successful"
}
```

---

### 发现可用模型

从提供商 API 获取可用模型列表。

**请求**

```http
POST /api/models/{provider_id}/discover
Content-Type: application/json

{
  "api_key": "sk-xxxxx",
  "base_url": "https://api.openai.com/v1"
}
```

**响应**

```json
{
  "success": true,
  "models": [
    {"id": "gpt-4", "name": "GPT-4"},
    {"id": "gpt-3.5-turbo", "name": "GPT-3.5 Turbo"}
  ],
  "message": "Discovered 2 models",
  "added_count": 2
}
```

---

## 模型管理

### 添加模型到提供商

向提供商添加一个新模型。

**请求**

```http
POST /api/models/{provider_id}/models
Content-Type: application/json

{
  "id": "gpt-4-turbo",
  "name": "GPT-4 Turbo"
}
```

**响应**

返回更新后的 `ProviderInfo` 对象，状态码 201。

---

### 删除模型

从提供商中删除一个模型。

**请求**

```http
DELETE /api/models/{provider_id}/models/{model_id}
```

**注意**: `model_id` 支持 path 参数，可以包含 `/` 字符。

**响应**

返回更新后的 `ProviderInfo` 对象。

---

### 测试模型连接

测试特定模型是否可以正常工作。

**请求**

```http
POST /api/models/{provider_id}/models/test
Content-Type: application/json

{
  "model_id": "gpt-4"
}
```

**响应**

```json
{
  "success": true,
  "message": "Model connection successful"
}
```

---

### 探测模型多模态能力

探测模型是否支持图像和视频输入。

**请求**

```http
POST /api/models/{provider_id}/models/{model_id}/probe-multimodal
```

**响应**

```json
{
  "supports_image": true,
  "supports_video": false,
  "supports_multimodal": true,
  "image_message": "Image support confirmed",
  "video_message": "Video support not available"
}
```

---

## 活动模型管理

### 获取活动模型

获取当前活动的模型配置。

**请求**

```http
GET /api/models/active?scope=effective&agent_id=agent-001
```

**查询参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `scope` | string | 否 | 查询范围：`effective`（默认）、`global`、`agent` |
| `agent_id` | string | 否 | Agent ID（当 scope 为 `agent` 时必填） |

**Scope 说明**

- `effective`: 优先返回 Agent 特定配置，如无则返回全局配置
- `global`: 仅返回全局配置
- `agent`: 返回指定 Agent 的配置（需要 agent_id）

**响应**

```json
{
  "active_llm": {
    "provider_id": "openai",
    "model": "gpt-4"
  }
}
```

---

### 设置活动模型

设置全局或特定 Agent 的活动模型。

**请求**

```http
PUT /api/models/active
Content-Type: application/json

{
  "provider_id": "openai",
  "model": "gpt-4",
  "scope": "global",
  "agent_id": null
}
```

**参数说明**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `provider_id` | string | 是 | 提供商 ID |
| `model` | string | 是 | 模型 ID |
| `scope` | string | 是 | 设置范围：`global`（全局）或 `agent`（特定 Agent） |
| `agent_id` | string | 否 | Agent ID（当 scope 为 `agent` 时必填） |

**响应**

返回更新后的 `ActiveModelsInfo` 对象。

---

## 本地模型管理

### 列出本地模型

列出推荐和已下载的本地模型。

**请求**

```http
GET /api/local-models/models
```

**响应**

```json
[
  {
    "id": "Qwen/Qwen2.5-7B-Instruct-GGUF",
    "name": "Qwen2.5-7B-Instruct",
    "size": "4.2GB",
    "downloaded": true,
    "local_path": "/path/to/model"
  }
]
```

---

### 下载本地模型

开始下载指定的本地模型。

**请求**

```http
POST /api/local-models/models/download
Content-Type: application/json

{
  "model_name": "Qwen/Qwen2.5-7B-Instruct-GGUF",
  "source": "auto"
}
```

**参数说明**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `model_name` | string | 是 | 模型名称 |
| `source` | string | 否 | 下载源：`auto`、`modelscope`、`huggingface` |

**响应**

```json
{
  "status": "accepted",
  "message": "Local model download started: Qwen/Qwen2.5-7B-Instruct-GGUF"
}
```

---

### 获取模型下载进度

获取当前模型下载的进度。

**请求**

```http
GET /api/local-models/models/download
```

**响应**

```json
{
  "status": "downloading",
  "model_name": "Qwen/Qwen2.5-7B-Instruct-GGUF",
  "downloaded_bytes": 2147483648,
  "total_bytes": 4508876800,
  "speed_bytes_per_sec": 1048576,
  "source": "modelscope"
}
```

---

### 取消模型下载

取消当前的模型下载任务。

**请求**

```http
DELETE /api/local-models/models/download
```

**响应**

```json
{
  "status": "ok",
  "message": "Local model download cancellation requested"
}
```

---

### 检查本地服务器状态

检查 llama.cpp 本地服务器的状态。

**请求**

```http
GET /api/local-models/server
```

**响应**

```json
{
  "available": true,
  "installable": true,
  "installed": true,
  "port": 8080,
  "model_name": "Qwen/Qwen2.5-7B-Instruct-GGUF",
  "message": null
}
```

---

### 启动本地服务器

为下载的模型启动 llama.cpp 服务器。

**请求**

```http
POST /api/local-models/server
Content-Type: application/json

{
  "model_id": "Qwen/Qwen2.5-7B-Instruct-GGUF"
}
```

**响应**

```json
{
  "port": 8080,
  "model_name": "Qwen/Qwen2.5-7B-Instruct-GGUF"
}
```

服务器启动后会自动：
1. 更新 `copaw-local` 提供商的 `base_url` 为 `http://127.0.0.1:{port}/v1`
2. 添加模型到 `copaw-local` 提供商
3. 激活该模型为活动模型

---

### 停止本地服务器

停止正在运行的 llama.cpp 服务器。

**请求**

```http
DELETE /api/local-models/server
```

**响应**

```json
{
  "status": "ok",
  "message": "llama.cpp server stopped"
}
```

---

### 下载 llama.cpp

开始下载 llama.cpp 运行时。

**请求**

```http
POST /api/local-models/server/download
```

**响应**

```json
{
  "status": "accepted",
  "message": "llama.cpp download started"
}
```

---

### 获取 llama.cpp 下载进度

获取 llama.cpp 下载进度。

**请求**

```http
GET /api/local-models/server/download
```

**响应**

```json
{
  "status": "downloading",
  "downloaded_bytes": 52428800,
  "total_bytes": 104857600,
  "speed_bytes_per_sec": 524288
}
```

---

### 取消 llama.cpp 下载

取消 llama.cpp 下载任务。

**请求**

```http
DELETE /api/local-models/server/download
```

**响应**

```json
{
  "status": "ok",
  "message": "llama.cpp download cancellation requested"
}
```

---

## 错误响应

所有接口在出错时返回统一的错误格式：

```json
{
  "detail": "错误描述信息"
}
```

常见错误码：

| 状态码 | 说明 |
|--------|------|
| 400 | 请求参数错误 |
| 404 | 资源不存在（提供商或模型未找到） |
| 409 | 资源冲突（如重复下载） |
| 500 | 服务器内部错误 |

---

## 使用示例

### 示例 1：配置 vLLM 自定义提供商

```bash
# 1. 创建自定义提供商
curl -X POST http://localhost:8088/api/models/custom-providers \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{
    "id": "vllm",
    "name": "vLLM Local",
    "default_base_url": "http://localhost:8000/v1",
    "chat_model": "OpenAIChatModel"
  }'

# 2. 添加模型
curl -X POST http://localhost:8088/api/models/vllm/models \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{
    "id": "/models/Qwen2.5-7B",
    "name": "Qwen2.5-7B"
  }'

# 3. 测试连接
curl -X POST http://localhost:8088/api/models/vllm/test \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>"

# 4. 激活模型
curl -X PUT http://localhost:8088/api/models/active \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{
    "provider_id": "vllm",
    "model": "/models/Qwen2.5-7B",
    "scope": "global"
  }'
```

### 示例 2：使用 Ollama 提供商

```bash
# 1. 配置 Ollama 提供商
curl -X PUT http://localhost:8088/api/models/ollama/config \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{
    "base_url": "http://localhost:11434/v1"
  }'

# 2. 发现模型
curl -X POST http://localhost:8088/api/models/ollama/discover \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>"

# 3. 测试模型
curl -X POST http://localhost:8088/api/models/ollama/models/test \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"model_id": "llama2"}'
```

### 示例 3：为特定 Agent 配置模型

```bash
# 设置 agent-001 使用特定模型
curl -X PUT http://localhost:8088/api/models/active \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{
    "provider_id": "openai",
    "model": "gpt-4",
    "scope": "agent",
    "agent_id": "agent-001"
  }'

# 查询该 Agent 的活动模型
curl -X GET "http://localhost:8088/api/models/active?scope=agent&agent_id=agent-001" \
  -H "Authorization: Bearer <token>"
```

---

## 配置文件存储

- **提供商配置**: `$COPAW_SECRET_DIR/providers/`（默认 `~/.copaw.secret/providers/`）
  - 内置提供商: `builtin/` 目录
  - 自定义提供商: `custom/` 目录
  - 每个提供商一个 JSON 文件，如 `openai.json`

- **活动模型**: `$COPAW_SECRET_DIR/providers/active_model.json`

- **本地模型**: `$COPAW_WORKING_DIR/local_models/`（默认 `~/.copaw/local_models/`）
  - 运行时: `bin/` 目录
  - 模型文件: `models/` 目录

---

## 支持的聊天模型协议

CoPaw 支持以下聊天模型协议：

| 协议类名 | 说明 | 兼容提供商 |
|---------|------|-----------|
| `OpenAIChatModel` | OpenAI Chat Completions API | OpenAI, Azure, vLLM, Ollama, LM Studio 等 |
| `AnthropicChatModel` | Anthropic Messages API | Anthropic Claude |
| `GeminiChatModel` | Google Gemini API | Google AI Studio, Vertex AI |

---

## 最佳实践

1. **提供商配置**
   - 为本地部署的模型创建自定义提供商
   - 使用 `generate_kwargs` 配置默认生成参数
   - 定期测试连接以确保配置有效

2. **模型管理**
   - 使用发现功能自动获取可用模型
   - 对于不支持的模型，手动添加并测试
   - 探测多模态能力以了解模型功能

3. **活动模型**
   - 使用全局配置作为默认
   - 为需要特定模型的 Agent 配置单独的活动模型
   - 切换模型前确保目标模型可用

4. **本地模型**
   - 优先使用推荐的 GGUF 模型
   - 确保有足够的磁盘空间和内存
   - 本地服务器端口冲突时可手动配置
