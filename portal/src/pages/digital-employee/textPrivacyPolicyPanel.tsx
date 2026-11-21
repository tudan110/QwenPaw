import { useEffect, useState } from "react";
import { Alert, Button, Checkbox, Collapse, Input, Select, Skeleton, Space, Tag } from "antd";
import { readControlled, writeControlled } from "../../api/controlledDocuments";

const endpoint = "/admin/sensitive-data/policy";
const modes = { off: "关闭", observe: "仅记录命中", block: "阻止发送" } as const;
type Mode = keyof typeof modes;
const scenes = {
  chat_input: { label: "对话输入", detail: "检查聊天入口收到的文本，拦截发生在新消息进入会话处理前。" },
  model_context: { label: "模型上下文", detail: "检查受管模型调用发送的文本，包括历史对话、系统提示和进入上下文的工具结果。此项也会影响后台任务。" },
} as const;
type Scene = keyof typeof scenes;
const sceneKeys = Object.keys(scenes) as Scene[];
type Policy = Record<Scene, Mode> & { revision: number; builtin: string[]; custom_fields: string[] };
type Status = {
  policy: Policy;
  available_builtin: string[];
  hits: { id: number; at: number; scene: Scene; decision: "observed" | "blocked"; revision: number; rule_count: number }[];
};
const errorText = (error: unknown) => error instanceof Error ? error.message : "请求失败，请重试。";

export function TextPrivacyPolicyPanel() {
  const [status, setStatus] = useState<Status>();
  const [draft, setDraft] = useState<Policy>();
  const [fields, setFields] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  function apply(next: Status) {
    setStatus(next);
    setDraft(next.policy);
    setFields(next.policy.custom_fields.join("\n"));
  }

  useEffect(() => {
    let current = true;
    setLoading(true);
    setError("");
    setNotice("");
    readControlled<Status>(endpoint).then(
      (next) => { if (current) { apply(next); setLoading(false); } },
      (failure: unknown) => { if (current) { setError(errorText(failure)); setLoading(false); } },
    );
    return () => { current = false; };
  }, [attempt]);

  async function save() {
    if (!draft) return;
    setError("");
    setNotice("");
    const custom = fields.split(/\r?\n/).map((field) => field.trim()).filter(Boolean);
    if (custom.length > 32 || custom.some((field) => Array.from(field).length > 48 || !/^[\p{L}\p{N}_][\p{L}\p{N}_ -]*$/u.test(field))) {
      setError("最多配置 32 个字段，每个不超过 48 个字符，仅允许字母、汉字、数字、空格、下划线和短横线。");
      return;
    }
    if (new Set(custom.map((field) => field.toLowerCase())).size !== custom.length) {
      setError("自定义字段名不能重复。");
      return;
    }
    if (!draft.builtin.length && !custom.length && sceneKeys.some((scene) => draft[scene] !== "off")) {
      setError("启用检查前至少选择一条识别规则。");
      return;
    }
    setSaving(true);
    try {
      apply(await writeControlled<Status>(endpoint, { ...draft, custom_fields: custom }));
      setNotice("策略已保存，后续请求将按新策略处理。");
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      setSaving(false);
    }
  }

  const dirty = !!draft && !!status && (draft !== status.policy || fields !== status.policy.custom_fields.join("\n"));
  const busy = loading || saving;
  return <section className="gov-surface sd-section" aria-labelledby="sd-privacy-policy">
    <header className="sd-heading">
      <div><h4 id="sd-privacy-policy">对话与模型上下文</h4>
        <p>全局策略，对所有使用下列入口的用户生效。默认关闭，不改变既有的受控资料分类和授权。</p></div>
      <Space wrap>
        <Button loading={loading} disabled={saving || dirty} onClick={() => setAttempt((value) => value + 1)}>重新读取</Button>
        {draft && <Button disabled={busy || !dirty} onClick={() => { if (status) apply(status); setError(""); setNotice(""); }}>取消编辑</Button>}
        {draft && <Button type="primary" loading={saving} disabled={loading || !dirty} onClick={() => void save()}>保存策略</Button>}
      </Space>
    </header>
    {error && <Alert type="error" showIcon title={error} />}
    {notice && <p role="status">{notice}</p>}
    {loading && !draft && <Skeleton active paragraph={{ rows: 3 }} />}
    {status && draft && <>
      <div className="sd-privacy-definitions">
        <div className="sd-privacy-rule">
          <h5 id="sd-builtin-label">内置识别规则</h5>
          <p>按已知号码格式、显式字段或凭据格式匹配，不识别隐含语义。</p>
          <Checkbox.Group className="sd-tags" aria-labelledby="sd-builtin-label" disabled={busy} value={draft.builtin}
            options={status.available_builtin} onChange={(builtin) => setDraft({ ...draft, builtin })} />
        </div>
        <div className="sd-privacy-rule">
          <label htmlFor="sd-custom-fields"><strong>自定义敏感字段</strong></label>
          <p id="sd-fields-help">每行一个字段名，例如「客户编号」；匹配「客户编号：示例值」。只填写字段名，不填写实际敏感值。</p>
          <Input.TextArea id="sd-custom-fields" aria-describedby="sd-fields-help" disabled={busy} value={fields}
            autoSize={{ minRows: 3, maxRows: 6 }} maxLength={1800} onChange={(event) => setFields(event.target.value)} />
        </div>
      </div>
      <ul className="sd-coverage">
        {sceneKeys.map((scene) => <li key={scene}>
          <div><strong>{scenes[scene].label}</strong><p>已生效：{modes[status.policy[scene]]}</p></div>
          <Select className="sd-privacy-mode" aria-label={`${scenes[scene].label}处理方式`} value={draft[scene]} disabled={busy}
            options={Object.entries(modes).map(([value, label]) => ({ value, label }))}
            onChange={(mode: Mode) => setDraft({ ...draft, [scene]: mode })} />
          <p>{scenes[scene].detail}</p>
        </li>)}
      </ul>
      <p>仅记录不会修改或阻止请求；阻止发送也不会自动脱敏。这里只检查接入链路中的文本，不解析附件、多媒体，不检查回复返回链路，也不追溯处理历史存储、业务导出或日志。</p>
      <Collapse size="small" items={[{ key: "hits", label: "近期命中记录", children: status.hits.length ? <ul className="sd-event-list">
        {status.hits.map((hit) => <li key={hit.id}>
          <span>{new Date(hit.at * 1000).toLocaleString("zh-CN")}</span>
          <strong>{scenes[hit.scene].label}</strong>
          <Tag color={hit.decision === "blocked" ? "red" : undefined}>{hit.decision === "blocked" ? "已阻止" : "仅记录"}</Tag>
          <span>{hit.rule_count} 条规则 · 策略版本 {hit.revision}</span>
        </li>)}
      </ul> : <p>暂无已记录命中。记录不保存正文、命中的原值或账号。</p> }]} />
    </>}
  </section>;
}
