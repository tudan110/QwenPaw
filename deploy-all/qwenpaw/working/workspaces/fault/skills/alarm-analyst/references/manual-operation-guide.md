# 基于实际部署环境的人工处置指南

## 当前边界与选择规则

系统只用 CMDB 已返回的关系和字段定位部署，不自行 SSH、执行 Kubernetes 命令或登录数据库。已有告警、指标和知识查询照常；这些数据不证明登录、Pod 当前状态或命令执行成功。

交付时需同时更新 Python 扩展包、运行工作区规则/skill 和 Portal。告警聚合脚本使用包内 `extensions/api/cmdb_manual_guidance.py`；只向旧版本镜像同步新 skill 不足以启用本功能。本地源代码改动不代表运行工作目录已同步或服务已重启。

先确认根实例、明确承载关系和部署字段。`deploy` 实例链或明确部署字段可支持选择路径；业务 `contain/connect`、同 IP、名称相似或仅出现相关集群不能证明部署。K3s/Kubernetes、裸 Docker、主机/托管数据库分开给建议，不将 K3s 命令套到所有数据库。

命名空间、Pod、容器、端口等只能绑定本次 CMDB 已确认值。多个候选、字段冲突或没有字段时保留待现场确认，不默认 `default/mysql-0/root/3306`。集群名不是 kubeconfig context，容器节点名不是 Pod 名。

账号由运维在自己的授权环境中选择和填写，不回显或复用 CMDB login_user，即使它是 root；密码自行交互输入，不要求提交给 AI。不从 CMDB、文档或配置提取登录 token/密码来拼命令。

首轮处置必须从 Step 0 给出实际操作位置和进入方法，不能只在环境表提到部署或在流程图写“确认环境”。禁止系统远程登录不等于禁止向运维提供人工 SSH、kubectl、mysql 命令。宿主阈值告警和配置容量只是待核验线索，不能直接写成慢 SQL 根因或资源耗尽。

## MySQL 部署于 K3s/Kubernetes：完整路径

以下是人工模板，不是已执行证据；仅在 CMDB 已确认对应部署后使用。占位符未填写时不得复制执行。

0. **进入实际管理环境**：已有授权 kubeconfig 的终端可直接操作，无需 SSH。若现场流程要求从服务器操作，先核对管理机角色、已有权限和 CLI，再由运维执行下面的模板；部署宿主机不自动等于控制平面，不默认 host-1 或数据库 IP 就是管理机。

   ```bash
   SSH_TARGET='<现场确认的已授权管理机地址>'
   SSH_USER='<运维在本地填写的账号，不提交给 AI>'
   ssh "${SSH_USER}@${SSH_TARGET}"
   ```

   不输出或读取 kubeconfig、私钥、密码内容。若选择服务器路径，登录后再在该服务器设置下面的变量；不能在本机设变量后假定远端自动继承。

1. **授权环境与参数准备**：由运维使用现有授权管理入口，核对集群/目标 CI；系统不获取 SSH 登录信息。

   ```bash
   KUBE_CONTEXT='<现场核对的已有 context>'
   NAMESPACE='<CMDB 已确认或现场核对的 Namespace>'
   MYSQL_POD='<确认属于目标实例的 Pod>'
   MYSQL_CONTAINER='<目标 MySQL 容器>'
   DB_PORT='<现场核验的容器内 MySQL 监听端口>'
   DB_USER='<运维本地填写，不要求提交给 AI>'
   ```

2. **定位当前 Pod 和容器**：确认集群、Namespace、工作负载与主库/副本角色，多个候选先核验，不取第一条。

   ```bash
   kubectl config get-contexts
   kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" get pods -o wide
   kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" get pod "$MYSQL_POD" -o jsonpath='{.spec.containers[*].name}'
   ```

   只有现场确认该管理机角色、现有权限及 CLI 后，才可用 `sudo k3s kubectl` 替换 kubectl 前缀；不能默认每个工作节点都有管理 kubeconfig，也不向 AI 提供 sudo/SSH 密码。上述命令由运维人工执行，不能写成系统已核验。

   CMDB `db_ip/db_port` 可能记录 Service/NodePort/宿主映射入口。即使入口为 `10.2.0.15:30306`，也不能据此填成容器内 `127.0.0.1:30306`；只有明确的 `db_listen_port/container_port` 或现场监听配置才支持绑定内部端口，不默认 3306。

