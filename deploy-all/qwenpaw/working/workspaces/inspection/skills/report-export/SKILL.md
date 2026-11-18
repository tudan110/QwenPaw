---
name: report-export
description: 用户明确要求下载或导出报告时使用。调用内建 export_report，默认生成 PDF，支持 Word（docx）和 Markdown（md）；生产模式无需临时脚本或白名单申请。
---

# 报告导出与下载

只有用户明确要求下载、导出或文件交付时才执行；普通分析和通知仍在聊天中交付完整正文。

## 工作流程

1. 根据已有会话和真实证据整理完整报告正文，不重新查询或编造数据。
2. 直接调用内建 `export_report` 工具，把正文传入 `content`，简短主题传入 `title`：
   - 未指定格式：`format="pdf"`。
   - PDF：`format="pdf"`；Word：`format="docx"`。
   - 仅用户明确要求 Markdown 时使用 `format="md"`。
   - 用户同时要 PDF 和 Word 时，复用相同正文分别调用两次。
3. 将工具成功返回的下载链接原样放进最终回复，不自行拼接链接。PDF 和 Word 可直接下载。

## 生产模式要求

- PDF/Word 由内建固定渲染器生成并归档，无需先 `write_file`、执行 shell、动态编写 Python 或安装依赖。
- 不执行临时生成脚本，不申请放开通用 shell，不把旧 `save_report.py` 当成生产默认入口。
- 支持中文正文、基本 Markdown 标题、列表、表格与代码块；外链、图片、HTML 不抓取或执行。复杂图表不承诺原样排版。
- 工具失败时报告真实错误；不得谎称已生成，不得未经用户同意降级为 Markdown。
- Excel/PPT 不在此内建工具的生成范围；已有对应文件的归档流程仅在实际授权可执行时使用，不把 PDF/Word 的支持扩大为所有 Office 格式。
- 老版本没有 `export_report` 时说明需要升级平台；不要让用户维护临时白名单脚本。
