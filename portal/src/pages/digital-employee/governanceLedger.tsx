import { PlusOutlined, SearchOutlined } from "@ant-design/icons";
import { useMemo, useState } from "react";
import { getSession } from "../../auth/ssoSession";
import { Alert, Button, Descriptions, Empty, Form, Input, Modal, Select, Space, Table, Typography } from "antd";

export type Values = Record<string, string>;
export interface Field {
  key: string;
  label: string;
  options?: string[];
  required?: boolean;
  hidden?: boolean;
  type?: "date" | "datetime-local" | "number" | "textarea";
}
interface Revision { time: string; values: Values }
export interface RecordRow extends Revision { id: string; history: Revision[] }
export const fmtDateTime = (iso: string) => new Date(iso).toLocaleString("zh-CN", { hour12: false });
export const field = (key: string, label: string, options?: string[]): Field => ({ key, label, options, required: true });
export const optional = (key: string, label: string, type?: Field["type"]): Field => ({ key, label, type });

export function governanceAccount() {
  const user = getSession()?.user;
  return user?.userId != null && user.userId !== "" ? `id:${user.userId}` : user?.username ? `name:${user.username}` : "";
}

const ledgerKey = (scope: string, id: string) => `portal.governance.v1.${encodeURIComponent(scope)}.${id}`;
export function getLedgerRows(scope: string, id: string): RecordRow[] {
  try { return scope ? getRecords(ledgerKey(scope, id)) : []; }
  catch { return []; }
}

function getRecords(key: string): RecordRow[] {
  const raw = localStorage.getItem(key);
  if (!raw) return [];
  const parsed = JSON.parse(raw);
  if (!Array.isArray(parsed)) throw new Error("Invalid ledger");
  return parsed;
}

