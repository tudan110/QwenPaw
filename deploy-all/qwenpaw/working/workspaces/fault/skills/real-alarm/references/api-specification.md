# API 规范

本文档描述 `real-alarm` 技能的唯一查询入口、参数、分页策略和错误处理约定。

## 推荐入口

### 1. 原始查询入口

统一执行：

```bash
uv run scripts/get_alarms.py [options]
```

适用于：

- 只查原始分页数据
- 需要精确控制页码和页大小
- 需要指定时间范围查询

### 2. 统一汇总入口

```bash
uv run scripts/analyze_alarms.py --mode <mode> [options]
```

适用于：

- 综合概览
- 级别 / 标题 / 设备 / 专业 / 区域分布
- 严重告警清单
- 关键字搜索

如果结果要直接回到聊天窗口，推荐：

```bash
uv run scripts/analyze_alarms.py --mode summary --output markdown
```

`markdown` 输出特性：

- 自动生成适合聊天窗口的标题、摘要和表格
- 自动补充简短分析结论
- 分布类模式自动附带 ECharts 配置代码块
- `severity` 默认环形图，`title` / `device` 默认柱状图
- 告警明细默认只展示前 20 条，并补充总数说明

如果只需要图表代码块，可使用：

```bash
uv run scripts/analyze_alarms.py --mode summary --output markdown-echarts-only
```

适用场景：

- 前端只想渲染图表
- 不需要文字摘要和表格
- 需要把图表块嵌入其他响应内容

不要要求用户自行调用 HTTP API。

## 参数说明

### get_alarms.py 参数

| 参数名称 | 类型 | 是否必填 | 说明 | 示例 |
|---------|------|---------|------|------|
| `page_num` | int | 否 | 页码，默认 `1` | `1` |
| `page_size` | int | 否 | 每页数量，默认 `10` | `10`, `100`, `1000` |
| `token` | str | 否 | JWT 令牌；默认从环境变量 `INOE_API_TOKEN` 读取 | `eyJ...` |
| `api_base_url` | str | 否 | API 基础地址；默认从环境变量 `INOE_API_BASE_URL` 读取 | `http://host:port` |
| `begin_time` | str | 否 | 开始时间，格式 `YYYY-MM-DD HH:MM:SS` | `2026-03-15 10:00:00` |
| `end_time` | str | 否 | 结束时间，格式 `YYYY-MM-DD HH:MM:SS` | `2026-03-16 10:00:00` |
| `alarm_severitys` | list | 否 | 告警级别列表，如 `["1", "2"]` | `1 2` |
| `alarm_status` | str | 否 | 告警状态，`1` 表示活跃 | `1` |
| `dev_name` | str | 否 | 设备名称 | `SN-XA-LHL-A.Leaf-4` |
| `manage_ip` | str | 否 | 管理IP | `4.155.10.35` |
| `cities` | list | 否 | 城市列表 | `南京 秦淮区` |
| `alarm_title` | str | 否 | 告警标题 | `端口DOWN` |

### analyze_alarms.py 参数

| 参数名称 | 类型 | 是否必填 | 说明 | 示例 |
|---------|------|---------|------|------|
| `mode` | str | 否 | 分析模式，默认 `summary` | `summary`, `severity`, `title`, `device`, `speciality`, `search` |
| `keyword` | str | 否 | 搜索关键字 | `端口` |
| `keyword_field` | str | 否 | 关键字搜索字段，默认 `all` | `all`, `alarmtitle`, `devName`, `manageIp`, `speciality`, `alarmregion` |
| `severity` | str | 否 | 按告警级别过滤 | `1` |
| `device_name` | str | 否 | 按设备名称过滤 | `SN-XA-LHL-A.Leaf-4` |
| `manage_ip` | str | 否 | 按管理IP过滤 | `4.155.10.35` |
| `speciality` | str | 否 | 按专业过滤 | `IPM` |
| `region` | str | 否 | 按区域过滤 | `XA` |
| `begin_time` | str | 否 | 开始时间，格式 `YYYY-MM-DD HH:MM:SS` | `2026-03-15 10:00:00` |
| `end_time` | str | 否 | 结束时间，格式 `YYYY-MM-DD HH:MM:SS` | `2026-03-16 10:00:00` |
| `alarm_severitys` | list | 否 | 告警级别列表 | `1 2` |
| `alarm_status` | str | 否 | 告警状态 | `1` |
| `cities` | list | 否 | 城市列表 | `南京 秦淮区` |
| `fetch_page_size` | int | 否 | 抓取全量告警时的分页大小，默认 `100` | `100` |
| `top_n` | int | 否 | 分组结果或预览告警数量，默认 `10` | `10`, `20` |
| `include-alarms` | flag | 否 | 输出完整告警预览列表 | - |
| `output` | str | 否 | 输出格式，默认 `json` | `json`, `markdown`, `markdown-echarts-only` |

