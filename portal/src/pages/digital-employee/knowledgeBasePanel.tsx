import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  archiveKnowledgeSources,
  getIngestionJobProgress,
  getKnowledgeHealth,
  ingestKnowledgeFile,
  listKnowledgeSourceRecords,
  manualEntryKnowledge,
  queryKnowledge,
  unarchiveKnowledgeSources,
  type KbEvidence,
  type KbHealth,
  type KbIngestionJob,
  type KbQueryResponse,
  type KbSourceRecord,
} from "../../api/knowledgeBase";
import "./knowledge-base.css";

type PanelTab = "search" | "upload" | "manage";

const SCOPE_LABELS: Record<string, string> = {
  system_builtin: "平台内置",
  runtime_curated: "运行时沉淀",
  tenant_private: "租户私有",
};

const CONFIDENCE_LABELS: Record<string, string> = {
  high: "高",
  medium: "中",
  low: "低",
};

function formatTimestamp(ts?: string | null) {
  if (!ts) return "—";
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function extractErrorMessage(error: unknown) {
  if (error instanceof Error) return error.message;
  return String(error || "");
}

// =============================================================================

export function KnowledgeBasePanel() {
  const [activeTab, setActiveTab] = useState<PanelTab>("search");
  const [health, setHealth] = useState<KbHealth | null>(null);
  const [healthError, setHealthError] = useState("");

  const refreshHealth = useCallback(async () => {
    try {
      setHealth(await getKnowledgeHealth());
      setHealthError("");
    } catch (error) {
      setHealthError(extractErrorMessage(error));
    }
  }, []);

  useEffect(() => {
    void refreshHealth();
  }, [refreshHealth]);

  return (
    <div className="kb-panel">
      <div className="kb-header">
        <div className="kb-header-title">
          <i className="fas fa-book-open" />
          <div>
            <h2>知识库管理</h2>
            <p>检索、上传、归档运维知识库；同进程子系统，复用知识专员的 LLM/向量配置。</p>
          </div>
        </div>
        <div className="kb-header-status">
          <HealthBadge label="LLM" enabled={Boolean(health?.llm_enabled)} />
          <HealthBadge label="向量" enabled={Boolean(health?.embedding_enabled)} />
          <button className="kb-icon-btn" onClick={() => void refreshHealth()} title="刷新状态">
            <i className="fas fa-rotate" />
          </button>
        </div>
      </div>

      {healthError ? (
        <div className="kb-banner kb-banner-warn">
          <i className="fas fa-triangle-exclamation" />
          无法连接知识库子系统：{healthError}
        </div>
      ) : null}

      <div className="kb-tabs">
        <TabButton active={activeTab === "search"} onClick={() => setActiveTab("search")} icon="fa-magnifying-glass">
          检索
        </TabButton>
        <TabButton active={activeTab === "upload"} onClick={() => setActiveTab("upload")} icon="fa-cloud-arrow-up">
          上传
        </TabButton>
        <TabButton active={activeTab === "manage"} onClick={() => setActiveTab("manage")} icon="fa-folder-open">
          资料管理
        </TabButton>
      </div>

      <div className="kb-tab-body">
        {activeTab === "search" ? <SearchTab /> : null}
        {activeTab === "upload" ? <UploadTab onIngestComplete={() => void refreshHealth()} /> : null}
        {activeTab === "manage" ? <ManageTab /> : null}
      </div>
    </div>
  );
}

// =============================================================================

function TabButton({
  active,
  onClick,
  icon,
  children,
}: {
  active: boolean;
  onClick: () => void;
  icon: string;
  children: React.ReactNode;
}) {
  return (
    <button className={active ? "kb-tab kb-tab-active" : "kb-tab"} onClick={onClick}>
      <i className={`fas ${icon}`} />
      {children}
    </button>
  );
}

function HealthBadge({ label, enabled }: { label: string; enabled: boolean }) {
  return (
    <span className={enabled ? "kb-badge kb-badge-on" : "kb-badge kb-badge-off"}>
      <span className="kb-badge-dot" />
      {label} {enabled ? "可用" : "未配置"}
    </span>
  );
}

// ---------------------------- Search tab -------------------------------

function SearchTab() {
  const [input, setInput] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<KbQueryResponse | null>(null);
  const [error, setError] = useState("");

  const handleSubmit = useCallback(async () => {
    const query = input.trim();
    if (!query) return;
    setSubmitting(true);
    setError("");
    try {
      const response = await queryKnowledge(query);
      setResult(response);
    } catch (err) {
      setError(extractErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }, [input]);

  return (
    <div className="kb-search">
      <div className="kb-search-bar">
        <input
          className="kb-search-input"
          placeholder="向知识库提问，例如：P0 告警 SLA 是什么？"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              void handleSubmit();
            }
          }}
        />
        <button className="kb-primary-btn" onClick={() => void handleSubmit()} disabled={submitting}>
          <i className="fas fa-magnifying-glass" />
          {submitting ? "检索中…" : "检索"}
        </button>
      </div>

      {error ? (
        <div className="kb-banner kb-banner-error">
          <i className="fas fa-circle-exclamation" />
          {error}
        </div>
      ) : null}

      {result ? <SearchResult result={result} /> : (
        <div className="kb-empty kb-empty-hint">
          <i className="fas fa-lightbulb" />
          输入问题后回车，知识库会按 BM25（+可选向量）检索并返回带引用的答案。
        </div>
      )}
    </div>
  );
}

