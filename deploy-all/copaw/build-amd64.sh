#!/bin/bash
# =========================
# QwenPaw AMD64 版本 Docker 镜像构建脚本
# =========================

set -e  # 任意命令失败则退出

# --- 配置区 ---
IMAGE_NAME="qwenpaw"
TAG="latest"
DOCKERFILE="Dockerfile"
CONTEXT="../.."  # 构建上下文为项目根目录

# --- 构建开始 ---
echo "🎯 开始构建 AMD64 版本镜像: $IMAGE_NAME:$TAG"

# --- 构建 amd64 版本 ---
echo "📦 正在构建 linux/amd64 版本..."
docker buildx build \
  --platform linux/amd64 \
  -f "$DOCKERFILE" \
  -t $IMAGE_NAME:$TAG \
  --load \
  $CONTEXT

# --- 完成 ---
echo "✅ 构建完成！"
echo "🚀 镜像已构建并标记为: $IMAGE_NAME:$TAG"
echo ""
echo "💡 导出镜像："
echo "docker save -o qwenpaw-amd64.tar $IMAGE_NAME:$TAG"
echo ""
echo "💡 在目标设备上加载镜像："
echo "docker load -i qwenpaw-amd64.tar"
