# 从本地用户目录同步到 deploy-all 指南

本文档记录如何从 `~/.copaw` 同步数据到 `deploy-all/copaw/data/copaw`，用于 Docker 镜像打包。

> **重要提示**：CoPaw 版本升级可能导致目录结构变化，同步前请先检查代码确认当前版本的目录结构。参见 [版本升级检查](#版本升级检查) 章节。

## 目录结构对照

| 本地目录 | 部署目录 | 说明 |
|---------|---------|------|
| `~/.copaw/` | `deploy-all/copaw/data/copaw/` | 主目录 |
| `~/.copaw.secret/` | `deploy-all/copaw/data/copaw.secret/` | 大模型配置（API Key 等） |

> **注意**：`copaw.secret` 目录包含大模型 Provider 配置，需要打包到 Docker 镜像中。该目录通常包含：
> - `providers/active_model.json` - 当前激活的模型配置
> - `providers/builtin/` - 内置 Provider 配置
> - `providers/custom/` - 自定义 Provider 配置

## 同步步骤

### 1. 清理旧版目录和文件

```bash
# 清理工作区旧目录
cd deploy-all/copaw/data/copaw
find workspaces -type d \( -name "active_skills" -o -name "customized_skills" -o -name "dialog" -o -name "embedding_cache" \) -exec rm -rf {} + 2>/dev/null

# 清理旧文件
find workspaces -type f \( -name "copaw_file_metadata.json" -o -name "token_usage.json" -o -name "memory.md" \) -delete 2>/dev/null
rm -f copaw_file_metadata.json 2>/dev/null
```

### 2. 同步共享技能池

```bash
rm -rf deploy-all/copaw/data/copaw/skill_pool 2>/dev/null
mkdir -p deploy-all/copaw/data/copaw/skill_pool
rsync -a --exclude='.DS_Store' --exclude='__pycache__' --exclude='*.pyc' --exclude='.venv' --exclude='.lock' \
  ~/.copaw/skill_pool/ deploy-all/copaw/data/copaw/skill_pool/
```

### 3. 同步工作区技能目录

```bash
for ws in $(ls ~/.copaw/workspaces/); do
  # 删除旧的 skills 目录
  rm -rf "deploy-all/copaw/data/copaw/workspaces/$ws/skills" 2>/dev/null
  rm -rf "deploy-all/copaw/data/copaw/workspaces/$ws/.skill.json.lock" 2>/dev/null
  
  # 同步 skills 目录
  if [ -d ~/.copaw/workspaces/$ws/skills ]; then
    mkdir -p "deploy-all/copaw/data/copaw/workspaces/$ws/skills"
    rsync -a --exclude='.DS_Store' --exclude='__pycache__' --exclude='*.pyc' --exclude='.venv' --exclude='.lock' \
      ~/.copaw/workspaces/$ws/skills/ "deploy-all/copaw/data/copaw/workspaces/$ws/skills/"
  fi
  
  # 同步 skill.json
  if [ -f ~/.copaw/workspaces/$ws/skill.json ]; then
    cp ~/.copaw/workspaces/$ws/skill.json "deploy-all/copaw/data/copaw/workspaces/$ws/"
  fi
done
```

### 4. 同步配置文件并替换路径

```bash
# 同步并更新 config.json
cp ~/.copaw/config.json deploy-all/copaw/data/copaw/config.json
sed -i '' 's|/Users/tudan/.copaw|/app/working|g' deploy-all/copaw/data/copaw/config.json
sed -i '' 's|~/.copaw|/app/working|g' deploy-all/copaw/data/copaw/config.json

# 同步并更新各工作区的 agent.json
for ws in $(ls ~/.copaw/workspaces/); do
  if [ -f ~/.copaw/workspaces/$ws/agent.json ]; then
    cp ~/.copaw/workspaces/$ws/agent.json "deploy-all/copaw/data/copaw/workspaces/$ws/agent.json"
    sed -i '' 's|/Users/tudan/.copaw|/app/working|g' "deploy-all/copaw/data/copaw/workspaces/$ws/agent.json"
    sed -i '' 's|~/.copaw|/app/working|g' "deploy-all/copaw/data/copaw/workspaces/$ws/agent.json"
  fi
done

# 更新 skill.json 路径
for ws in $(ls ~/.copaw/workspaces/); do
  if [ -f "deploy-all/copaw/data/copaw/workspaces/$ws/skill.json" ]; then
    sed -i '' 's|/Users/tudan/.copaw|/app/working|g' "deploy-all/copaw/data/copaw/workspaces/$ws/skill.json"
    sed -i '' 's|~/.copaw|/app/working|g' "deploy-all/copaw/data/copaw/workspaces/$ws/skill.json"
  fi
done

# 更新 skill_pool/skill.json 路径
if [ -f deploy-all/copaw/data/copaw/skill_pool/skill.json ]; then
  sed -i '' 's|/Users/tudan/.copaw|/app/working|g' deploy-all/copaw/data/copaw/skill_pool/skill.json
  sed -i '' 's|~/.copaw|/app/working|g' deploy-all/copaw/data/copaw/skill_pool/skill.json
fi
```

### 5. 同步工作区其他文件

```bash
for ws in $(ls ~/.copaw/workspaces/); do
  # 同步必要的 JSON 文件
  for f in chats.json jobs.json feishu_receive_ids.json; do
    if [ -f ~/.copaw/workspaces/$ws/$f ]; then
      cp ~/.copaw/workspaces/$ws/$f "deploy-all/copaw/data/copaw/workspaces/$ws/$f"
    fi
  done
  
  # 同步 Markdown 文件
  for f in AGENTS.md BOOTSTRAP.md HEARTBEAT.md MEMORY.md PROFILE.md SOUL.md; do
    if [ -f ~/.copaw/workspaces/$ws/$f ]; then
      cp ~/.copaw/workspaces/$ws/$f "deploy-all/copaw/data/copaw/workspaces/$ws/$f"
    fi
  done
done
```

### 6. 同步大模型配置目录 (copaw.secret)

```bash
# 同步 copaw.secret 目录（包含大模型 Provider 配置）
rm -rf deploy-all/copaw/data/copaw.secret 2>/dev/null
mkdir -p deploy-all/copaw/data/copaw.secret
rsync -a --exclude='.DS_Store' \
  ~/.copaw.secret/ deploy-all/copaw/data/copaw.secret/
```

> **说明**：`copaw.secret` 目录包含大模型 API Key 等敏感配置，需要打包到镜像中，容器启动后会自动加载。请确保该目录中的 API Key 是有效的，或者在部署后通过环境变量覆盖。

### 7. 清理运行时数据（不打包进镜像）

```bash
for ws in $(ls deploy-all/copaw/data/copaw/workspaces/); do
  rm -rf "deploy-all/copaw/data/copaw/workspaces/$ws/sessions" 2>/dev/null
  rm -rf "deploy-all/copaw/data/copaw/workspaces/$ws/file_store" 2>/dev/null
  rm -rf "deploy-all/copaw/data/copaw/workspaces/$ws/tool_result" 2>/dev/null
  rm -f "deploy-all/copaw/data/copaw/workspaces/$ws/chats.json" 2>/dev/null
  rm -f "deploy-all/copaw/data/copaw/workspaces/$ws/feishu_receive_ids.json" 2>/dev/null
done

rm -f deploy-all/copaw/data/copaw/token_usage.json 2>/dev/null
rm -f deploy-all/copaw/data/copaw/copaw.log 2>/dev/null
```

### 8. 清理 Python 缓存和系统文件

```bash
find deploy-all/copaw/data/copaw -type d \( -name ".venv" -o -name "__pycache__" -o -name "*.egg-info" \) -exec rm -rf {} + 2>/dev/null
find deploy-all/copaw/data/copaw -name "*.pyc" -delete 2>/dev/null
find deploy-all/copaw/data/copaw -name ".DS_Store" -delete 2>/dev/null
```

### 9. 敏感文件处理

**注意**：`.env` 文件包含 API Token 等敏感信息，请根据实际情况决定是否保留。

> **重要提示**：Skills 目录下的 `.env` 文件通常包含外部系统的 API Token（如告警系统、数据库连接等）。同步前请确认：
> - 该 Token 是否可以用于生产环境
> - 是否需要使用环境变量或 Secret 替代
> - 是否需要与运维团队确认

```bash
# 询问是否同步 .env 文件
echo "是否同步 .env 文件？(y/n)"
read -r SYNC_ENV

if [ "$SYNC_ENV" = "y" ]; then
  echo "保留 .env 文件..."
else
  echo "删除 .env 文件..."
  find deploy-all/copaw/data/copaw -name ".env" -type f -delete 2>/dev/null
fi
```

或者直接决定：

```bash
# 如果不需要打包敏感配置，删除 .env 文件
find deploy-all/copaw/data/copaw -name ".env" -type f -delete 2>/dev/null

# 如果需要保留，确保 .env 文件已同步
```

## 路径替换规则

| 本地路径 | 容器路径 |
|---------|---------|
| `/Users/tudan/.copaw` | `/app/working` |
| `~/.copaw` | `/app/working` |

## 已废弃的目录/文件

以下目录/文件是旧版本遗留，应删除：

| 类型 | 名称 | 说明 |
|------|------|------|
| 目录 | `active_skills/` | 旧版技能目录，已迁移到 `skills/` |
| 目录 | `customized_skills/` | 旧版自定义技能目录 |
| 目录 | `dialog/` | 空目录，未使用 |
| 目录 | `embedding_cache/` | 空目录，未使用 |
| 文件 | `copaw_file_metadata.json` | 未被代码引用的缓存文件 |
| 文件 | `token_usage.json` (工作区内) | 空数组，实际使用根目录版本 |
| 文件 | `memory.md` | 与 `MEMORY.md` 重复（小写旧版） |

## 不应打包的运行时数据

以下数据在容器运行时生成，不应打包进镜像：

| 目录/文件 | 说明 |
|----------|------|
| `sessions/` | 会话数据 |
| `file_store/` | 文件存储（含向量数据库） |
| `tool_result/` | 工具结果缓存 |
| `chats.json` | 聊天记录 |
| `feishu_receive_ids.json` | 飞书接收 ID |
| `token_usage.json` | Token 使用统计 |
| `copaw.log` | 日志文件 |
| `.venv/` | Python 虚拟环境 |
| `__pycache__/` | Python 缓存 |
| `*.pyc` | 编译后的 Python 文件 |

## 一键同步脚本

可以将以上步骤合并为一个脚本 `sync-from-local.sh`：

```bash
#!/bin/bash
set -e

DEPLOY_DIR="deploy-all/copaw/data/copaw"
LOCAL_DIR="$HOME/.copaw"

echo "=== Step 1: Clean old directories ==="
cd "$DEPLOY_DIR"
find workspaces -type d \( -name "active_skills" -o -name "customized_skills" -o -name "dialog" -o -name "embedding_cache" \) -exec rm -rf {} + 2>/dev/null || true
find workspaces -type f \( -name "copaw_file_metadata.json" -o -name "token_usage.json" -o -name "memory.md" \) -delete 2>/dev/null || true

echo "=== Step 2: Sync skill_pool ==="
rm -rf skill_pool
mkdir -p skill_pool
rsync -a --exclude='.DS_Store' --exclude='__pycache__' --exclude='*.pyc' --exclude='.venv' --exclude='.lock' \
  "$LOCAL_DIR/skill_pool/" skill_pool/

echo "=== Step 3: Sync workspace skills ==="
for ws in $(ls "$LOCAL_DIR/workspaces/"); do
  rm -rf "workspaces/$ws/skills" "workspaces/$ws/.skill.json.lock" 2>/dev/null || true
  if [ -d "$LOCAL_DIR/workspaces/$ws/skills" ]; then
    mkdir -p "workspaces/$ws/skills"
    rsync -a --exclude='.DS_Store' --exclude='__pycache__' --exclude='*.pyc' --exclude='.venv' --exclude='.lock' \
      "$LOCAL_DIR/workspaces/$ws/skills/" "workspaces/$ws/skills/"
  fi
  [ -f "$LOCAL_DIR/workspaces/$ws/skill.json" ] && cp "$LOCAL_DIR/workspaces/$ws/skill.json" "workspaces/$ws/"
done

echo "=== Step 4: Sync config files and update paths ==="
cp "$LOCAL_DIR/config.json" config.json
sed -i '' 's|/Users/[^/]*/.copaw|/app/working|g' config.json
sed -i '' 's|~/.copaw|/app/working|g' config.json

for ws in $(ls "$LOCAL_DIR/workspaces/"); do
  if [ -f "$LOCAL_DIR/workspaces/$ws/agent.json" ]; then
    cp "$LOCAL_DIR/workspaces/$ws/agent.json" "workspaces/$ws/agent.json"
    sed -i '' 's|/Users/[^/]*/.copaw|/app/working|g' "workspaces/$ws/agent.json"
    sed -i '' 's|~/.copaw|/app/working|g' "workspaces/$ws/agent.json"
  fi
  [ -f "workspaces/$ws/skill.json" ] && sed -i '' 's|~/.copaw|/app/working|g; s|/Users/[^/]*/.copaw|/app/working|g' "workspaces/$ws/skill.json"
done

[ -f skill_pool/skill.json ] && sed -i '' 's|~/.copaw|/app/working|g; s|/Users/[^/]*/.copaw|/app/working|g' skill_pool/skill.json

echo "=== Step 5: Sync workspace files ==="
for ws in $(ls "$LOCAL_DIR/workspaces/"); do
  for f in AGENTS.md BOOTSTRAP.md HEARTBEAT.md MEMORY.md PROFILE.md SOUL.md chats.json jobs.json; do
    [ -f "$LOCAL_DIR/workspaces/$ws/$f" ] && cp "$LOCAL_DIR/workspaces/$ws/$f" "workspaces/$ws/"
  done
done

echo "=== Step 6: Sync copaw.secret (model providers) ==="
rm -rf ../copaw.secret 2>/dev/null || true
mkdir -p ../copaw.secret
rsync -a --exclude='.DS_Store' "$HOME/.copaw.secret/" ../copaw.secret/

echo "=== Step 7: Clean runtime data ==="
for ws in $(ls workspaces/); do
  rm -rf "workspaces/$ws/sessions" "workspaces/$ws/file_store" "workspaces/$ws/tool_result" 2>/dev/null || true
  rm -f "workspaces/$ws/chats.json" "workspaces/$ws/feishu_receive_ids.json" 2>/dev/null || true
done
rm -f token_usage.json copaw.log 2>/dev/null || true

echo "=== Step 8: Clean cache files ==="
find . -type d \( -name ".venv" -o -name "__pycache__" \) -exec rm -rf {} + 2>/dev/null || true
find . -name "*.pyc" -delete 2>/dev/null || true
find . -name ".DS_Store" -delete 2>/dev/null || true

echo "=== Step 9: Handle .env files ==="
echo "Skills 目录下可能包含 .env 文件（如 real-alarm/.env 包含 API Token）"
echo "是否同步 .env 文件？(y/n)"
read -r SYNC_ENV
if [ "$SYNC_ENV" = "y" ]; then
  echo "保留 .env 文件..."
else
  echo "删除 .env 文件..."
  find . -name ".env" -type f -delete 2>/dev/null || true
fi

echo "=== Done ==="
du -sh .
```

## 验证同步结果

```bash
# 检查主目录结构
ls deploy-all/copaw/data/copaw/
ls deploy-all/copaw/data/copaw/workspaces/fault/
ls deploy-all/copaw/data/copaw/skill_pool/

# 检查大模型配置目录
ls deploy-all/copaw/data/copaw.secret/
ls deploy-all/copaw/data/copaw.secret/providers/
cat deploy-all/copaw/data/copaw.secret/providers/active_model.json

# 检查路径是否正确替换
grep "/app/working" deploy-all/copaw/data/copaw/config.json | head -5

# 检查是否有残留的本地路径
grep -r "~/.copaw\|/Users/" deploy-all/copaw/data/copaw/*.json || echo "No local paths found"
```

## 版本升级检查

CoPaw 版本升级后，目录结构可能发生变化。同步前请先检查以下代码文件确认当前结构：

### 1. 检查工作区目录结构

```bash
# 检查工作区使用哪些目录
grep -rn "workspace_dir\|sessions\|memory\|file_store\|media\|tool_result" \
  src/copaw/constant.py src/copaw/config/config.py src/copaw/app/workspace/
```

关键文件：
- `src/copaw/constant.py` - 定义默认目录常量
- `src/copaw/config/config.py` - 配置结构定义
- `src/copaw/app/workspace/workspace.py` - 工作区管理逻辑

### 2. 检查技能目录结构

```bash
# 检查技能目录定义
grep -rn "skills\|skill_pool\|active_skills\|customized_skills" \
  src/copaw/agents/skills_manager.py src/copaw/app/migration.py
```

关键文件：
- `src/copaw/agents/skills_manager.py` - 技能管理核心逻辑
- `src/copaw/app/migration.py` - 迁移逻辑，包含旧目录清理

### 3. 检查废弃目录

```bash
# 检查迁移逻辑中的废弃目录
grep -rn "active_skills\|customized_skills\|dialog\|embedding_cache" \
  src/copaw/app/migration.py
```

迁移文件 `src/copaw/app/migration.py` 中的 `_WORKSPACE_ITEMS_TO_MIGRATE` 和相关注释会说明哪些目录是旧版废弃的。

### 4. 检查运行时数据目录

```bash
# 检查哪些是运行时生成的目录
grep -rn "sessions\|file_store\|tool_result\|chats\.json\|token_usage" \
  src/copaw/constant.py src/copaw/app/workspace/
```

### 5. 检查敏感文件处理

```bash
# 检查 .env 文件的处理方式
grep -rn "\.env\|dotenv" src/copaw/agents/skills_manager.py

# 检查 copaw.secret 目录定义
grep -rn "secret\|SECRET_DIR\|copaw\.secret" src/copaw/constant.py
```

### 6. 检查大模型配置目录 (copaw.secret)

```bash
# 检查 Provider 配置加载逻辑
grep -rn "providers\|active_model\|copaw.secret" \
  src/copaw/config/config.py src/copaw/agents/
```

关键文件：
- `src/copaw/constant.py` - 定义 `SECRET_DIR` 常量
- `src/copaw/config/config.py` - Provider 配置加载逻辑

### 常见版本升级变化

| 变化类型 | 检查方式 | 示例 |
|---------|---------|------|
| 新增目录 | 检查 `constant.py` 中的新常量 | `MEMORY_DIR`, `CUSTOM_CHANNELS_DIR` |
| 目录重命名 | 检查 `migration.py` 中的迁移逻辑 | `active_skills` → `skills` |
| 废弃目录 | 检查 `migration.py` 中的清理逻辑 | `dialog`, `embedding_cache` |
| 配置结构变化 | 检查 `config.py` 中的模型定义 | 新增字段、字段重命名 |
| 敏感信息处理 | 检查技能加载逻辑 | `.env` 文件是否被 gitignore |
| 大模型配置变化 | 检查 `copaw.secret` 目录结构 | Provider 配置格式变化 |

### 版本升级同步流程

1. **更新代码**
   ```bash
   git pull origin main
   ```

2. **检查变更日志**
   ```bash
   git log --oneline -20
   git diff HEAD~10 -- src/copaw/constant.py src/copaw/app/migration.py
   ```

3. **检查目录结构变化**
   ```bash
   # 按上述方法检查关键文件
   ```

4. **更新本文档**
   - 如果发现新的目录结构变化，更新本文档的相应章节
   - 更新废弃目录列表
   - 更新运行时数据列表

5. **执行同步**
   - 按本文档步骤执行同步
   - 如有新的废弃目录，先清理再同步

### 快速检查脚本

```bash
#!/bin/bash
# version-check.sh - 快速检查版本变化

echo "=== 检查工作区目录常量 ==="
grep -E "^[A-Z_]+_DIR\s*=" src/copaw/constant.py

echo ""
echo "=== 检查迁移项 ==="
grep -A 10 "_WORKSPACE_ITEMS_TO_MIGRATE\s*=" src/copaw/app/migration.py

echo ""
echo "=== 检查技能目录定义 ==="
grep -n "def get_.*skills.*dir\|SKILL_POOL\|skill_pool\|active_skills" \
  src/copaw/agents/skills_manager.py | head -20

echo ""
echo "=== 检查工作区初始化 ==="
grep -n "mkdir\|\.json\|sessions\|memory\|file_store" \
  src/copaw/app/workspace/workspace.py | head -30
```