export function Ledger({ id, scope, fields, initial, seedKey, adorn, validate, onSaved, actionLabel = "新增记录" }: {
  id: string;
  scope: string;
  fields: Field[];
  initial?: Values;
  seedKey?: string;
  adorn?: (row: RecordRow) => React.ReactNode;
  validate?: (values: Values) => string | undefined;
  onSaved?: (values: Values) => void;
  actionLabel?: string;
}) {
  const key = ledgerKey(scope, id);
  const [store, setStore] = useState(() => {
    try { return { rows: getRecords(key), error: "" }; }
    catch { return { rows: [] as RecordRow[], error: "本地记录读取失败。请检查浏览器存储权限或保留损坏数据以便排查。" }; }
  });
  const [editor, setEditor] = useState<{ row?: RecordRow } | null>(null);
  const [history, setHistory] = useState<RecordRow | null>(null);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [lastSeed, setLastSeed] = useState("");
  const [form] = Form.useForm<Values>();
  const visible = useMemo(() => store.rows.filter((row) => !query.trim() ||
    Object.values(row.values).some((value) => value.toLowerCase().includes(query.trim().toLowerCase()))), [query, store.rows]);

  const open = (values: Values, row?: RecordRow) => {
    setError("");
    setEditor({ row });
    form.resetFields();
    form.setFieldsValue(values);
  };
  const save = (raw: Values) => {
    if (!editor || !scope || store.error) return;
    const values = Object.fromEntries(Object.entries(raw).map(([key, value]) => [key, String(value ?? "").trim()]));
    const invalid = validate?.(values);
    if (invalid) { setError(invalid); return; }
    const time = new Date().toISOString();
    try {
      const before = getRecords(key);
      const previous = editor.row && before.find((item) => item.id === editor.row?.id);
      if (editor.row && previous?.time !== editor.row.time) {
        setStore({ rows: before, error: "" });
        setError("这条记录已在另一窗口更新，请关闭后重新打开。 ");
        return;
      }
      const updated = { id: previous?.id ?? (globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`), time, values,
        history: previous ? [{ time: previous.time, values: previous.values }, ...previous.history] : [] };
      const rows = [updated, ...before.filter((item) => item.id !== updated.id)];
      localStorage.setItem(key, JSON.stringify(rows));
      setStore({ rows, error: "" });
      setEditor(null);
      onSaved?.(values);
    } catch {
      setError("保存失败，浏览器可能禁止存储或存储空间已满。");
    }
  };
  // A handoff from a selected component or alert is user-initiated. Ignore
  // previous seeds when this tab next mounts; offer the prefilled form explicitly.
  const prefilled = Boolean(seedKey && seedKey !== lastSeed);
  const selectedName = initial?.component || initial?.name;
  return <div className="gov-flow">
    {(store.error || !scope) && <Alert type="warning" title={store.error || "无法识别当前账号，台账编辑不可用。"} showIcon />}
    <div className="gov-surface">
      <div className="gov-toolbar gov-ledger-toolbar">
        <div className="gov-ledger-status">
          <strong>{prefilled && selectedName ? `所选条目：${selectedName}` : `${visible.length} 条记录`}</strong>
          <span className="gov-secondary">{prefilled ? "可将所选条目信息带入登记表单" : "记录保存在当前账号的此浏览器中"}</span>
        </div>
        <div className="gov-toolbar-actions">
          <Input aria-label="搜索记录" placeholder="搜索记录" prefix={<SearchOutlined aria-hidden="true" />}
            allowClear onChange={(event) => setQuery(event.target.value)} value={query} />
          <Button type="primary" icon={<PlusOutlined />} disabled={Boolean(store.error) || !scope} onClick={() => {
            if (seedKey) setLastSeed(seedKey);
            open((!seedKey || prefilled ? initial : undefined) ?? {});
          }}>{prefilled ? "按所选条目登记" : actionLabel}</Button>
        </div>
      </div>
      <Table<RecordRow> className="gov-table" size="small" tableLayout="fixed" rowKey="id" dataSource={visible}
        pagination={{ pageSize: 7, hideOnSinglePage: true, size: "small" }}
        scroll={visible.length ? { x: adorn ? 1032 : 896 } : undefined}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={query ? "没有匹配的记录" : "还没有登记记录"} /> }}
        columns={[
          ...fields.slice(0, 4).map((f, index) => ({ title: f.label, key: f.key, width: index === 0 ? 174 : 134,
            render: (_: unknown, row: RecordRow) => row.values[f.key] || "—" })),
          ...(adorn ? [{ title: "核查标注", key: "review", width: 136, render: (_: unknown, row: RecordRow) => adorn(row) }] : []),
          { title: "最近登记", key: "time", width: 180, render: (_, row) => fmtDateTime(row.time) },
          { title: "操作", key: "actions", width: 140, align: "center", fixed: visible.length ? "right" : undefined,
            render: (_, row) => <Space size={6}>
              <Button size="small" onClick={() => setHistory(row)}>详情</Button>
              <Button size="small" disabled={!scope || Boolean(store.error)} onClick={() => open(row.values, row)}>更新</Button>
            </Space> },
        ]} />
    </div>
    <Modal className="gov-modal" title={editor?.row ? "更新登记记录" : "新增登记记录"} open={!!editor} onCancel={() => setEditor(null)}
      forceRender width={760} okText="保存登记" cancelText="取消" onOk={() => form.submit()}>
      <Form<Values> form={form} layout="vertical" onFinish={save}>
        <div className="gov-form-grid">
          {fields.map((item) => <Form.Item key={item.key} name={item.key} label={item.label} hidden={item.hidden}
            className={item.type === "textarea" ? "gov-full" : undefined}
            rules={item.required ? [{ required: true, whitespace: !item.options, message: `请填写${item.label}` }] : undefined}>
            {item.options ? <Select options={item.options.map((value) => ({ value }))} placeholder="请选择" />
              : item.type === "textarea" ? <Input.TextArea rows={2} maxLength={800} />
              : <Input type={item.type} maxLength={240} />}
          </Form.Item>)}
        </div>
      </Form>
      {error && <Alert type="error" showIcon title={error} />}
    </Modal>
    <Modal className="gov-modal" title="登记详情及历次修订" open={!!history} onCancel={() => setHistory(null)} footer={null} width={850}>
      {history && [history, ...history.history].map((item, index) => <div key={`${item.time}:${index}`} className="gov-revision">
        <Typography.Text strong>{index === 0 ? "当前记录" : `历史修订 ${index}`} · {fmtDateTime(item.time)}</Typography.Text>
        <Descriptions bordered size="small" column={{ xs: 1, sm: 2, md: 2 }} items={fields.filter((f) => !f.hidden).map((f) => ({ key: f.key, label: f.label, children: item.values[f.key] || "—" }))} />
      </div>)}
    </Modal>
  </div>;
}