## 配置

技能目录下的 `.env`：

```bash
#INOE_API_BASE_URL=http://192.168.130.211:30080
INOE_API_TOKEN=your_jwt_token_here
```

配置文件位置：`.claude/skills/real-alarm/.env`

读取优先级：

1. 技能目录 `.env`
2. 项目根目录 `.env`

## 接口信息

- 请求方式：`POST`
- 接口地址：`{INOE_API_BASE_URL}/resource/realalarm/list`
- 鉴权方式：`Authorization: Bearer <token>`
- 请求体：JSON 格式，包含分页参数和筛选条件

## 告警级别说明

| 级别 | 名称 | 说明 |
|------|------|------|
| 1 | 严重 | 需要立即处理的严重故障 |
| 2 | 重要 | 重要告警，需要关注 |
| 3 | 一般 | 一般性告警 |
| 4 | 提示 | 提示性信息 |

## 告警状态说明

| 状态 | 名称 | 说明 |
|------|------|------|
| 0 | 自动清除 | 网元自动清除的告警 |
| 1 | 活跃 | 告警未清除，持续中 |
| 2 | 同步清除 | 同步清除的告警 |
| 3 | 手工清除 | 手工清除的告警 |

## 告警类别说明

| 类别 | 名称 | 说明 |
|------|------|------|
| sys_log | 设备告警 | 设备相关告警 |
| threshold | 性能告警 | 性能指标告警 |
| derivative | 衍生告警 | 衍生告警 |

## 推荐执行策略

### 场景 1：只查总数

```bash
uv run scripts/get_alarms.py --page_num 1 --page_size 1
```

读取响应中的 `total`。

### 场景 2：简单列表

```bash
uv run scripts/get_alarms.py --page_num 1 --page_size 10
```

适合"列出告警""看前几条告警"。

### 场景 3：查询指定时间范围

```bash
uv run scripts/get_alarms.py --begin_time "2026-03-15 10:00:00" --end_time "2026-03-16 10:00:00"
```

### 场景 4：统计 / 分布 / 筛选 / 综合分析

优先使用：

```bash
uv run scripts/analyze_alarms.py --mode summary --output markdown
uv run scripts/analyze_alarms.py --mode severity --output markdown
uv run scripts/analyze_alarms.py --mode device --output markdown
uv run scripts/analyze_alarms.py --mode search --severity 1 --include-alarms --output markdown
```

`analyze_alarms.py` 会自动分页抓取全部告警，再做本地汇总。

如果必须手动取数，再先取总数，再决定是否全量拉取：

- 若 `total <= 100`：一次性拉取
- 若 `total > 100`：分页拉取，每页 `100`

示例：

```bash
uv run scripts/get_alarms.py --page_num 1 --page_size 1
uv run scripts/get_alarms.py --page_num 1 --page_size 100
uv run scripts/get_alarms.py --page_num 2 --page_size 100
```

## 分页约定

- 统计或筛选前，应确认数据是否全量获取
- 某页失败时，不要把不完整数据当成完整统计结果
- 若分页中断，应明确说明"已获取 X/Y 页，结果可能不完整"

## 成功与失败判断

- `code = 200`：成功
- 非 `200`：失败
- 命令退出码：成功返回 `0`，失败返回 `1`

## 常见错误

| 场景 | 典型表现 | 处理建议 |
|------|----------|----------|
| 缺少 token | 脚本直接报错退出 | 提示补充 `INOE_API_TOKEN` |
| 401 | 认证失败 | 提示 token 无效或过期 |
| 403 | 权限不足 | 提示当前账号无访问权限 |
| 404 | 接口不存在 | 检查 `INOE_API_BASE_URL` |
| 408 / Timeout | 请求超时 | 稍后重试，必要时减少单页数据量 |
| ConnectionError | 连接失败 | 检查网络或服务地址 |
| 时间格式错误 | 提示时间格式无效 | 确保格式为 `YYYY-MM-DD HH:MM:SS` |

## Agent 回复要求

- 不要只返回"命令执行成功"
- 不要原样输出整段 JSON，除非用户明确要求原始结果
- 应从 `total` 和 `rows` 中提炼用户真正需要的结论
- 统计类问题优先使用 `analyze_alarms.py` 的结果，而不是手动重复聚合
- 聊天场景优先使用 `--output markdown`
- 告警级别应转换为可读名称（严重/重要/一般/提示）
- 告警状态应转换为可读名称（活跃/已清除）