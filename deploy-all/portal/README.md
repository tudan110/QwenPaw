# Digital Workforce Portal 部署说明

Portal 前端项目的容器化部署配置，支持 Docker 和 Kubernetes (k3s) 部署。

## 目录结构

```
deploy-all/portal/
├── Dockerfile              # 多阶段构建配置
├── docker-compose.yml      # Docker Compose 部署配置
├── nginx.conf              # Nginx 配置文件
├── build-amd64.sh          # AMD64 版本构建脚本
├── build-arm64.sh          # ARM64 版本构建脚本
└── helm/
    └── digital-workforce-portal/
        ├── Chart.yaml
        ├── values.yaml
        └── templates/
            ├── _helpers.tpl
            ├── deployment.yaml
            └── service.yaml
```

## Docker 构建

### 构建依据和交付约定

构建前先阅读仓库根目录 `CLAUDE.md`，再参考本说明、
`deploy-all/portal/Dockerfile`、`build-amd64.sh` 和 `build-arm64.sh`。
运行配置以 `nginx.conf` 和 `docker-entrypoint.d/40-runtime-config.sh`
为准。

- 前端是 `portal/`，不是 `console/`；镜像名和当前版本为
  `digital-workforce-portal:0.1.0`。
- 默认构建当前工作区内容，包含未提交的前端修改；交付前确认这些修改属于本次打包范围。
- **正式镜像包统一导出到仓库根目录下的 `deploy-all/images/`，直接覆盖同名旧包**，
  不要只留在临时目录或会话目录。
- 文件名固定为 `digital-workforce-portal-amd64.tar.gz` 和
  `digital-workforce-portal-arm64.tar.gz`，均为 gzip 压缩的 Docker 镜像归档，
  不是源码包或容器文件系统导出包。
- 两个架构可以使用相同镜像 tag，但必须分别构建、立即导出，再构建下一个架构，
  避免导出时拿错架构。现有 `build-*.sh` 只构建和加载镜像，不会自动导出压缩包。
- 本机打包机为 Intel 芯片 macOS，双架构打包固定先完成 **amd64**，再构建
  **arm64**；ARM64 模拟构建明显较慢，不要让它阻塞 AMD64 正式包的生成和交付。

### 双架构构建并导出

以下命令使用 Bash，在项目根目录执行。需要 Docker daemon 和支持
`linux/amd64`、`linux/arm64` 的 buildx builder；先用 `docker buildx ls`
确认，必要时为构建命令指定 `--builder <名称>`。

```bash
set -euo pipefail
mkdir -p deploy-all/images
IMAGE=digital-workforce-portal:0.1.0

for ARCH in amd64 arm64; do
  docker buildx build \
    --platform "linux/$ARCH" \
    -f deploy-all/portal/Dockerfile \
    -t "$IMAGE" \
    --load .

  ACTUAL=$(docker image inspect "$IMAGE" --format '{{.Os}}/{{.Architecture}}')
  test "$ACTUAL" = "linux/$ARCH"

  PACKAGE="deploy-all/images/digital-workforce-portal-$ARCH.tar.gz"
  docker save "$IMAGE" | gzip > "$PACKAGE.tmp"
  gzip -t "$PACKAGE.tmp"
  chmod 644 "$PACKAGE.tmp"
  mv -f "$PACKAGE.tmp" "$PACKAGE"
done

shasum -a 256 deploy-all/images/digital-workforce-portal-*.tar.gz
```

只有导出和压缩校验成功后才替换旧包，失败时保留旧包。更改镜像版本时，
同步调整部署配置中的 tag。

### ARM64 模拟编译过慢时的替代方式

Portal 的 Vite 构建结果是架构无关的静态 HTML、CSS、JavaScript 和字体资源，
无需在两个 CPU 架构下重复编译。按 amd64 优先的顺序，先用原 Dockerfile
完成 amd64 镜像，并从这次构建取得静态资源。若 ARM64 模拟环境长时间停留在
`vite ... transforming...`、尚未报错，不要继续等待它重复编译；可以：

1. 在本机原生架构完成一次前端构建，或从同一工作区已构建好的前端镜像中提取
   `/usr/share/nginx/html/`。
2. 复用这份静态资源，以 `--platform linux/arm64` 选择真正的 ARM64
   `nginx:alpine` 基础镜像；不能仅给 AMD64 镜像改名或修改架构标记。
