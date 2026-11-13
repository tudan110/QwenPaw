# QwenPaw 通用镜像打包说明

本文档说明如何基于 [`qwenpaw/Dockerfile`](qwenpaw/Dockerfile) 构建**跨环境通用**的 QwenPaw 镜像。

## 核心原则

通用镜像只包含：

- QwenPaw 程序与离线运行依赖；
- 仓库维护的 Agent、Skill 和初始化模板；
- 构建期生成的无环境工作目录 seed。

通用镜像不包含：

- `deploy-all/qwenpaw/data/qwenpaw/` 运行时快照；
- `~/.qwenpaw` 中的设置数据库、知识库、会话和报告；
- 知识库数据库、上传文件、会话、缓存和环境专属服务数据。

> **凭据不随镜像交付**：`qwenpaw.secret/`、`.master_key` 和运行时快照均排除在构建上下文之外。Provider 配置、主密钥和 INOE Token 必须由目标环境单独配置；空 secret 目录不会再从镜像恢复模型。旧镜像/代码曾包含的凭据应撤销并轮换，删除新的 `COPY` 并不能清除旧镜像层、tar 或 Git 历史。

## 唯一维护源

受管的 Agent/Skill 维护在：

```text
deploy-all/qwenpaw/working/
├── config.json
├── universal-seed.json
└── workspaces/
    └── <agent-id>/
        ├── agent.json
        ├── skill.json
        └── skills/
```

其中：

- `workspaces/*/skills/` 是 Skill 代码唯一维护源；
- `skill.json` 决定 Skill 是否启用、适用渠道及配置元数据；
- `universal-seed.json` 声明废弃 Skill 和跨工作区复用的源码；
- 不再需要将 `working`、本机用户目录或 Skill 手工同步到 `deploy-all/qwenpaw/data/` 后再打包。

构建时，`scripts/build_universal_seed.py` 会将这些输入生成到镜像的：

```text
/app/share/qwenpaw-seed/
```

并完成：

1. 将本机 workspace 路径规范化为 `/app/working/workspaces/<agent-id>`；
2. 根据 manifest 物化缺失的 builtin Skill；
3. 仅过滤真实 `.env`、明确的凭据字段和生成缓存；`working` 中维护的其他文件都会保留；
4. 生成空的 `jobs.json` 与 seed 内容哈希；
5. 拒绝没有受管源码的有效 Skill，避免隐性依赖 data 快照。

## 打包前检查

打包前只需维护并检查 repository source：

```bash
python3 deploy-all/qwenpaw/scripts/build_universal_seed.py \
  --source deploy-all/qwenpaw/working \
  --builtin-root src/qwenpaw/agents/skills \
  --output .seed-check/qwenpaw-universal-seed \
  --runtime-working-dir /app/working
```

成功后可以检查输出内容：

```bash
find .seed-check/qwenpaw-universal-seed -type f | sort
```

临时目录可在检查后删除。该命令不会读取或改写 `~/.qwenpaw`、`data/` 或任何运行环境。

## 构建镜像

在仓库根目录执行：

```bash
docker build -f deploy-all/qwenpaw/Dockerfile -t qwenpaw:latest .
```

按架构构建时使用现有脚本：

```bash
cd deploy-all/qwenpaw && ./build-amd64.sh
```

```bash
cd deploy-all/qwenpaw && ./build-arm64.sh
```

同一版本的 amd64 与 arm64 镜像必须使用相同镜像 tag；导出的 tar 文件名可用架构区分。

## 首次运行行为

容器发现工作目录为空时，会把 `/app/share/qwenpaw-seed/` 初始化到运行时工作目录。随后 QwenPaw 会按既有机制创建内置 `skill_pool`、默认 Agent 和 QA Agent。

现有 PVC 的受管 Agent/Skill 仍通过 initContainer 和 entrypoint 同步；用户 Skill、会话、设置和 secret 不会被该同步覆盖。空 secret 目录保持为空，直到操作员显式配置 Provider；基础本地检索不需要虚构模型或 INOE 凭据。

## 运行时数据与环境迁移

