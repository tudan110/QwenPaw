#!/bin/bash
# QwenPaw 项目启动脚本 (使用 uv)

# 兼容 sh 调用：若非 bash 则自动切换到 bash 执行
if [ -z "$BASH_VERSION" ]; then
    exec bash "$0" "$@"
fi

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

resolve_working_dir() {
    if [ -n "${QWENPAW_WORKING_DIR:-}" ]; then
        printf '%s\n' "$QWENPAW_WORKING_DIR"
        return
    fi
    printf '%s\n' "$HOME/.qwenpaw"
}

WORKING_DIR="$(resolve_working_dir)"
export QWENPAW_WORKING_DIR="$WORKING_DIR"
VENV_DIR=".venv"

REBUILD_FRONTEND=false
ARGS=()
for arg in "$@"; do
    if [ "$arg" = "--rebuild" ]; then
        REBUILD_FRONTEND=true
    else
        ARGS+=("$arg")
    fi
done

echo "=========================================="
echo "  QwenPaw 启动脚本"
echo "=========================================="

# 检查并安装 uv
if ! command -v uv &> /dev/null; then
    echo "[1/5] 安装 uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
else
    echo "[1/5] uv 已安装"
fi

UV_VERSION=$(uv --version 2>&1)
echo "      $UV_VERSION"

# 创建虚拟环境（如果不存在）
if [ ! -d "$VENV_DIR" ]; then
    echo "[2/5] 创建虚拟环境..."
    uv venv "$VENV_DIR"
else
    echo "[2/5] 虚拟环境已存在，跳过创建"
fi

# 安装依赖（不包含 mlx，仅支持 Apple Silicon arm64）
echo "[3/5] 安装依赖..."
UV_HTTP_TIMEOUT=300 uv pip install -e ".[dev]"

# 构建前端（如果需要）
CONSOLE_DIST="$SCRIPT_DIR/console/dist"
NEED_BUILD=false

if [ "$REBUILD_FRONTEND" = true ]; then
    NEED_BUILD=true
    rm -rf "$CONSOLE_DIST"
    echo "[4/5] 强制重新构建前端..."
elif [ ! -d "$CONSOLE_DIST" ] || [ ! -f "$CONSOLE_DIST/index.html" ]; then
    NEED_BUILD=true
    echo "[4/5] 构建前端..."
else
    echo "[4/5] 前端已构建，跳过（使用 --rebuild 强制重新构建）"
fi

if [ "$NEED_BUILD" = true ]; then
    if command -v pnpm &> /dev/null; then
        echo "      使用 pnpm 加速构建..."
        cd "$SCRIPT_DIR/console"
        pnpm install --frozen-lockfile=false
        pnpm run build
        cd "$SCRIPT_DIR"
    elif command -v npm &> /dev/null; then
        cd "$SCRIPT_DIR/console"
        npm ci --quiet
        npm run build
        cd "$SCRIPT_DIR"
    else
        echo "警告: 未找到 npm 或 pnpm，跳过前端构建"
        echo "如需前端界面，请手动安装 Node.js 并运行: cd console && npm ci && npm run build"
    fi
fi

# 初始化配置（如果需要）
CONFIG_FILE="$WORKING_DIR/config.json"
if [ ! -f "$CONFIG_FILE" ]; then
    echo "[5/5] 初始化配置..."
    source "$VENV_DIR/bin/activate"
    qwenpaw init --defaults
else
    echo "[5/5] 配置已存在，跳过初始化"
    source "$VENV_DIR/bin/activate"
fi

echo ""
echo "=========================================="
echo "  启动 QwenPaw..."
echo "=========================================="
echo ""

# 同步故障处置 builtin skill 到 fault 工作区，避免工作区副本滞后
FAULT_WORKSPACE_SKILL_DIR="$WORKING_DIR/workspaces/fault/skills/fault-disposal"
FAULT_SOURCE_SKILL_DIR="$SCRIPT_DIR/src/qwenpaw/agents/skills/fault-disposal"
if [ -d "$FAULT_SOURCE_SKILL_DIR" ] && [ -d "$(dirname "$FAULT_WORKSPACE_SKILL_DIR")" ]; then
    echo "[sync] 同步 fault-disposal skill 到工作区..."
    mkdir -p "$FAULT_WORKSPACE_SKILL_DIR"
    rsync -a --delete "$FAULT_SOURCE_SKILL_DIR/" "$FAULT_WORKSPACE_SKILL_DIR/"
fi

# 同步 portal 扩展路由到 QwenPaw custom_channels，避免换机器后 /api/portal/* 丢失
PORTAL_CUSTOM_CHANNEL_DIR="$WORKING_DIR/custom_channels"
PORTAL_CUSTOM_CHANNEL_FILE="$PORTAL_CUSTOM_CHANNEL_DIR/portal_api.py"
echo "[sync] 同步 portal_api custom channel..."
mkdir -p "$PORTAL_CUSTOM_CHANNEL_DIR"
cat > "$PORTAL_CUSTOM_CHANNEL_FILE" <<'PY'
from qwenpaw.extensions.api.portal_backend import register_app_routes


__all__ = ["register_app_routes"]
PY

# 启动应用
qwenpaw app "${ARGS[@]}"
