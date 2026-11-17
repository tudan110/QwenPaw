# 信通院整改归档，未批准发布

2026-11-17 按用户要求撤回本批信通院能力检验整改，改为后续逐项审核。此目录中的代码、补丁、镜像、Chart 和配置仅供审阅与恢复，不是可直接部署的版本。

## 保存的版本

- 整改前基线：`cf77202f94df408c2e6e7dee18c5b32eccd85706`。
- 归档分支：`codex/archive-caiict-remediation-20261117`，指向 `1b15a083735c52b5a67d286acfb06574d6c4df44`。
- 本次撤销：`af157e929`（代码和部署默认值）、`8d50873af`（Excel 已修改进展）、`1b15a0837`（配套 Helm 转义修复及打包文件）。
- 原始评估、执行方案和整改前的 15 项 Excel 保留，用于后续逐项审核。

## 本地恢复材料

| 路径 | 内容 |
| --- | --- |
| `manifest.json` | 原始提交、64 个撤回路径、无关工作区文件摘要、归档文件摘要及产物原路径 |
| `remediation-commits.bundle` | 三个提交的 Git bundle；需要已有基线 `cf77202f9`，已执行 bundle verify |
| `remediation-files.tar.gz` | 被修改文件在归档版本下的完整快照，可独立解压阅读 |
| `patches/` | 三个提交的原始 binary/full-index 补丁，包含二进制文件变化 |
| `release-candidate/` | 原 `outputs/release-20261116-81/`，包括当时的镜像、Chart、候选规则和说明，原样移入 |
| `build-artifacts/` | 撤回前的 Console 构建结果和已打包静态文件 |
| `workspace-before/` | 撤回前其他未提交工作区差异，仅作误操作恢复备份 |
| `review-materials/` | 可直接查看的撤回前实施记录、带修改进展的 Excel 历史快照；其中内容不代表当前已生效 |
| `verification.json` | 文件基线、归档完整性、回归与构建验证结果 |

大型恢复材料由本目录 `.gitignore` 排除，文件仍保存在本机；归档分支也保留完整提交。这些本地备份未推送或上传。

## 后续审核切分

| 功能 | 审核重点及主要文件 |
| --- | --- |
| 工具/MCP 准入 | `execution_policy.py`、`mcp_boundary.py`、`tool_registry.py`；先核对当前实际业务工具和端点 |
| 高风险审批 | `operation_intent.py`、approvals、`tool_adapter.py`；参数绑定、过期、单次消费及现有业务兼容 |
| 任务控制 | `execution_control.py`、TaskTracker、runtime、管理路由与 UI；停止语义、持久状态和异常恢复 |
| 输出防护 | output_guard 和 HTTP 输出边界；保留正常流式体验、跨片段检测、故障处理与体积边界 |
| 外联控制 | `egress_policy.py`、MCP/模型/业务客户端；真实规则迁移、TLS、DNS、重定向及代理兼容 |
| 审计 | audit、forwarder 和 trace；持久队列、归档依赖、容量、故障策略和版本恢复 |
| 组件/验收工具 | component_inventory、run_acceptance；使用范围、金标、指标和原始证据 |
| 部署 | values、deployment 和打包 Chart；资源差异、共享 release、不可变镜像及恢复演练 |

这些功能在原提交中存在交叉依赖，尤其 `tool_adapter.py`、应用装配、审计与外联。上述表格是审核顺序，不代表已有可独立发布的补丁。后续应从撤回后的分支按经审核的范围拆分、补测，再构建独立发布包。

本次只撤回本地源代码、配置和交付产物。未操作 81，未执行 Helm 回滚，未改生产数据或凭据，未清理本机容器镜像缓存。未来发布必须从审核后的源代码重新构建并固定镜像 digest，不能复用本归档镜像或仅凭本机 `latest` 标签选择镜像。

## 撤回验证

- 全部 64 个撤回路径与整改前基线逐文件核对一致；原有 4 个未提交文件的 SHA-256 均保持不变。
- bundle 验证通过，完整文件快照逐文件匹配归档分支，三个原始补丁通过只读 `git apply --check`。
- 原发布候选目录中的 Chart、Portal 镜像包、后端镜像包共 3 项原 SHA256SUMS 校验通过。
- 后端定向回归 556 项通过；Console 3 个文件共 20 项测试通过，构建通过。保留既有 audioop 弃用及前端分包提示。
- Console 构建目录和应用打包静态目录已重建为撤回后版本，核对不再包含本批新增的执行控制入口。
- 上述均为本地验证，不代替 81 现场业务验收。
