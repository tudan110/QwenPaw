import assert from "node:assert/strict";
import test from "node:test";
import {
  extractRuntimeErrorText,
  runtimeErrorToFriendly,
  toFriendlyChatError,
} from "./chatErrorMessage.ts";

const GENERIC = "服务暂时遇到点问题，请稍后重试。";

test("hides raw python tracebacks behind a generic friendly line", () => {
  const raw =
    'Traceback (most recent call last):\n  File "x.py", line 3, in <module>\n    boom()\nRuntimeError: boom';
  const out = toFriendlyChatError(raw);
  assert.equal(out, GENERIC);
  assert.doesNotMatch(out, /Traceback|File "|boom/);
});

test("maps model category codes to friendly Chinese", () => {
  assert.match(toFriendlyChatError("failed (MODEL_TIMEOUT)"), /超时/);
  assert.match(toFriendlyChatError("failed (MODEL_QUOTA_EXCEEDED)"), /访问量较大/);
  assert.match(toFriendlyChatError("failed (MODEL_CONTEXT_LENGTH_EXCEEDED)"), /内容过长/);
  assert.match(toFriendlyChatError("failed (UNAUTHORIZED_MODEL_ACCESS)"), /联系管理员/);
  assert.match(
    toFriendlyChatError("Model execution failed (MODEL_EXECUTION_ERROR)"),
    /模型服务暂时不可用/,
  );
});

test("network interruptions get a retry hint", () => {
  assert.match(
    toFriendlyChatError("httpx.RemoteProtocolError: peer closed connection"),
    /连接中断/,
  );
});

test("explains vLLM automatic tool-choice deployment configuration errors", () => {
  const raw =
    '400 Bad Request: "auto" tool choice requires --enable-auto-tool-choice and --tool-call-parser hermes';
  const message = toFriendlyChatError(raw);
  assert.match(message, /模型部署配置问题/);
  assert.match(message, /vLLM/);
  assert.match(message, /平台管理员检查/);
  assert.doesNotMatch(message, /400|hermes|Bad Request/);
});

test("never leaks internal dump paths / product names", () => {
  const out = toFriendlyChatError("boom (Details: /tmp/qwenpaw_query_error_abc.json)");
  assert.doesNotMatch(out, /\/tmp|qwenpaw|Details/);
});

test("unknown or empty errors fall back to one friendly line", () => {
  assert.equal(toFriendlyChatError("some totally unmapped weirdness"), GENERIC);
  assert.equal(toFriendlyChatError(""), GENERIC);
  assert.equal(toFriendlyChatError(null), GENERIC);
});

test("extractRuntimeErrorText normalizes string / {code,message} / ERROR item", () => {
  assert.equal(extractRuntimeErrorText("hi"), "hi");
  assert.equal(
    extractRuntimeErrorText({ code: "MODEL_TIMEOUT", message: "took too long" }),
    "took too long (MODEL_TIMEOUT)",
  );
  const errItem = {
    code: "ERR",
    message: "",
    content: [{ type: "text", text: "deep detail" }],
  };
  assert.match(extractRuntimeErrorText(errItem), /deep detail \(ERR\)/);
});

test("runtimeErrorToFriendly maps an {code,message} object end to end", () => {
  assert.match(
    runtimeErrorToFriendly({ code: "MODEL_QUOTA_EXCEEDED", message: "429 rate" }),
    /访问量较大/,
  );
});

test("explains Kunlun model authorization without claiming credentials expired", () => {
  const message = toFriendlyChatError(
    "Kunlun model request failed (KUNLUN_MODEL_UNAUTHORIZED)",
  );
  assert.match(message, /昆仑模型未授权/);
  assert.match(message, /模型 ID、应用授权及模型密钥权限/);
  assert.doesNotMatch(message, /过期|稍后重试|KUNLUN_|MODEL_EXECUTION/);
});

test("distinguishes known gateway route errors from ambiguous missing resources", () => {
  const route = runtimeErrorToFriendly({
    message: "Kunlun model request failed (KUNLUN_ROUTE_NOT_FOUND)",
  });
  assert.match(route, /昆仑接口未找到/);
  assert.match(route, /网关转发路由/);
  assert.doesNotMatch(route, /未授权|过期/);

  const missing = runtimeErrorToFriendly({ code: "KUNLUN_NOT_FOUND" });
  assert.match(missing, /接口或模型未找到/);
  assert.match(missing, /模型 ID/);
});

test("gives category-specific Kunlun recovery advice across runtime error shapes", () => {
  const cases = [
    ["KUNLUN_AUTH_FAILED", /身份验证未通过.*不一定代表凭据已过期/],
    ["KUNLUN_NOT_CONFIGURED", /配置不完整.*补全网关地址/],
    ["KUNLUN_SERVICE_UNAVAILABLE", /网关或模型服务暂时不可用/],
    ["KUNLUN_CONNECTION_FAILED", /无法连接.*SDP.*登录状态和资源访问权限/],
    ["KUNLUN_TIMEOUT", /响应超时/],
    ["KUNLUN_RATE_LIMITED", /请求受限.*调用额度/],
  ] as const;
  for (const [code, expected] of cases) {
    for (const error of [
      `Kunlun model request failed (${code})`,
      { code, message: "safe failure" },
      { content: [{ type: "text", text: `safe failure (${code})` }] },
    ]) {
      const message = runtimeErrorToFriendly(error);
      assert.match(message, expected);
      assert.doesNotMatch(message, /KUNLUN_|safe failure/);
    }
  }
});

test("never echoes sensitive provider detail alongside a recognized Kunlun code", () => {
  const message = toFriendlyChatError(
    new Error(
      "private-model sk-private-key Bearer private-token /tmp/private.json " +
        "(KUNLUN_MODEL_UNAUTHORIZED)",
    ),
  );
  assert.match(message, /昆仑模型未授权/);
  assert.doesNotMatch(message, /private|Bearer|\/tmp|sk-/);
  assert.equal(
    toFriendlyChatError(
      "Traceback (most recent call last): (KUNLUN_MODEL_UNAUTHORIZED)",
    ),
    GENERIC,
  );
  assert.equal(toFriendlyChatError("KUNLUN_UNKNOWN_FAILURE"), GENERIC);
});