[`SYNC_GUIDE.md`](SYNC_GUIDE.md) 仅用于理解或迁移某个环境的运行时数据；它不是通用镜像构建步骤。运行时数据库、知识库文件、主密钥和环境专属凭据不得重新烘焙进通用镜像。

## 安全默认值与升级迁移（B/C P0）

- 安装阶段使用 root，最终镜像以 UID/GID `10001:10001` 运行。
- Helm 的主容器和两个 initContainer 使用同一非 root 身份，禁用提权、
  删除所有 capabilities，并继承 `RuntimeDefault` seccomp；根文件系统只读。
- 可写状态仅在 working、secret、backups 和 `/app/runtime`、`/tmp` 挂载内。
  Supervisor 输出到容器日志，配置/PID 位于 runtime，D-Bus 使用用户会话。
- `HOME`、`XDG_CACHE_HOME` 和 `TMPDIR` 在安装依赖后才切换到 runtime；
  构建阶段保留系统默认目录，避免安装脚本使用尚未创建的路径。
- 无凭据的静态 seed 在构建时统一赋予读取和目录遍历权限，避免维护源
  的本机文件权限导致非 root 容器无法初始化或同步 Skill。
- MCP SDK 固定为已验证的 `1.26.0`；2.x 使用 `httpx2`，与当前基于
  `httpx` 的受控传输客户端不兼容，不能在打包时自动跨大版本升级。
- PVC 根目录由存储驱动/kubelet 的 `fsGroup: 10001` 提供组访问；
  bootstrap 只创建目录，不使用 root、递归 chown 或 `chmod 777` 修复旧卷。
  若 CSI/NFS 不支持 fsGroup，须由存储管理员预置目录和权限。
- 后端 Service 默认 `ClusterIP`；Portal 同 release、同命名空间的 Pod
  可访问后端 8088。旧 NodePort 不再默认暴露。
- INOE Token 默认空；请求/设置/运行环境提供凭据后才能调用需要认证的接口。
  `QWENPAW_SSO_TOKEN_REQUIRED=true` 默认保留；首发管理权限由进程启动环境
  的 `QWENPAW_ADMIN_INOE_USER_IDS` 明确 allowlist 决定，Docker/Chart 默认 `"1"`，普通用户
  不会自动成为管理员。不能通过工作目录 `envs.json` 或设置页改变这些
  静态启动策略，也不要单独打开 `QWENPAW_AUTH_ENABLED` 创建旁路注册入口。
- Chart 的 `QWENPAW_INTERNAL_API_ORIGINS=http://qwenpaw:8088` 是可信内部
  API origin；更改 Service 名称/端口时必须同步修改，不配置通配地址。
  本地模型 adapter 的能力凭据由运行时生成在 secret DB，不作为 Chart
  默认密钥交付，也不由普通用户提供。

### 升级前必须完成

1. 确认目标环境，停止旧 Pod，并备份 PVC；Provider 密文和 `.master_key`
   必须成对备份/恢复，不能给已有密文生成不匹配的新主密钥。
2. 将旧卷整理为 `working/`、`secret/`、`backups/` 子目录；若旧卷直接将
   `config.json` 放在根目录，先迁移布局。通过受控的离线存储管理操作，
   将这三个目录及内容的所有者改为 `10001:10001`，secret 目录权限 `0700`、
   `.master_key` 为 `0600`，working/backups 为 `0750`。不改变共享卷的其他数据。
3. 目标环境显式创建 `qwenpaw-runtime-secrets`（或用 `envFrom` 指定自己的
   Secret）。默认 `optional: false`，不存在则 Pod 不启动；凭据不要放进
   Git、values 或镜像。已有 Provider 配置单独安全恢复到 `secret/`，或由
   授权操作员在启动后重新配置；不能从旧镜像自动复制。
   管理员 ID 列表通过目标 values 的 `env.QWENPAW_ADMIN_INOE_USER_IDS`
   显式设置（Chart 的显式 env 优先于 envFrom），不能靠 envs.json 提权。
   默认仅 ID `1` 获得管理权限；覆盖为 `""` 可拒绝全部管理/高危操作。
