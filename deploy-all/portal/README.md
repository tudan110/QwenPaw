# Digital Workforce Portal 部署说明

Portal 前端项目的容器化部署配置，支持 Docker 和 Kubernetes (k3s) 部署。

## 目录结构

```
deploy-all/portal/
├── Dockerfile              # 多阶段构建配置
├── docker-compose.yml      # Docker Compose 部署配置
├── nginx.conf              # Nginx 配置文件
├── build-arm.sh            # ARM64 版本构建脚本
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

在项目根目录执行：

```bash
docker build -f deploy-all/portal/Dockerfile -t digital-workforce-portal:0.1.0 .
```

### ARM64 版本构建

用于 ARM 架构设备（如树莓派、AWS Graviton 等）：

```bash
cd deploy-all/portal
./build-arm.sh
```

导出镜像用于传输：

```bash
docker save -o digital-workforce-portal-arm64.tar digital-workforce-portal:0.1.0
```

在目标设备上加载：

```bash
docker load -i digital-workforce-portal-arm64.tar
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

### 验证对话续写的流式输出

Portal 默认通过 `/copaw-api/api/console/chat/continue` 将续写请求转给 QwenPaw。后端先把模型增量拼成累积正文，再通过 SSE 发送；Portal 用每个累积快照替换同一条回复。若正文在生成中反复变短、最后才跳到全文，应先核对实际运行的 **QwenPaw** 是否包含 `448be0d46`（或后续版本中的等效修复），而不是只更新 Portal 或清理浏览器缓存。若直连后端有连续的累积帧、经过 Portal 却被批量送达，再排查 Nginx 及其他代理的 SSE 缓冲。

对于使用项目默认命名的 Helm 环境，在目标集群上查询实际 Pod 镜像及摘要（不是只看部署模板里的 tag）：

```bash
kubectl -n cnos-iomp get pods \
  -l 'app.kubernetes.io/name in (qwenpaw,digital-workforce-portal)' \
  -o 'custom-columns=POD:.metadata.name,IMAGE:.status.containerStatuses[*].image,IMAGE_ID:.status.containerStatuses[*].imageID'
```

用发布记录将 `IMAGE_ID` 对应到源码提交。如果镜像没有源码提交记录，可以直接对实际处理请求的 QwenPaw Pod 核对安装文件的内容指纹。以下命令在已确认的目标集群上下文执行，将 `POD` 设为实际的 QwenPaw Pod 名称；后端应与**待部署版本**的源文件哈希相同：

```bash
# 本地，在待发布版本的源码目录
python -c 'from pathlib import Path; from hashlib import sha256; print(sha256(Path("src/qwenpaw/app/chats/text_continuation.py").read_text(encoding="utf-8").encode()).hexdigest())'
# 目标集群，运行中的后端容器
POD=实际的QwenPawPod名称
kubectl -n cnos-iomp exec "$POD" -c qwenpaw -- /app/venv/bin/python -c 'from pathlib import Path; from importlib.metadata import distribution; from hashlib import sha256; p=Path(distribution("qwenpaw").locate_file("qwenpaw/app/chats/text_continuation.py")); print(sha256(p.read_text(encoding="utf-8").encode()).hexdigest())'
```

部署后端续写修复与 Portal 的 Nginx 防缓冲配置时，分别检查对应镜像。`IfNotPresent` 下应使用新的不可变标签或摘要，不能指望覆盖同一个 tag 后 Pod 自动使用新内容。

用一段不含业务信息的合成长文验证「开始生成 → 停止 → 继续生成」。在 `status: completed` **之前**，原回复应保持已有前缀，新增正文至少连续增长三次；完成后刷新，同一条回复仍应显示完整正文。若实时正文已增长但最后出现「服务暂时遇到点问题」，不要把它计为通过：请按同一测试时间检查 QwenPaw 服务日志，区分模型流报错和续写保存失败。
