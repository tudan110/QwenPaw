# Portal iframe 抽屉关闭对接说明

## 背景

当前 portal 前端页面会被传统 Web 系统通过 `iframe` 嵌入到右侧抽屉中。

当用户在 portal 页面右上角点击 **切换传统视图** 按钮时，portal 会通过 `postMessage` 通知父页面关闭抽屉。

## 对接目标

宿主系统需要监听 portal 发出的消息，在收到指定消息后关闭右侧抽屉。

## 触发时机

用户点击 portal 右上角 **切换传统视图** 按钮时触发。

## 消息说明

### 发送方向

由 `iframe` 内 portal 页面发送给父页面：

```ts
window.parent.postMessage(message, "*");
```

### 消息体

```json
{
  "source": "qwenpaw-portal",
  "type": "portal:close-drawer",
  "reason": "switch-traditional-view"
}
```

### 字段定义

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `source` | `string` | 固定值：`qwenpaw-portal`，用于标识消息来源 |
| `type` | `string` | 固定值：`portal:close-drawer`，表示请求关闭抽屉 |
| `reason` | `string` | 固定值：`switch-traditional-view`，表示由“切换传统视图”触发 |

## 宿主系统需要做的事情

监听 `message` 事件，识别 portal 发出的关闭抽屉消息，然后关闭右侧抽屉。

## 示例代码

### 原生 JavaScript

```js
window.addEventListener("message", (event) => {
  const data = event.data || {};

  if (
    data.source === "qwenpaw-portal" &&
    data.type === "portal:close-drawer" &&
    data.reason === "switch-traditional-view"
  ) {
    closeDrawer();
  }
});
```

### Vue2 + Element 示例

```js
mounted() {
  this.handlePortalMessage = (event) => {
    const data = event.data || {};

    if (
      data.source === "qwenpaw-portal" &&
      data.type === "portal:close-drawer" &&
      data.reason === "switch-traditional-view"
    ) {
      this.drawerVisible = false;
    }
  };

  window.addEventListener("message", this.handlePortalMessage);
},

beforeDestroy() {
  window.removeEventListener("message", this.handlePortalMessage);
}
```

## 安全建议

建议宿主系统增加 `origin` 校验，只接受 portal 所在域名发出的消息。

示例：

```js
const ALLOWED_ORIGIN = "https://your-portal-domain.example.com";

window.addEventListener("message", (event) => {
  if (event.origin !== ALLOWED_ORIGIN) {
    return;
  }

  const data = event.data || {};

  if (
    data.source === "qwenpaw-portal" &&
    data.type === "portal:close-drawer" &&
    data.reason === "switch-traditional-view"
  ) {
    closeDrawer();
  }
});
```

## 当前实现说明

portal 当前仅发送关闭抽屉消息，不等待父页面回执，也不会在发送后主动跳转到其他视图。
