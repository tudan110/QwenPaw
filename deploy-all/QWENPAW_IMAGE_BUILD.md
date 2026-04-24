# QwenPaw 镜像打包说明

本文档说明如何基于 `deploy-all/qwenpaw/Dockerfile` 打包 QwenPaw 镜像。

## 先决条件

在执行 Docker 打包前，**必须先完成下面两个同步步骤**：

1. 执行仓库根目录的 `sync-qwenpaw-working.sh`，将 `deploy-all/qwenpaw/working` 同步到本地用户目录
2. 再按照 `deploy-all/SYNC_GUIDE.md`，将本地用户目录下的数据同步到 `deploy-all/qwenpaw/data`

只有这两步完成后，才能使用 `deploy-all/qwenpaw/Dockerfile` 正确打包。

## 为什么必须按这个顺序执行

`deploy-all/qwenpaw/Dockerfile` 在构建阶段会直接把以下内容复制进镜像：

- `deploy-all/qwenpaw/data/qwenpaw/`
- `deploy-all/qwenpaw/data/qwenpaw.secret/`
- `deploy-all/qwenpaw/working/workspaces/*/skills`

这意味着：

- `deploy-all/qwenpaw/working` 是工作区技能源码来源
- `deploy-all/qwenpaw/data` 是最终要进入镜像的工作目录数据来源

如果跳过同步步骤，镜像里会带上**旧数据、缺失数据或本地未更新的数据**。

## 标准打包流程

### 第 1 步：同步工作目录到本地用户目录

在仓库根目录执行：

```bash
./sync-qwenpaw-working.sh
```

默认会同步到：

```bash
~/.qwenpaw
```

如果希望严格镜像同步，可使用：

```bash
./sync-qwenpaw-working.sh --delete
```

> 这一步的目标是先把 `deploy-all/qwenpaw/working` 中维护的工作区内容同步到本地用户目录。

### 第 2 步：把本地用户目录同步到 deploy-all/qwenpaw/data

然后按 `deploy-all/SYNC_GUIDE.md` 执行同步，将本地目录中的数据整理并复制到：

- `deploy-all/qwenpaw/data/qwenpaw/`
- `deploy-all/qwenpaw/data/qwenpaw.secret/`

重点是把以下本地目录同步进去：

- `~/.qwenpaw/` → `deploy-all/qwenpaw/data/qwenpaw/`
- `~/.qwenpaw.secret/` → `deploy-all/qwenpaw/data/qwenpaw.secret/`

请直接参考：

```bash
deploy-all/SYNC_GUIDE.md
```

> 这一步完成后，`deploy-all/qwenpaw/data` 才是 Docker 打包时真正使用的数据源。

### 第 3 步：确认打包输入目录

打包前建议至少确认下面目录存在且内容已更新：

```bash
deploy-all/qwenpaw/data/qwenpaw
deploy-all/qwenpaw/data/qwenpaw.secret
deploy-all/qwenpaw/working/workspaces
```

### 第 4 步：使用 Dockerfile 打包

在项目根目录执行：

```bash
docker build -f deploy-all/qwenpaw/Dockerfile -t qwenpaw:latest .
```

## 使用构建脚本

如果需要按架构构建，也可以直接使用 `deploy-all/qwenpaw` 下的脚本。

### AMD64

```bash
cd deploy-all/qwenpaw
./build-amd64.sh
```

### ARM64

```bash
cd deploy-all/qwenpaw
./build-arm64.sh
```

## 推荐执行顺序

```bash
# 1. 从仓库工作目录同步到本地用户目录
./sync-qwenpaw-working.sh

# 2. 按指南把 ~/.qwenpaw 和 ~/.qwenpaw.secret 同步到 deploy-all/qwenpaw/data
#    具体操作见 deploy-all/SYNC_GUIDE.md

# 3. 使用 Dockerfile 打包
docker build -f deploy-all/qwenpaw/Dockerfile -t qwenpaw:latest .
```

## 常见错误

### 直接打包，没有先同步 working

后果：本地用户目录里的工作区内容不是最新，后续同步到 `deploy-all/qwenpaw/data` 的也是旧版本。

### 只执行了 sync-qwenpaw-working.sh，没有同步到 deploy-all/qwenpaw/data

后果：Dockerfile 仍然会读取 `deploy-all/qwenpaw/data` 的旧数据，镜像内容不会更新。

### data 已同步，但 working/workspaces 下的技能没有更新

后果：镜像里的工作区技能和 data 中的数据可能不一致。

## 结论

打包 QwenPaw 镜像时，正确顺序必须是：

1. `sync-qwenpaw-working.sh`
2. 按 `deploy-all/SYNC_GUIDE.md` 同步本地用户目录到 `deploy-all/qwenpaw/data`
3. 使用 `deploy-all/qwenpaw/Dockerfile` 打包
