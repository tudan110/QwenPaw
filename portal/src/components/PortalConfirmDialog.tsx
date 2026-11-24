type PortalConfirmDialogProps = {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  confirmIconClass?: string;
  cancelLabel?: string;
  danger?: boolean;
  notice?: string;
  submitting?: boolean;
  onClose: () => void;
  onConfirm: () => void;
};

export default function PortalConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "确认删除",
  confirmIconClass = "fa-trash-can",
  cancelLabel = "取消",
  danger = true,
  notice,
  submitting = false,
  onClose,
  onConfirm,
}: PortalConfirmDialogProps) {
  if (!open) {
    return null;
  }

  return (
    <div className="history-modal show" onClick={() => { if (!submitting) onClose(); }}>
      <div
        className="history-content portal-confirm-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="history-header">
          <h3>
            <i className="fas fa-triangle-exclamation" /> {title}
          </h3>
          <button type="button" className="history-close" aria-label="关闭确认弹窗" onClick={onClose} disabled={submitting}>
            <i className="fas fa-times" />
          </button>
        </div>
        <div className="history-body portal-confirm-body">
          <div className="portal-confirm-copy">{message}</div>
          {notice ? <div className="model-inline-notice error" role="alert">{notice}</div> : null}
          <div className="portal-model-form-actions portal-confirm-actions">
            <button
              type="button"
              className="portal-model-btn secondary"
              disabled={submitting}
              onClick={onClose}
            >
              {cancelLabel}
            </button>
            <button
              type="button"
              className={danger ? "portal-model-btn secondary danger" : "portal-model-btn"}
              disabled={submitting}
              onClick={onConfirm}
            >
              <i className={`fas ${submitting ? "fa-spinner fa-spin" : confirmIconClass}`} />
              {confirmLabel}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