3. **容器内访问 MySQL**：确认镜像有客户端、目标及端口正确。

   ```bash
   kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" exec -it "$MYSQL_POD" -c "$MYSQL_CONTAINER" -- mysql --host=127.0.0.1 --port="$DB_PORT" --user="$DB_USER" --password
   ```

   密码只在本地提示中输入。容器无客户端时不默认创建调试 Pod；由运维选择已有授权客户端，只有 Service/端口已确认时才给对应连接/转发方案。

4. **数据库身份及只读排查**：先核对版本、实例和角色，再选择适用语句；权限不足保留缺口。

   ```sql
   SELECT @@hostname, @@port, @@version, @@read_only;
   SHOW FULL PROCESSLIST;
   SHOW VARIABLES WHERE Variable_name IN ('performance_schema', 'slow_query_log', 'long_query_time', 'log_output');
   ```

   已确认 performance_schema 启用、表可用且有权限后再看慢 SQL 摘要：

   ```sql
   SELECT SCHEMA_NAME, DIGEST_TEXT, COUNT_STAR,
          SUM_TIMER_WAIT / 1000000000000 AS total_seconds,
          AVG_TIMER_WAIT / 1000000000000 AS avg_seconds
   FROM performance_schema.events_statements_summary_by_digest
   ORDER BY SUM_TIMER_WAIT DESC LIMIT 10;
   ```

   锁等待区分 MySQL 8 的 `performance_schema.data_lock_waits` 与 MySQL 5.7 的 `information_schema.INNODB_LOCK_WAITS`。不要盲目同时运行；不能为排查直接开启日志或修改参数。目标 SQL/库名现场确认后做 EXPLAIN，不用会实际运行查询的 EXPLAIN ANALYZE 代替。

5. **按证据处置，需人工确认审批后执行**：慢 SQL 计数高不证明缺索引，也不默认终止查询。确认具体 SQL、当前会话、阻塞链、事务、主从角色、业务影响及预案。

   ```sql
   KILL QUERY <现场重新核验的会话ID>;
   ```

   此命令仅是条件性模板，不能给未核验 ID 或批量执行。KILL QUERY 不一定释放整个事务/锁；结束连接可能造成事务回滚。索引/配置变更、重启或切库分别核验窗口、备份、风险和回退；不知道实际表/列时不给虚构 DDL。

6. **恢复验证与后续修复**：运维复查会话、锁等待、慢 SQL 摘要和延迟，核对工作负载状态并测试业务请求。按实际变更记录回退配置/SQL 变更，不承诺 KILL 可恢复原事务。告警消失、通知成功或 Pod Running 不能单独证明业务已恢复。

## 裸 Docker 与主机/托管环境

- 裸 Docker：运维先在已授权宿主环境核对 `docker ps`、目标容器，再使用 `docker exec -it "$MYSQL_DOCKER_CONTAINER" mysql ... --password`；参数来自对应 CMDB 实例，不从相关 K3s 集群借值。
- 主机/托管数据库：运维使用已有授权入口或客户端，用已确认地址/端口执行 `mysql --host="$DB_HOST" --port="$DB_PORT" --user="$DB_USER" --password`，不由 AI 建立 SSH 或索要账号密码。
- 数据库内身份、排查、审批及验证步骤同样保留；部署未知时先给确认路径，不假称已匹配环境。
- Redis、PostgreSQL、应用等使用对应组件 SOP，不套 MySQL SQL。访问准备与人工边界通用。

## 输出和完整性

先明确“CMDB 已知部署事实”“未确认参数”和“操作执行位置”，再按依赖顺序给完整人工命令。扁平/详细模式仅控制组织方式，不删访问、登录、排查、风险或验证步骤。

每条编号建议保留完整多行代码块、前提和风险，不能只给内部 `python .../skill脚本` 调用。字段不全时给获取/核验步骤或待绑定模板，不能标“直接复制即可执行”。

根因证据完整性、CMDB 查询范围完整性和操作参数完整性分别说明；不因账号不提供就否定已有根因证据。建议默认未执行，不生成 SSH/Kubernetes/MySQL 自动 action；已有平台业务接口按原权限和审批，不扩大执行能力。
