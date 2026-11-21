"""Pre-dispatch rules for export paths without authoritative row counts."""

MESSAGE = (
    "导出策略已拦截：此工具无法核验业务数据条数或执行导出确认，未生成文件。"
    "请使用该业务的受控导出入口；没有受控入口时不能导出明细。"
    "不要更换工具、文件格式或拆分请求继续导出。"
)
_UNCONTROLLED = {
    "export_report", "send_file_to_user", "write_file", "append_file", "edit_file",
}


def require_controlled_export(tool: str, operation: object = None) -> None:
    from .execution_policy import enabled

    if not enabled():
        return
    if tool in _UNCONTROLLED or (tool == "process_office_document" and operation != "inspect"):
        raise PermissionError(MESSAGE)
