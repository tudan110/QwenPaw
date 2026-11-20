import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Button, Input, Modal, Tag } from "antd";
import {
  type Kind, type Operation, type Oversight, type Policy, type Preview, type Workspace,
  downloadControlled, readControlled, writeControlled,
} from "../../api/controlledDocuments";
import { emitKnowledgeBaseChanged } from "../../api/knowledgeBaseChange";
import "./controlledDocuments.css";

const KINDS: Record<Kind, string> = { export: "导出原文", share: "限时共享脱敏预览", archive: "批量归档" };
const STATES: Record<string, string> = {
  pending_confirm: "待本人确认", pending_review: "待管理员复核", ready: "已授权，待执行", export_ready: "单次下载已授权",
  running: "执行中", paused: "已暂停", stopped: "已停止", completed: "已完成", rejected: "复核拒绝", expired: "已过期",
  interrupted: "执行中断，检查点已保留", conflict: "资料状态冲突，操作已冻结", rolled_back: "已回退",
};
const date = (value: number) => new Date(value * 1000).toLocaleString();
const errorMessage = (error: unknown) => error instanceof Error ? error.message : "请求失败";
const idPattern = /^[a-f0-9]{32}$/;

export function ControlledDocumentsPanel() {
  const [workspace, setWorkspace] = useState<Workspace>();
  const [oversight, setOversight] = useState<Oversight>();
  const [notice, setNotice] = useState<{ error: boolean; text: string }>();
  const [loading, setLoading] = useState(false);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [lookup, setLookup] = useState("");
  const [preview, setPreview] = useState<Preview>();
  const [publishPreview, setPublishPreview] = useState<Preview>();
  const [recipient, setRecipient] = useState("");
  const [minutes, setMinutes] = useState(15);
  const [tab, setTab] = useState<"workspace" | "oversight">("workspace");
  const [cap, setCap] = useState(10);
  const [limit, setLimit] = useState(3);
  const lastActor = useRef("");
  const requestId = useRef(0);
  const latestRead = useRef(0);
  const pending = useRef(false);

  const refresh = useCallback(async () => {
    const sequence = ++requestId.current;
    try {
      const snapshot = await readControlled<Workspace>("/state");
      if (sequence < latestRead.current) return;
      latestRead.current = sequence;
      if (lastActor.current !== snapshot.actor) {
        setPreview(undefined); setPublishPreview(undefined); setSelected([]); setOversight(undefined);
        setTitle(""); setContent(""); setLookup(""); setRecipient(""); setLastControl("");
        setCap(snapshot.policy.batch_cap); setLimit(snapshot.policy.alert_limit);
        lastActor.current = snapshot.actor;
      }
      setWorkspace(snapshot);
      if (tab === "oversight" && snapshot.admin) {
        const admin = await readControlled<Oversight>("/admin/state");
        if (sequence === latestRead.current) setOversight(admin);
      }
    } catch (error) {
      if (sequence >= latestRead.current) {
        latestRead.current = sequence;
        setWorkspace(undefined); setOversight(undefined); setPreview(undefined); setPublishPreview(undefined);
        setNotice({ error: true, text: errorMessage(error) });
      }
    }
  }, [tab]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => { if (!pending.current && !document.hidden) void refresh(); }, 2500);
    return () => { window.clearInterval(timer); latestRead.current = ++requestId.current; };
  }, [refresh]);

  useEffect(() => {
    setPreview((last) => last && workspace?.documents.some((doc) => doc.id === last.id && !doc.archived) ? last : undefined);
  }, [workspace?.documents]);

  async function perform(fn: () => Promise<unknown>, text: string) {
    if (pending.current) return;
    pending.current = true;
    setLoading(true); setNotice(undefined);
    try { await fn(); setNotice({ error: false, text }); }
    catch (error) { setNotice({ error: true, text: errorMessage(error) }); }
    finally { await refresh(); pending.current = false; setLoading(false); }
  }

  const update = (path: string, label: string, body?: unknown) => void perform(() => writeControlled(path, body), label);
  function openDocument(id: string) {
    setPreview(undefined);
    setLookup(id);
    void perform(async () => setPreview(await readControlled<Preview>(`/documents/${id}`)), "已通过后端校验并读取资料预览");
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void perform(async () => {
      await writeControlled("/documents", { title: title.trim(), content });
      setTitle(""); setContent("");
    }, "资料已保存，分类结果已记录");
  }

  function ask(kind: Kind) {
    const targets = selected.filter((id) => workspace?.documents.some((doc) => doc.id === id && doc.owner && !doc.archived));
    void perform(async () => {
      await writeControlled("/operations", { kind, targets, ...(kind === "share" ? { recipient: recipient.trim(), minutes } : {}) });
      setSelected([]);
    }, "已提交申请，请到操作列表确认对象和后果");
  }

  function download(op: Operation) {
    void perform(async () => {
      const blob = await downloadControlled(`/operations/${op.id}/download`);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = `document-${op.targets[0]}.txt`; a.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
    }, "原文已送达浏览器，单次许可已消耗");
  }

  const policyText = (policy: Policy) => `批量上限 ${policy.batch_cap} 项、5 分钟拒绝告警阈值 ${policy.alert_limit} 次`;
  const short = selected.filter((id) => workspace?.documents.some((doc) => doc.id === id && doc.owner && !doc.archived));
  const action = (op: Operation, control: string, text: string) => update(`/operations/${op.id}/control/${control}`, text);
  const emergency = (active: boolean) => void perform(async () => {
    const result = await writeControlled<{ active: boolean; affected: number }>("/admin/emergency", { active });
    setLastControl(result.active ? `紧急关停已生效，${result.affected} 个运行中的归档任务已暂停` : "已解除关停，暂停的任务不会自动续跑");
  }, "控制结果已记录");
  const [lastControl, setLastControl] = useState("");

  return <div className="controlled-documents">
    <header>
      <h3>受控资料</h3>
      <p>保存后仅本人可见。AI 管理员可先检查脱敏预览，再把本人资料发布到共享知识库，供智能体检索。</p>
      <p>管理个人文本资料、限时共享和需要复核的资料操作。该工作区和聊天附件分开保存。</p>
      {workspace?.admin && <p>已发布副本在知识库中单独管理；归档个人原件不会撤回共享副本。</p>}
      {workspace && <p>当前智观账号：<strong>{workspace.actor}</strong> <Tag>{workspace.admin ? "AI 管理员" : "普通用户"}</Tag>
        <Tag color={workspace.policy.emergency ? "red" : "green"}>{workspace.policy.emergency ? "紧急关停中" : "受控操作开放"}</Tag></p>}
      <Button onClick={() => void refresh()} disabled={loading}>刷新状态</Button>
      {workspace?.security_hold && <p role="alert" className="controlled-error">安全告警待处置：本账号的导出、共享和批量归档已冻结。</p>}
    </header>
    <Modal
      open={!!publishPreview}
      title="发布到共享知识库"
      okText="确认已检查并发布"
      cancelText="取消"
      onCancel={() => setPublishPreview(undefined)}
      onOk={() => {
        if (!publishPreview) return;
        const { id } = publishPreview;
        setPublishPreview(undefined);
        void perform(async () => {
          await writeControlled(`/admin/documents/${id}/publish`, { reviewed_for_sharing: true });
          emitKnowledgeBaseChanged("controlled-documents", "manual-entry-created");
        }, "脱敏版本已发布，可在知识库检索。原件仍保留在受控资料中。");
      }}
    >
      <p>将发布「{publishPreview?.title}」的当前脱敏预览。可访问企业共享知识库的用户和智能体均可检索；请检查预览中是否仍有不宜公开的内容。</p>
      <pre style={{ whiteSpace: "pre-wrap", maxHeight: 280, overflow: "auto" }}>{publishPreview?.content}</pre>
    </Modal>
    {notice && <p role={notice.error ? "alert" : "status"} className={notice.error ? "controlled-error" : "controlled-success"}>{notice.text}</p>}
    {workspace && <>
      <nav aria-label="受控资料功能">
        <Button type={tab === "workspace" ? "primary" : "default"} onClick={() => setTab("workspace")}>资料与任务</Button>
        {workspace.admin && <Button type={tab === "oversight" ? "primary" : "default"} onClick={() => setTab("oversight")}>复核与管控</Button>}
      </nav>
      {tab === "workspace" ? <>
        <section>
          <h4>新增个人资料</h4>
          <form onSubmit={submit}>
            <Input aria-label="资料标题" placeholder="资料标题（不填敏感信息）" maxLength={100} value={title} onChange={(e) => setTitle(e.target.value)} />
            <Input.TextArea aria-label="资料内容" rows={4} value={content} placeholder="粘贴文本，或从下方选择 UTF-8 文本文件" maxLength={32000} onChange={(e) => setContent(e.target.value)} />
            <input type="file" aria-label="选择文本文件" accept=".txt,.md,.csv,.json,text/plain" onChange={(e) => {
              const file = e.target.files?.[0]; e.target.value = "";
              if (!file) return;
              if (file.size > 128000) { setNotice({ error: true, text: "文件超过文本大小上限" }); return; }
              void file.arrayBuffer().then((buffer) => {
                const text = new TextDecoder("utf-8", { fatal: true }).decode(buffer);
                if (text.length > 32000 || text.includes("\0")) throw new Error("请选择不超过 32,000 字符的 UTF-8 纯文本");
                setContent(text); setTitle(file.name.slice(0, 100));
              }).catch((error) => setNotice({ error: true, text: errorMessage(error) }));
            }} />
            <Button type="primary" htmlType="submit" disabled={loading || !title.trim() || !content.trim()}>保存并分类</Button>
          </form>
        </section>
        <section>
          <h4>本人资料与收到的共享</h4>
          <div className="controlled-line">
            <Input aria-label="资料编号" placeholder="粘贴资料编号核验读取权限" value={lookup} onChange={(e) => setLookup(e.target.value.trim())} />
            <Button disabled={loading || !idPattern.test(lookup)} onClick={() => openDocument(lookup)}>读取资料</Button>
          </div>
          {!workspace.documents.length && <p>暂无可见资料。</p>}
          {workspace.documents.map((doc) => <div key={doc.id} className="controlled-record">
            <label><input type="checkbox" checked={short.includes(doc.id)} disabled={!doc.owner || doc.archived || loading} onChange={(e) => setSelected((old) => e.target.checked ? [...old, doc.id] : old.filter((id) => id !== doc.id))} /> {doc.title}</label>
            <Tag>{doc.owner ? (doc.archived ? "本人 · 已归档" : "本人 · 可操作") : "限时共享 · 只读"}</Tag>
            {doc.labels.map((label) => <Tag color="orange" key={label}>{label}</Tag>)}
            <code>{doc.id}</code>
            {!doc.archived && <Button size="small" disabled={loading} onClick={() => openDocument(doc.id)}>查看脱敏预览</Button>}
            {workspace.admin && !workspace.policy.emergency && !workspace.security_hold && doc.owner && !doc.archived && preview?.id === doc.id && <Button size="small" disabled={loading} onClick={() => setPublishPreview(preview)}>发布到知识库</Button>}
          </div>)}
          {preview && <div className="controlled-record"><strong>{preview.title} · {preview.masked ? "已遮蔽命中内容" : "未命中已配置规则"}</strong>
            <code>{preview.id}</code><pre>{preview.content}</pre></div>}
          <p>已选 {short.length} 项。批量上限 {workspace.policy.batch_cap} 项；超过上限请分批申请。</p>
          <div className="controlled-line">
            <Button disabled={loading || short.length !== 1 || !!workspace.policy.emergency} onClick={() => ask("export")}>申请原文导出</Button>
            <Button disabled={loading || !short.length || !!workspace.policy.emergency} onClick={() => ask("archive")}>申请批量归档</Button>
          </div>
          <div className="controlled-line">
            <Input aria-label="接收方智观用户 ID" placeholder="接收方智观用户 ID" value={recipient} onChange={(e) => setRecipient(e.target.value)} />
            <label>有效分钟 <input type="number" min={1} max={60} value={minutes} onChange={(e) => setMinutes(Number(e.target.value))} /></label>
            <Button disabled={loading || short.length !== 1 || !recipient.trim() || minutes < 1 || minutes > 60 || !!workspace.policy.emergency} onClick={() => ask("share")}>申请限时共享</Button>
          </div>
        </section>
        <section>
          <h4>操作申请与执行</h4>
          {!workspace.operations.length && <p>暂无操作。</p>}
          {workspace.operations.map((op) => <div className="controlled-record" key={op.id}>
            <strong>{KINDS[op.kind]}</strong> <Tag color={op.status === "running" ? "blue" : undefined}>{STATES[op.status] || op.status}</Tag>
            <code>{op.id}</code>
            <div>目标：{op.targets.map((id) => workspace.documents.find((doc) => doc.id === id)?.title || id).join("、")}</div>
            {op.recipient_label && <div>接收方 {op.recipient_label} · 仅可读脱敏预览 · 生效后 {op.minutes} 分钟</div>}
            <div>更新 {date(op.updated)} · 执行许可截至 {date(op.expires)}{op.reviewer ? ` · 复核人 ${op.reviewer}` : ""}</div>
            {op.kind === "archive" && <div>检查点 {op.cursor}/{op.targets.length} {op.control_ms === null ? "" : `· 服务端最近控制处理 ${op.control_ms} ms`}</div>}
            {op.status === "pending_confirm" && <p>{op.kind === "archive" ? "归档会移除可用资料并撤销已有共享。本批资料可回退，旧授权需重新申请。" : op.kind === "export" ? "下载将向当前浏览器交付未脱敏原文，许可仅可使用一次。" : "授权指定账号在有效期内读取脱敏预览，可主动撤销。"}
              {op.sensitive ? " 此操作还须经管理员复核。" : ""}</p>}
            <div className="controlled-line">
              {op.status === "pending_confirm" && <Button disabled={loading} onClick={() => update(`/operations/${op.id}/confirm`, "本人确认已记录")}>确认目标和后果</Button>}
              {op.status === "ready" && <Button type="primary" disabled={loading || !!workspace.policy.emergency} onClick={() => update(`/operations/${op.id}/execute`, "已开始执行，请查看当前状态")}>执行已授权操作</Button>}
              {op.status === "export_ready" && <Button disabled={loading || !!workspace.policy.emergency} onClick={() => download(op)}>下载原文（仅一次）</Button>}
              {op.status === "running" && <Button disabled={loading} onClick={() => action(op, "pause", "已暂停并保留进度")}>暂停</Button>}
              {["paused", "interrupted"].includes(op.status) && op.expires * 1000 > Date.now() && <Button disabled={loading || !!workspace.policy.emergency} onClick={() => action(op, "resume", "已从检查点恢复")}>恢复执行</Button>}
              {["pending_confirm", "pending_review", "ready", "export_ready", "running", "paused", "interrupted", "conflict"].includes(op.status) && <Button disabled={loading} onClick={() => action(op, "stop", "已停止，不再执行后续项")}>停止操作</Button>}
              {op.kind === "archive" && op.cursor > 0 && ["paused", "stopped", "interrupted", "conflict", "completed"].includes(op.status) && <Button disabled={loading} onClick={() => action(op, "rollback", "已将本操作归档的资料恢复为可用")}>回退已归档资料</Button>}
            </div>
          </div>)}
        </section>
        <section>
          <h4>限时授权</h4>
          {!workspace.grants.length && <p>暂无记录。</p>}
          {workspace.grants.map((item) => <div className="controlled-record" key={item.id}>
            {item.title} · {item.outgoing ? `授予 ${item.recipient_label}` : "收到共享"} · {item.revoked ? `已撤销 ${date(item.revoked)}` : item.expires * 1000 <= Date.now() ? "已到期" : `有效至 ${date(item.expires)}`}
            <code>{item.document_id}</code>
            {item.outgoing && !item.revoked && item.expires * 1000 > Date.now() && <Button size="small" disabled={loading} onClick={() => update(`/grants/${item.id}/revoke`, "共享权限已撤销")}>撤销授权</Button>}
          </div>)}
        </section>
      </> : workspace.admin && <>
        <section>
          <h4>紧急关停（受控资料）</h4>
          <p>关停后阻止导出、共享和新归档，暂停正在运行的归档任务并保留检查点。</p>
          <Button danger={workspace.policy.emergency === 0} disabled={loading} onClick={() => emergency(!workspace.policy.emergency)}>{workspace.policy.emergency ? "解除关停" : "关停受控资料操作"}</Button>
          {lastControl && <p role="status">{lastControl}</p>}
        </section>
        <section>
          <h4>待管理员复核</h4>
          {oversight?.reviews.length === 0 && <p>暂无待复核操作。</p>}
          {oversight?.reviews.map((op) => <div className="controlled-record" key={op.id}>
            <strong>{KINDS[op.kind]}</strong> · 申请人 {op.subject} · {op.targets.length} 个目标
            <div>资料编号：{op.targets.join("、")}</div><code>{op.id}</code>
            {op.recipient_label && <p>接收方 {op.recipient_label} · {op.minutes} 分钟</p>}
            <div className="controlled-line">
              <Button type="primary" disabled={loading} onClick={() => update(`/admin/review/${op.id}`, "已通过复核，等待申请人执行", { approve: true })}>批准</Button>
              <Button danger disabled={loading} onClick={() => update(`/admin/review/${op.id}`, "已拒绝操作", { approve: false })}>拒绝</Button>
            </div>
          </div>)}
        </section>
        <section>
          <h4>运行策略与版本回退</h4>
          <p>当前：{policyText(workspace.policy)}</p>
          <div className="controlled-line">
            <label>批量上限 <input type="number" min={2} max={20} value={cap} onChange={(e) => setCap(Number(e.target.value))} /></label>
            <label>拒绝告警阈值 <input type="number" min={2} max={10} value={limit} onChange={(e) => setLimit(Number(e.target.value))} /></label>
            <Button disabled={loading || cap < 2 || cap > 20 || limit < 2 || limit > 10} onClick={() => update("/admin/policy", "策略已生效", { batch_cap: cap, alert_limit: limit })}>保存运行策略</Button>
          </div>
          {oversight?.revisions.map((revision) => <div className="controlled-record" key={revision.id}>
            <strong>{revision.restored_from ? "回退" : "变更"}</strong> · {date(revision.created)} · {revision.subject}
            <p>{policyText(revision.before)} → {policyText(revision.after)}</p><code>{revision.id}</code>
            <Button size="small" disabled={loading} onClick={() => update(`/admin/policy/${revision.id}/restore`, "已恢复该版本变更前的策略")}>恢复变更前策略</Button>
          </div>)}
        </section>
        <section>
          <h4>越权告警与处置</h4>
          {oversight?.incidents.length === 0 && <p>暂无告警。</p>}
          {oversight?.incidents.map((event) => <div className="controlled-record" key={event.id}>
            <Tag color={event.resolved ? "green" : "red"}>{event.resolved ? "已处置" : "待处置"}</Tag> {date(event.created)} · 账号 {event.subject} · 5 分钟内拒绝 {event.count} 次（阈值 {event.threshold} 次）
            <div>关联事件 <code>{event.event_id}</code></div>
            {event.resolved ? <p>{event.resolver} · {date(event.resolved)}</p> : <Button size="small" disabled={loading} onClick={() => update(`/admin/incidents/${event.id}/resolve`, "已记录告警处置并解除冻结，暂停任务不会自动恢复")}>标记处置完毕</Button>}
          </div>)}
        </section>
        <section>
          <h4>近期实际操作记录</h4>
          {oversight?.events.length === 0 && <p>暂无记录。</p>}
          {oversight?.events.map((event) => <div className="controlled-record" key={event.id}>
            {date(event.created)} · {event.subject} · <strong>{event.action}</strong> <Tag>{event.result}</Tag>
            <div>对象 <code>{event.object_id}</code> · 记录 <code>{event.id}</code></div>{event.reason && <p>{event.reason}</p>}
          </div>)}
        </section>
      </>}
    </>}
  </div>;
}
