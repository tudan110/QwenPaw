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
