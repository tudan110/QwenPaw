# QwenPaw 部署说明

QwenPaw 应用的容器化部署配置，包含前后端一体化镜像，支持 Docker 和 Kubernetes (k3s) 部署。

## 目录结构

```
deploy-all/qwenpaw/
├── Dockerfile                  # 多阶段构建配置
├── entrypoint.sh               # 容器入口脚本
├── build-amd64.sh              # AMD64 版本构建脚本
├── build-arm64.sh              # ARM64 版本构建脚本
├── config/
│   └── supervisord.conf.template  # Supervisor 配置模板
└── helm/
    └── qwenpaw/
        ├── Chart.yaml
        ├── values.yaml
        └── templates/
            ├── _helpers.tpl
            ├── deployment.yaml
            ├── service.yaml
            └── pvc.yaml
```

## 应用说明

QwenPaw 是一个前后端一体化应用：
- **前端**: console（React 应用）
- **后端**: Python 应用（qwenpaw）
- **端口**: 8088
- **特性**: 内置 Chromium 浏览器，支持自动化任务
- **Portal 扩展路由**: 容器启动时会自动写入 `custom_channels/portal_api.py`，确保 `/api/portal/*` 可供 Portal 前端访问
- **后端启动器**: 容器默认使用 `qwenpaw.extensions.runtime.worker_app`；当前审批和运行中任务要求单 worker、单副本

## Docker 构建

完整构建原则和归档说明见
[`QWENPAW_IMAGE_BUILD.md`](../QWENPAW_IMAGE_BUILD.md)。
**以后后端镜像也统一导出到仓库根目录的 `deploy-all/images/`，覆盖同名旧包**：

- AMD64：`deploy-all/images/qwenpaw-amd64.tar.gz`
- ARM64：`deploy-all/images/qwenpaw-arm64.tar.gz`

不要把正式产物仅留在当前目录、Downloads 或会话临时目录。压缩包不提交 Git。

在项目根目录执行：

```bash
docker build -f deploy-all/qwenpaw/Dockerfile -t qwenpaw:latest .
```

### 按架构构建并导出

以下 Bash 命令在仓库根目录执行。本机打包机为 Intel 芯片 macOS，双架构打包
固定先完成 **amd64**，再构建 **arm64**，避免 ARM64 模拟构建拖慢 AMD64 交付。
两个架构复用 `qwenpaw:latest`，应逐个构建并立即导出，防止下一个构建覆盖 tag
后导出错误架构。
现有脚本负责构建和镜像内依赖检查，不自动导出压缩包。

只打包某个架构时，将循环列表改为 `amd64` 或 `arm64`；后端打包不要求同时打包 Portal。

```bash
set -euo pipefail
mkdir -p deploy-all/images

for ARCH in amd64 arm64; do
  (cd deploy-all/qwenpaw && bash "./build-$ARCH.sh")

  ACTUAL=$(docker image inspect qwenpaw:latest --format '{{.Os}}/{{.Architecture}}')
  test "$ACTUAL" = "linux/$ARCH"

  PACKAGE="deploy-all/images/qwenpaw-$ARCH.tar.gz"
  docker save qwenpaw:latest | gzip > "$PACKAGE.partial"
  gzip -t "$PACKAGE.partial"
  chmod 644 "$PACKAGE.partial"
  mv -f "$PACKAGE.partial" "$PACKAGE"
done

shasum -a 256 deploy-all/images/qwenpaw-*.tar.gz
```

新包导出并通过校验后才覆盖旧包；构建或导出失败时保留旧包。
上传后核对远程文件与本地 SHA-256 一致。打包本身不自动上传、导入或部署，
这些操作以当次明确要求为准。

在目标 Docker 设备上加载对应架构的包（示例为 ARM64）：

```bash
docker load -i qwenpaw-arm64.tar.gz
```

k3s/containerd 的导入与部署方式见
[`deploy-all/README.md`](../README.md#离线一键部署--升级k3s--k8s)。

## Helm 部署 (k3s)

```bash
# 打包
helm package ./deploy-all/qwenpaw/helm/qwenpaw

# 安装
helm install qwenpaw ./deploy-all/qwenpaw/helm/qwenpaw

# 升级
helm upgrade qwenpaw ./deploy-all/qwenpaw/helm/qwenpaw

# 卸载
helm uninstall qwenpaw
```

## 配置说明

### 镜像配置 (values.yaml)

```yaml
image:
  repository: qwenpaw
  tag: latest
  pullPolicy: IfNotPresent
```

### 后端 worker 配置

```yaml
env:
  QWENPAW_APP_WORKERS: "1"
  QWENPAW_APP_BACKLOG: "2048"
  QWENPAW_APP_TIMEOUT_KEEP_ALIVE: "5"
```

审批请求和运行中的聊天任务保存在进程内，当前应保持单 worker、单副本。
多 worker 或多副本可能导致审批列表与批准请求落到不同进程，出现
`Approval request not found`。单 worker 仍支持异步并发请求，但 CPU
密集型请求的吞吐能力会低于多进程配置；修改配置后需要重启后端。

### 服务配置

```yaml
service:
  type: ClusterIP
  port: 8088
  targetPort: 8088
```

默认仅集群内访问：`http://qwenpaw:8088`。确有外部直连需求时，须显式设置
`type: NodePort`、`nodePort: 30088` 并配置受限入口；默认不向节点暴露后端。
非 root、运行时 Secret、旧 PVC 和网络放行的升级要求见
[`QWENPAW_IMAGE_BUILD.md`](../QWENPAW_IMAGE_BUILD.md#安全默认值与升级迁移bc-p0)。

### 持久化存储

```yaml
persistence:
  enabled: true
  size: 10Gi
  workingDir:
    mountPath: /app/working
  secretDir:
    mountPath: /app/working.secret
```

### 环境变量

```yaml
env:
  QWENPAW_PORT: "8088"
  QWENPAW_DISABLED_CHANNELS: "imessage"
```

### 自定义配置

创建自定义 values 文件：

```bash
helm install qwenpaw ./deploy-all/qwenpaw/helm/qwenpaw -f my-values.yaml
```
