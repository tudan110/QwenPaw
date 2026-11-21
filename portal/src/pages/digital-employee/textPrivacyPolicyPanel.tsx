import { useEffect, useState } from "react";
import { Alert, Button, Checkbox, Collapse, Input, Select, Skeleton, Space, Tag } from "antd";
import { readControlled, writeControlled } from "../../api/controlledDocuments";

const endpoint = "/admin/sensitive-data/policy";
type Mode = "off" | "observe" | "block";
type Scene = { id: string; label: string; detail: string; action: string };
type Policy = { revision: number; builtin: string[]; custom_fields: string[] } & Record<string, Mode | number | string[]>;
type Status = {
  policy: Policy;
  scenes: Scene[];
  available_builtin: string[];
  hits: { id: number; at: number; scene: string; decision: "observed" | "blocked"; revision: number; rule_count: number }[];
};
const sceneOptions = (scene: Scene): { value: Mode; label: string }[] => [
  { value: "off", label: "关闭" },
  { value: "observe", label: "仅记录命中" },
  { value: "block", label: scene.action },
];
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
    if (!draft || !status) return;
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
    if (!draft.builtin.length && !custom.length && status.scenes.some(({ id }) => draft[id] !== "off")) {
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
      <div><h4 id="sd-privacy-policy">敏感数据识别与场景策略</h4>
        <p>各场景独立设置处理方式，统一使用下方识别规则。保存后对所有使用对应入口的用户生效。</p></div>
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
        {status.scenes.map((scene) => {
          const options = sceneOptions(scene);
          const activeLabel = options.find(({ value }) => value === status.policy[scene.id])?.label;
          return <li key={scene.id}>
            <div><strong>{scene.label}</strong><p>已生效：{activeLabel ?? "未知"}</p></div>
            <Select<Mode> className="sd-privacy-mode" aria-label={`${scene.label}处理方式`}
              value={draft[scene.id] as Mode} disabled={busy} options={options}
              onChange={(mode) => setDraft({ ...draft, [scene.id]: mode })} />
            <p>{scene.detail}</p>
          </li>;
        })}
      </ul>
      <p>仅记录命中不会阻止操作。阻止模式不会自动脱敏；日志和缓存命中时跳过写入。策略不追溯清理历史数据，也不识别图片、音频或视频中的内容。</p>
      <Collapse size="small" items={[{ key: "hits", label: "近期命中记录", children: status.hits.length ? <ul className="sd-event-list">
        {status.hits.map((hit) => <li key={hit.id}>
          <span>{new Date(hit.at * 1000).toLocaleString("zh-CN")}</span>
          <strong>{status.scenes.find(({ id }) => id === hit.scene)?.label ?? "其他场景"}</strong>
          <Tag color={hit.decision === "blocked" ? "red" : undefined}>{hit.decision === "blocked" ? "已阻止" : "仅记录"}</Tag>
          <span>{hit.rule_count} 条规则 · 策略版本 {hit.revision}</span>
        </li>)}
      </ul> : <p>暂无已记录命中。记录不保存正文、命中的原值或账号。</p> }]} />
    </>}
  </section>;
}
