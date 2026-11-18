# 生产模式 PDF / Word 导出修复验证

## 根因

原 report-export 技能只负责归档已有文件，默认 Markdown；PDF/Word 依赖模型另写生成脚本。生产策略禁止动态脚本、通用文件写入，且默认脚本列表也没有 save_report.py。因此不能仅给截图中的临时脚本加白名单来修复。截图中的“Markdown 总能导出”也不是默认策略保证。

下载接口本身已经支持 PDF、DOCX 和附件响应，门户也已识别报告 URL 并显示下载按钮。

## 修改

- 新增默认启用的内建 export_report 工具，仅接受正文、标题和 pdf/docx/md 格式。默认 PDF；Word 用 docx；明确请求 Markdown 才使用 md。
- 由服务端确定当前 agent 和归档目录，复用 python-docx 与镜像现有 LibreOffice Writer、中文字体。不执行模型生成的代码、不读取用户指定文件、不加载外部图片或 HTML。
- 生产策略只增加这个受控产物工具，不放开 write_file、shell 或旧归档脚本。支持基本标题、列表、表格和代码块；复杂图表及 Markdown 内联标记不保证原样排版。
- 输入限制为 1 MB、5000 行、表格总计 2000 单元格；PDF 转换采用固定二进制、独立临时 profile、60 秒超时。产物以唯一文件名发布，失败清理。
- 更新 gateway、fault、inspection 的技能说明与元数据。镜像构建新增真实 DOCX/PDF 生成检查，缺依赖或转换失败会阻断构建。

## 验证

使用临时 Python 测试环境运行：

```sh
python -m pytest --noconftest tests/unit/extensions/test_report_export.py tests/unit/extensions/test_report_export_flow.py -q
```

提交前重新执行：29 项测试通过。故障工作区原有导出触发和完整聊天报告约束已保留。

测试包含真实中文 DOCX/PDF 生成与解析、表格、生产普通身份策略、真实工具调用与 FastAPI 下载、MIME/attachment、输入及符号链接拒绝、失败清理、默认 PDF 和工具注册。集成测试替换无关模型运行时与身份服务，不调用真实 SSO；PDF 使用本机 LibreOffice 实转。--noconftest 避免加载缺少依赖的全仓库 fixture；不是全仓测试通过声明。

另在现有 test_production_business_reads.py 添加生产策略回归；当前轻量环境未运行该完整测试文件。未构建生产 Linux 镜像，未在目标环境使用登录会话生成或下载报告。

## 发布与现场验收

需构建并部署包含本次修改的新镜像，启动时按既有受管种子同步机制更新技能，重新创建/加载 Agent 工具集。不得仅拷贝新技能说明到没有 export_report 工具的旧后端。

普通测试账号保持 QWENPAW_PRODUCTION_GUARDS=true，分别请求“导出这份报告”“导出 Word”“导出 Markdown”，核对默认 PDF、真实 DOCX、明确 Markdown 以及下载文件内容。再核对动态脚本仍被拒绝。失败应展示真实错误，不应降级 Markdown 或要求用户维护临时白名单。

报告沿用既有 agent 级共享归档与鉴权下载语义，不是用户私有文件。没有新增跨用户隔离承诺。本次验证未部署或改变线上安全配置。
