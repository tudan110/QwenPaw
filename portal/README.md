# Digital Workforce Portal

独立 React 前端，专门承接数字员工相关页面改动，不修改现有 `console` / `website` 代码。

## 启动

### 方式一：使用启动脚本（推荐）

```bash
# 在项目根目录执行
./start-portal.sh
```

启动脚本会自动检查并安装依赖。可通过环境变量自定义端口：

```bash
PORT=5173 ./start-portal.sh
```

也可以自定义 Portal 展示名称：

```bash
VITE_PORTAL_APP_TITLE="数字员工门户" ./start-portal.sh
```

### 方式二：手动启动

```bash
cd portal
pnpm install  # 首次需要安装依赖
pnpm dev
```

默认端口：`5173`

## 构建

```bash
pnpm build
```

构建时也支持自定义 Portal 展示名称：

```bash
VITE_PORTAL_APP_TITLE="数字员工门户" pnpm build
```

## 关键文件

- `src/pages/AgentCenterPage.jsx`: 主入口页
- `src/pages/DigitalEmployeePage.jsx`: 数字员工页
- `src/data/portalData.js`: 主入口与数字员工映射、静态演示数据
- `src/lib/conversationStore.js`: 历史会话本地存储

## 拓扑图呈现

故障影响卡片、资源导入预览、自监控和大屏拓扑共用
`src/components/topologyLayout.ts`，不再使用会持续移动的力导向布局。
单根、无环、每个节点至多一个父节点时，使用从左到右的 ECharts
`tree`；支持缩放、平移和点击展开/收起，默认展开全部层级。
根因颜色、节点大小和资源信息保持不变，关系说明可在子节点提示中查看。

多父关系、环路和多个独立分支使用固定坐标的分层 `graph`，保留所有实际
节点和连线，以箭头表示源到目标；不复制共享节点，不添加虚构根节点，也不
为凑树结构删边。环路内的节点放在同一层，环路外按真实方向向右展开。

对话 ECharts 代码块中，标题或系列名明确包含“拓扑”“依赖”“链路”
等语义的旧 `graph + force` 配置也会采用上述布局。其他关系图及显式指定的
固定布局不受影响。

离线布局回归：

```bash
node --experimental-strip-types --test src/components/topologyLayout.test.ts
```