function SearchResult({ result }: { result: KbQueryResponse }) {
  const insufficient = result.flags?.insufficient_evidence;
  return (
    <div className="kb-search-result">
      <div className={`kb-summary ${insufficient ? "kb-summary-insufficient" : ""}`}>
        <div className="kb-summary-head">
          <span className="kb-summary-tag">综合答复</span>
          {result.overall_confidence != null ? (
            <span className="kb-confidence">置信度 {Math.round(result.overall_confidence * 100)}%</span>
          ) : null}
        </div>
        <div className="kb-summary-text">{result.summary || "—"}</div>
        {result.evidence_boundary_statement ? (
          <div className="kb-boundary">{result.evidence_boundary_statement}</div>
        ) : null}
      </div>

      {result.relevant_evidence?.length ? (
        <div className="kb-evidence-list">
          <div className="kb-section-title">引用证据 · {result.relevant_evidence.length} 条</div>
          {result.relevant_evidence.map((ev, idx) => (
            <EvidenceCard key={ev.id} index={idx + 1} evidence={ev} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function EvidenceCard({ index, evidence }: { index: number; evidence: KbEvidence }) {
  const band = evidence.confidence_band;
  return (
    <div className={`kb-evidence-card kb-evidence-${band}`}>
      <div className="kb-evidence-head">
        <span className="kb-evidence-index">[{index}]</span>
        <span className="kb-evidence-title">{evidence.title}</span>
        <span className={`kb-evidence-band kb-band-${band}`}>{CONFIDENCE_LABELS[band] || band}</span>
      </div>
      <div className="kb-evidence-excerpt">{evidence.excerpt}</div>
      <div className="kb-evidence-meta">
        {evidence.source?.filename ? (
          <span><i className="fas fa-file-lines" /> {evidence.source.filename}</span>
        ) : null}
        {evidence.source?.locator ? <span>· {evidence.source.locator}</span> : null}
        {evidence.source?.scope_label ? (
          <span className="kb-scope-chip">{evidence.source.scope_label}</span>
        ) : null}
      </div>
    </div>
  );
}

// ---------------------------- Upload tab -------------------------------

function UploadTab({ onIngestComplete }: { onIngestComplete: () => void }) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [activeJob, setActiveJob] = useState<KbIngestionJob | null>(null);

  const pickFile = () => fileInputRef.current?.click();

  const handleFile = useCallback(
    async (file: File) => {
      setUploading(true);
      setError("");
      setActiveJob(null);
      try {
        const job = await ingestKnowledgeFile(file);
        setActiveJob(job);
      } catch (err) {
        setError(extractErrorMessage(err));
      } finally {
        setUploading(false);
      }
    },
    [],
  );

  // Poll job progress until terminal state
  useEffect(() => {
    if (!activeJob || !activeJob.job_id) return;
    if (activeJob.status === "succeeded" || activeJob.status === "failed") return;

    let cancelled = false;
    const tick = async () => {
      try {
        const next = await getIngestionJobProgress(activeJob.job_id);
        if (cancelled) return;
        setActiveJob(next);
        if (next.status === "succeeded") {
          onIngestComplete();
        }
      } catch (err) {
        if (!cancelled) setError(extractErrorMessage(err));
      }
    };
    const timerId = window.setInterval(() => void tick(), 1500);
    return () => {
      cancelled = true;
      window.clearInterval(timerId);
    };
  }, [activeJob?.job_id, activeJob?.status, onIngestComplete]);

  return (
    <div className="kb-upload">
      <div
        className="kb-dropzone"
        onClick={pickFile}
        onDragOver={(event) => {
          event.preventDefault();
          event.stopPropagation();
        }}
        onDrop={(event) => {
          event.preventDefault();
          event.stopPropagation();
          const file = event.dataTransfer.files?.[0];
          if (file) void handleFile(file);
        }}
      >
        <i className="fas fa-cloud-arrow-up" />
        <div className="kb-dropzone-title">{uploading ? "上传中…" : "点击或拖拽文件到这里"}</div>
        <div className="kb-dropzone-hint">
          支持 Markdown / TXT / PDF / DOCX / XLSX / HTML / 图片 OCR · 单文件 ≤ 20 MB
        </div>
        <input
          ref={fileInputRef}
          type="file"
          style={{ display: "none" }}
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void handleFile(file);
            event.target.value = "";
          }}
          accept=".md,.txt,.pdf,.docx,.xlsx,.xlsm,.html,.htm,.png,.jpg,.jpeg,.tiff"
        />
      </div>

      {error ? (
        <div className="kb-banner kb-banner-error">
          <i className="fas fa-circle-exclamation" />
          {error}
        </div>
      ) : null}

      {activeJob ? <IngestProgressCard job={activeJob} /> : null}
    </div>
  );
}

function IngestProgressCard({ job }: { job: KbIngestionJob }) {
  const pct = Math.max(0, Math.min(100, Number(job.progress_pct ?? 0)));
  return (
    <div className="kb-ingest-card">
      <div className="kb-ingest-row">
        <i className="fas fa-file" />
        <span className="kb-ingest-filename">{job.filename}</span>
        <span className={`kb-ingest-status kb-status-${job.status}`}>{job.status}</span>
      </div>
      <div className="kb-progress">
        <div className="kb-progress-fill" style={{ width: `${pct}%` }} />
      </div>
      <div className="kb-ingest-meta">
        <span>阶段：{job.current_stage || "—"}</span>
        <span>切片数：{job.unit_count ?? 0}</span>
        {job.note ? <span>· {job.note}</span> : null}
      </div>
    </div>
  );
}

// ---------------------------- Manage tab -------------------------------

function ManageTab() {
  const [records, setRecords] = useState<KbSourceRecord[]>([]);
  const [includeArchived, setIncludeArchived] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [actionPending, setActionPending] = useState<number | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await listKnowledgeSourceRecords({
        limit: 100,
        include_archived: includeArchived,
      });
      setRecords(response.items || []);
    } catch (err) {
      setError(extractErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [includeArchived]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleArchive = useCallback(
    async (id: number) => {
      setActionPending(id);
      try {
        await archiveKnowledgeSources([id]);
        await refresh();
      } catch (err) {
        setError(extractErrorMessage(err));
      } finally {
        setActionPending(null);
      }
    },
    [refresh],
  );

  const handleUnarchive = useCallback(
    async (id: number) => {
      setActionPending(id);
      try {
        await unarchiveKnowledgeSources([id]);
        await refresh();
      } catch (err) {
        setError(extractErrorMessage(err));
      } finally {
        setActionPending(null);
      }
    },
    [refresh],
  );

  const visibleRecords = useMemo(() => records, [records]);

  return (
    <div className="kb-manage">
      <div className="kb-manage-toolbar">
        <label className="kb-toggle">
          <input
            type="checkbox"
            checked={includeArchived}
            onChange={(event) => setIncludeArchived(event.target.checked)}
          />
          显示已归档
        </label>
        <button className="kb-secondary-btn" onClick={() => void refresh()} disabled={loading}>
          <i className="fas fa-rotate" />
          {loading ? "加载中…" : "刷新"}
        </button>
        <ManualEntryButton onComplete={() => void refresh()} />
      </div>

      {error ? (
        <div className="kb-banner kb-banner-error">
          <i className="fas fa-circle-exclamation" />
          {error}
        </div>
      ) : null}

      {!visibleRecords.length && !loading ? (
        <div className="kb-empty">
          <i className="fas fa-inbox" />
          知识库里还没有资料。去「上传」标签页上传第一份吧。
        </div>
      ) : null}

      {visibleRecords.length ? (
        <div className="kb-table">
          <div className="kb-table-head">
            <span>文件名</span>
            <span>类型</span>
            <span>归属</span>
            <span>上传时间</span>
            <span>状态</span>
            <span style={{ textAlign: "right" }}>操作</span>
          </div>
          {visibleRecords.map((record) => (
            <div key={record.id} className="kb-table-row">
              <span className="kb-table-filename" title={record.filename}>
                <i className="fas fa-file-lines" /> {record.display_title || record.filename}
              </span>
              <span>{record.source_type}</span>
              <span className="kb-scope-chip">
                {SCOPE_LABELS[record.source_scope] || record.source_scope}
              </span>
              <span>{formatTimestamp(record.uploaded_at)}</span>
              <span>
                {record.archived_at ? (
                  <span className="kb-archived">已归档</span>
                ) : (
                  <span className="kb-active">在用</span>
                )}
              </span>
              <span style={{ textAlign: "right" }}>
                {record.archived_at ? (
                  <button
                    className="kb-link-btn"
                    onClick={() => void handleUnarchive(record.id)}
                    disabled={actionPending === record.id}
                  >
                    {actionPending === record.id ? "…" : "恢复"}
                  </button>
                ) : (
                  <button
                    className="kb-link-btn kb-link-danger"
                    onClick={() => void handleArchive(record.id)}
                    disabled={actionPending === record.id}
                  >
                    {actionPending === record.id ? "…" : "归档"}
                  </button>
                )}
              </span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ManualEntryButton({ onComplete }: { onComplete: () => void }) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const submit = useCallback(async () => {
    if (!title.trim() || !content.trim()) {
      setError("标题和内容都得填");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      await manualEntryKnowledge({ title: title.trim(), content: content.trim() });
      setTitle("");
      setContent("");
      setOpen(false);
      onComplete();
    } catch (err) {
      setError(extractErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }, [content, onComplete, title]);

  if (!open) {
    return (
      <button className="kb-secondary-btn" onClick={() => setOpen(true)}>
        <i className="fas fa-plus" />
        手动录入
      </button>
    );
  }

  return (
    <div className="kb-manual-entry">
      <input
        className="kb-input"
        placeholder="标题（≤120 字符）"
        value={title}
        onChange={(event) => setTitle(event.target.value)}
        maxLength={120}
      />
      <textarea
        className="kb-textarea"
        placeholder="内容（≤50KB）"
        value={content}
        onChange={(event) => setContent(event.target.value)}
        rows={6}
      />
      {error ? <div className="kb-inline-error">{error}</div> : null}
      <div className="kb-manual-actions">
        <button className="kb-link-btn" onClick={() => setOpen(false)} disabled={submitting}>
          取消
        </button>
        <button className="kb-primary-btn" onClick={() => void submit()} disabled={submitting}>
          {submitting ? "提交中…" : "保存"}
        </button>
      </div>
    </div>
  );
}
