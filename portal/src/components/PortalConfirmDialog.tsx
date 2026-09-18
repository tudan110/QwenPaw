type PortalConfirmDialogProps = {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  confirmIconClass?: string;
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
  submitting = false,
  onClose,
  onConfirm,
}: PortalConfirmDialogProps) {
  if (!open) {
    return null;
  }

  return (
    <div className="history-modal show" onClick={onClose}>
      <div
        className="history-content portal-confirm-dialog"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="history-header">
          <h3>
            <i className="fas fa-triangle-exclamation" /> {title}
          </h3>
          <button type="button" className="history-close" onClick={onClose} disabled={submitting}>
            <i className="fas fa-times" />
          </button>
        </div>
        <div className="history-body portal-confirm-body">
          <div className="portal-confirm-copy">{message}</div>
          <div className="portal-model-form-actions portal-confirm-actions">
            <button
              type="button"
              className="portal-model-btn secondary"
              disabled={submitting}
              onClick={onClose}
            >
              取消
            </button>
            <button
              type="button"
              className="portal-model-btn secondary danger"
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