4. 仅需基础离线检索时可显式 `envFrom: []`，并根据本地检索需要选择
   `KNOWLEDGE_BASE_RERANKER: heuristic`、`KNOWLEDGE_BASE_HYDE_ENABLED: "false"`；
   不是要求全部部署禁用模型功能，也不绕过运行时的管理/高危鉴权。
5. 配置下面的网络放行规则；再用 `helm template` 检查目标 values，
   重新打包 umbrella Chart（`bash deploy-all/helm/package-cnos-inoe-agent.sh`），
   不要继续使用旧的 bundled tgz 或旧的秘密镜像。

### 目标环境网络放行

`networkPolicy.enabled` 默认 true。默认仅放行同 release Portal 入站和
kube-system 的 kube-dns TCP/UDP 53 出站；INOE、模型、MCP、审计、远程检索
均需按现场真实 Pod 标签/命名空间或精确 CIDR、端口显式配置。标准
NetworkPolicy **不支持域名白名单**，外部 LLM 动态地址应通过受控的固定
出口代理或支持 FQDN 策略的 CNI 管理，不能默认放行 `0.0.0.0/0`。

以下为 values 结构示意，标签、端口和文档专用 CIDR 必须替换成现场确认值：

```yaml
networkPolicy:
  egress:
    inoe:
      - to:
          - namespaceSelector:
              matchLabels:
                kubernetes.io/metadata.name: YOUR_INOE_NAMESPACE
            podSelector:
              matchLabels:
                YOUR_INOE_LABEL_KEY: YOUR_INOE_LABEL_VALUE
        ports:
          - protocol: TCP
            port: 8080 # 填 Pod 实际目标端口，而不是 NodePort
    model:
      - to:
          - ipBlock:
              cidr: 192.0.2.8/32 # 文档地址；填经确认的 LLM/出口代理地址
        ports:
          - protocol: TCP
            port: 443
    mcp: []       # 按同样 to + ports 结构填写必要对端
    audit: []
    retrieval: []
    additional: []
  ingress: []     # INOE 回调/另一个 release 的 Portal 等需显式对端 + 8088
```

一个 peer 内同时写 namespaceSelector 和 podSelector 表示 AND；不要拆成
两个 peers 意外允许整个 namespace。默认 DNS selector 可调整；NodeLocal
DNS、hostNetwork、Service DNAT 的 CIDR 行为依赖 CNI，须验证实际连接。
NetworkPolicy **只有在 CNI 支持并启用 enforcement 时才生效**；还要检查
其他策略，Kubernetes allow 规则会累加。必须验证允许对端可达、未授权
Pod 和未放行互联网地址不可达。`networkPolicy.enabled: false` 是显式操作员
例外，必须另有等效网络边界；本次静态/渲染测试不能证明现场 enforcement。

若确需后端 NodePort，显式设置 `service.type: NodePort` 和
`service.nodePort: 30088`，同时限制入口并保留鉴权；不要仅为旧烟测放宽网络。
禁用持久化或某个子目录时 Chart 使用 emptyDir，相关状态会在重建后丢失。
`containerSecurityContext.readOnlyRootFilesystem: false` 仅用于已评估的兼容例外，
不影响默认非 root、禁止提权和 capability 限制。

### 验证与回滚

发布前检查两个架构的最终镜像 `Config.User`、镜像层无 Provider/主密钥、
非 root 启动、PVC 写入、OCR/Xvfb、受管 Skill 同步、允许与拒绝网络路径。
单元测试和 `helm lint/template` 只能验证配置/脚本，不能替代实际镜像和 CNI
验证。Docker 直跑无 NetworkPolicy，需等效防火墙/受控出口，主机 bind mount
也须提前提供 UID/GID 10001 的目录权限。

回滚先暂停流量、保存失败现场和 PVC 备份，恢复匹配的密文/主密钥。
优先回滚应用版本而保留加固 Chart、Secret 和网络 values；若旧镜像只支持
root 或含历史凭据，不能直接恢复线上默认 root/NodePort/无限出网，需在隔离
维护环境验证修复。不要用删除策略、`chmod 777` 或把凭据重新烘焙进镜像
作为应急回滚方法。
