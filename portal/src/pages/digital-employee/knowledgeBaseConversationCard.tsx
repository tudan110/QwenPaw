import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import {
  createKnowledgeManualEntry,
  getKnowledgeIngestProgress,
  uploadKnowledgeFile,
  type KnowledgeIngestJob,
} from "../../api/knowledgeBase";
import "./knowledge-base-conversation.css";

type KnowledgeBaseFlow = {
  flowId?: string;
  mode?: "search" | "upload" | "manual";
  status?: "idle" | "running" | "completed" | "error";
  error?: string;
  fileName?: string;
  fileSize?: number;
  job?: KnowledgeIngestJob;
  manualTitle?: string;
  manualContent?: string;
  autoRun?: boolean;
};

type KnowledgeBaseConversationCardProps = {
  message: {
    id: string;
    knowledgeBaseFlow?: KnowledgeBaseFlow;
  };
  onFlowUpdate?: (messageId: string, patch: Partial<KnowledgeBaseFlow>) => void;
  onManagementOpen?: () => void;
};

function formatFileSize(size?: number) {
  if (!size) {
    return "";
  }
  if (size < 1024 * 1024) {
    return `${Math.max(1, Math.round(size / 1024))} KB`;
  }
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function getJobId(job?: KnowledgeIngestJob) {
  return String(job?.job_id || job?.id || "").trim();
}

function isSuccessfulJob(job?: KnowledgeIngestJob) {
  const status = String(job?.status || "").toLowerCase();
  const stage = String(job?.current_stage || "").toLowerCase();
  const pct = Number(job?.progress_pct || 0);
  return ["completed", "success", "done", "finished"].includes(status)
    || ["completed", "success", "done", "finished"].includes(stage)
    || pct >= 100;
}

function isFailedJob(job?: KnowledgeIngestJob) {
  const status = String(job?.status || "").toLowerCase();
  const stage = String(job?.current_stage || "").toLowerCase();
  return ["failed", "error"].includes(status) || ["failed", "error"].includes(stage);
}

export function KnowledgeBaseConversationCard({
  message,
  onFlowUpdate,
  onManagementOpen,
}: KnowledgeBaseConversationCardProps) {
  const flow = message.knowledgeBaseFlow || {};
  const initialMode = flow.mode === "manual" ? "manual" : "upload";
  const [mode, setMode] = useState<"upload" | "manual">(initialMode);
  const [manualTitle, setManualTitle] = useState(flow.manualTitle || "");
  const [manualContent, setManualContent] = useState(flow.manualContent || "");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isDraggingFile, setIsDraggingFile] = useState(false);
  const [localError, setLocalError] = useState("");
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const jobId = getJobId(flow.job);
  const isRunning = flow.status === "running";

  const statusLabel = useMemo(() => {
    if (flow.status === "running") {
      return mode === "upload" ? "导入中" : "沉淀中";
    }
    if (flow.status === "completed") {
      return "已完成";
    }
    if (flow.status === "error") {
      return "需要处理";
    }
    return "等待操作";
  }, [flow.status, mode]);

  const updateFlow = (patch: Partial<KnowledgeBaseFlow>) => {
    onFlowUpdate?.(message.id, patch);
  };

  const switchMode = (nextMode: "upload" | "manual") => {
    setMode(nextMode);
    setLocalError("");
    updateFlow({ mode: nextMode, error: "", status: "idle" });
  };

  const selectFile = useCallback((file: File | null) => {
    setLocalError("");
    setSelectedFile(file);
    updateFlow({
      mode: "upload",
      status: "idle",
      fileName: file?.name || "",
      fileSize: file?.size || 0,
      job: undefined,
      error: "",
    });
  }, []);

  const handleDropFile = useCallback((event: DragEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.stopPropagation();
    setIsDraggingFile(false);
    const file = event.dataTransfer.files?.[0] || null;
    selectFile(file);
  }, [selectFile]);

  const handleUpload = async () => {
    if (!selectedFile) {
      setLocalError("请先选择要导入的文档");
      return;
    }
    setLocalError("");
    updateFlow({
      mode: "upload",
      status: "running",
      error: "",
      fileName: selectedFile.name,
      fileSize: selectedFile.size,
    });
    try {
      const job = await uploadKnowledgeFile(selectedFile);
      updateFlow({
        status: isSuccessfulJob(job) ? "completed" : "running",
        job,
      });
    } catch (error) {
      const messageText = error instanceof Error ? error.message : "文档导入失败";
      updateFlow({ status: "error", error: messageText });
      setLocalError(messageText);
    }
  };

  const handleManualEntry = async () => {
    const title = manualTitle.trim();
    const content = manualContent.trim();
    if (!title || !content) {
      setLocalError("请填写标题和知识内容");
      return;
    }
    setLocalError("");
    updateFlow({
      mode: "manual",
      status: "running",
      error: "",
      manualTitle: title,
      manualContent: content,
    });
    try {
      await createKnowledgeManualEntry({ title, content });
      updateFlow({ status: "completed", error: "" });
    } catch (error) {
      const messageText = error instanceof Error ? error.message : "知识沉淀失败";
      updateFlow({ status: "error", error: messageText });
      setLocalError(messageText);
    }
  };

  useEffect(() => {
    if (!jobId || mode !== "upload" || flow.status !== "running") {
      return undefined;
    }

    let cancelled = false;
    const timer = window.setInterval(async () => {
      try {
        const progress = await getKnowledgeIngestProgress(jobId);
        if (cancelled) {
          return;
        }
        const nextStatus = isSuccessfulJob(progress) ? "completed" : "running";
        updateFlow({ job: progress, status: nextStatus });
        if (isSuccessfulJob(progress) || isFailedJob(progress)) {
          if (isFailedJob(progress)) {
            updateFlow({
              status: "error",
              error: progress.note || "文档导入失败",
              job: progress,
            });
          }
          window.clearInterval(timer);
        }
      } catch (error) {
        if (!cancelled) {
          updateFlow({
            status: "error",
            error: error instanceof Error ? error.message : "导入进度查询失败",
          });
        }
        window.clearInterval(timer);
      }
    }, 1800);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [flow.status, jobId, mode]);

  const progressPct = Math.max(0, Math.min(100, Number(flow.job?.progress_pct || 0)));
  const visibleError = localError || flow.error || "";
  const uploadCompleted = flow.status === "completed" && mode === "upload";
  const hasPickedFile = Boolean(selectedFile || flow.fileName);

  return (
    <div className="knowledge-conversation-card">
      <div className="knowledge-upload-steps" aria-label="知识入库流程">
        <span className="active"><b>1</b>选择文件</span>
        <span className={flow.job ? "active" : ""}><b>2</b>解析入库</span>
        <span className={uploadCompleted ? "active" : ""}><b>3</b>后续查询</span>
      </div>

      <div className="knowledge-conversation-header">
        <div>
          <strong>{mode === "upload" ? "上传新知识" : "手动沉淀知识"}</strong>
          <span>{mode === "upload" ? "支持 Markdown、PDF、图片、Excel、Word，系统会自动切片入库。" : "把已确认的经验、SOP 或处置结论保存为可检索知识。"}</span>
        </div>
        <span className={`knowledge-status-pill ${flow.status || "idle"}`}>{statusLabel}</span>
      </div>

      <div className="knowledge-mode-tabs compact" role="tablist" aria-label="知识库操作">
        <button type="button" className={mode === "upload" ? "active" : ""} onClick={() => switchMode("upload")}>
          <i className="fas fa-file-arrow-up" />
          导入
        </button>
        <button type="button" className={mode === "manual" ? "active" : ""} onClick={() => switchMode("manual")}>
          <i className="fas fa-pen-to-square" />
          沉淀
        </button>
      </div>

      {mode === "upload" ? (
        <div className="knowledge-card-section">
          <input
            ref={fileInputRef}
            type="file"
            className="knowledge-file-input"
            onChange={(event) => {
              const file = event.target.files?.[0] || null;
              selectFile(file);
            }}
          />
          <button
            type="button"
            className={isDraggingFile ? "knowledge-upload-drop drag-active" : "knowledge-upload-drop"}
            onClick={() => fileInputRef.current?.click()}
            onDragEnter={(event) => {
              event.preventDefault();
              setIsDraggingFile(true);
            }}
            onDragOver={(event) => {
              event.preventDefault();
              event.dataTransfer.dropEffect = "copy";
              setIsDraggingFile(true);
            }}
            onDragLeave={() => setIsDraggingFile(false)}
            onDrop={handleDropFile}
          >
            <i className={`fas ${uploadCompleted ? "fa-circle-check" : "fa-cloud-arrow-up"}`} />
            <span>{selectedFile?.name || flow.fileName || "拖拽或选择文件"}</span>
            <small>
              {formatFileSize(selectedFile?.size || flow.fileSize)
                || "导入完成后，内容会直接进入知识库检索和资料预览。"}
            </small>
          </button>
          <div className="knowledge-card-actions">
            <button type="button" className="secondary" onClick={() => fileInputRef.current?.click()} disabled={isRunning}>
              选择文件
            </button>
            <button type="button" onClick={() => void handleUpload()} disabled={isRunning || uploadCompleted}>
              <i className={`fas ${isRunning ? "fa-spinner fa-spin" : uploadCompleted ? "fa-check" : "fa-file-import"}`} />
              {isRunning ? "导入中" : uploadCompleted ? "导入完成" : "开始导入"}
            </button>
            {uploadCompleted && onManagementOpen ? (
              <button type="button" className="secondary" onClick={onManagementOpen}>
                <i className="fas fa-table-list" />
                去知识库管理查看
              </button>
            ) : null}
          </div>
          <div className="knowledge-flow-panel">
            <strong>入库流程</strong>
            <div className="knowledge-flow-step done"><span>1</span>选择文件<em>{hasPickedFile ? "完成" : "待选择"}</em></div>
            <div className={`knowledge-flow-step ${flow.job ? "done" : ""}`}><span>2</span>自动解析与切片<em>{flow.job ? "完成" : "等待"}</em></div>
            <div className={`knowledge-flow-step ${uploadCompleted ? "done" : ""}`}><span>3</span>写入知识库供后续查询<em>{uploadCompleted ? "可查询" : "等待"}</em></div>
          </div>
          {flow.job ? (
            <div className="knowledge-progress">
              <div className="knowledge-progress-meta">
                <span>{uploadCompleted ? "已完成" : flow.job.current_stage || flow.job.status || "处理中"}</span>
                <strong>{progressPct}%</strong>
              </div>
              <div className="knowledge-progress-track">
                <span style={{ width: `${progressPct}%` }} />
              </div>
              {flow.job.unit_count ? <p>已解析知识单元：{flow.job.unit_count}</p> : null}
            </div>
          ) : null}
          <div className="knowledge-upload-effect">
            <strong>上传后会看到什么</strong>
            <p>解析说明、切片数量和后续检索效果会在这里持续更新。</p>
          </div>
        </div>
      ) : null}

      {mode === "manual" ? (
        <div className="knowledge-card-section">
          <input
            value={manualTitle}
            placeholder="知识标题"
            onChange={(event) => setManualTitle(event.target.value)}
          />
          <textarea
            value={manualContent}
            rows={5}
            placeholder="输入要沉淀的经验、SOP 或处置结论"
            onChange={(event) => setManualContent(event.target.value)}
          />
          <div className="knowledge-card-actions">
            <button type="button" onClick={() => void handleManualEntry()} disabled={isRunning || flow.status === "completed"}>
              <i className={`fas ${isRunning ? "fa-spinner fa-spin" : "fa-check"}`} />
              保存到知识库
            </button>
            {flow.status === "completed" && onManagementOpen ? (
              <button type="button" className="secondary" onClick={onManagementOpen}>
                <i className="fas fa-table-list" />
                去知识库管理查看
              </button>
            ) : null}
          </div>
        </div>
      ) : null}

      {visibleError ? (
        <div className="knowledge-card-error">
          <i className="fas fa-triangle-exclamation" />
          {visibleError}
        </div>
      ) : null}
    </div>
  );
}