3. 保持原 Dockerfile 的 production 阶段行为：复制静态资源、nginx 配置和
   `40-runtime-config.sh`，保留脚本执行权限、缓存目录属主、端口、健康检查和启动命令。
4. 按上述文件名导出到 `deploy-all/images/`，覆盖旧包，并核对归档中的镜像架构。

2026-11-25 的交付采用此方式：AMD64 按原 Dockerfile 完整构建，
ARM64 复用该次构建的同一份静态资源，使用 ARM64 nginx 运行时，避免在模拟环境
重复编译前端。
两个架构均已验证镜像可加载、nginx 可启动、`/health` 和首页可访问。
此替代方式无需修改仓库原有 Dockerfile。

### 上传到镜像包文件服务器

当前约定的文件服务器为 `tudan@192.168.112.51`，SSH 端口 `60022`。
目标根目录为 `/vol2/1000/docker2/apps/dufs/data/inoe-agent`：

| 架构 | 本地文件 | 服务器目标文件（相对于目标根目录） |
|------|----------|----------------------------------|
| amd64 | `deploy-all/images/digital-workforce-portal-amd64.tar.gz` | `amd64/digital-workforce-portal-amd64.tar.gz` |
| arm64 | `deploy-all/images/digital-workforce-portal-arm64.tar.gz` | `arm64/digital-workforce-portal-arm64.tar.gz` |

上传前确认目录存在、可写且空间充足。使用 SSH 密钥或交互式输入密码，
**不要把密码写入文档、脚本或提交记录**。
以下命令在项目根目录执行；先上传临时文件，远程校验后再覆盖同名旧包，
避免下载到未传完的文件。

```bash
set -euo pipefail
REMOTE=tudan@192.168.112.51
BASE=/vol2/1000/docker2/apps/dufs/data/inoe-agent

ssh -p 60022 "$REMOTE" \
  "ls -ld '$BASE/amd64' '$BASE/arm64' && df -h '$BASE'"

for ARCH in amd64 arm64; do
  FILE="digital-workforce-portal-$ARCH.tar.gz"
  HASH=$(shasum -a 256 "deploy-all/images/$FILE" | awk '{print $1}')
  scp -P 60022 "deploy-all/images/$FILE" \
    "$REMOTE:$BASE/$ARCH/$FILE.uploading"
  ssh -p 60022 "$REMOTE" \
    "cd '$BASE/$ARCH' &&
     printf '%s  %s\n' '$HASH' '$FILE.uploading' | sha256sum -c - &&
     gzip -t '$FILE.uploading' &&
     chmod 644 '$FILE.uploading' &&
     mv -f '$FILE.uploading' '$FILE'"
done
```

上传后核对两个远程文件的 SHA-256 与本地一致。这里只交付镜像包，
不自动在服务器导入镜像、重启服务或执行部署。

### 在目标设备导入

选择与目标设备 CPU 架构一致的镜像包：

```bash
# Docker（示例为 amd64）
docker load -i digital-workforce-portal-amd64.tar.gz

# k3s/containerd：不要使用 docker load 代替集群运行时导入
gzip -dc digital-workforce-portal-amd64.tar.gz | sudo k3s ctr images import -
```

## Docker Compose 部署

```bash
cd deploy-all/portal
docker-compose up -d
```

可通过环境变量覆盖 Portal 展示名称：

```bash
PORTAL_APP_TITLE="数字员工门户" docker compose up -d
```

## Helm 部署 (k3s)

```bash
# 打包
helm package ./digital-workforce-portal

# 安装
helm install digital-workforce-portal ./digital-workforce-portal-1.0.0.tgz
helm install digital-workforce-portal ./deploy-all/portal/helm/digital-workforce-portal

# 升级
helm upgrade digital-workforce-portal ./deploy-all/portal/helm/digital-workforce-portal

# 卸载
helm uninstall digital-workforce-portal
```

## 配置说明

### 镜像配置 (values.yaml)

```yaml
image:
  repository: digital-workforce-portal
  tag: 0.1.0
  pullPolicy: IfNotPresent
```

### 服务配置

```yaml
service:
  type: NodePort
  port: 80
  targetPort: 80
  nodePort: 30083
```

访问地址：`http://<node-ip>:30083`

### 自定义配置

创建自定义 values 文件：

```bash
helm install digital-workforce-portal ./deploy-all/portal/helm/digital-workforce-portal -f my-values.yaml
```

可配置项示例：

```yaml
env:
  TZ: Asia/Shanghai
  PORTAL_APP_TITLE: 数字员工门户
```
