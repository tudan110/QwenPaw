import { startTransition, useEffect, useMemo, useState } from "react";
import ReactECharts from "echarts-for-react";
import {
  getResourceImportMetadata,
  previewResourceImport,
  submitResourceImport,
} from "../../api/resourceImport";
import type {
  ResourceImportGroup,
  ResourceImportMetadata,
  ResourceImportPreview,
  ResourceImportRecord,
  ResourceImportRelation,
  ResourceImportResult,
} from "../../types/resourceImport";
import "./resource-import.css";

const IMPORT_TEMPLATE_HEADERS = [
  "name",
  "ci_type",
  "private_ip",
  "status",
  "department",
  "product",
  "project",
  "idc",
  "server_room",
  "rack",
  "host_name",
  "os_version",
  "vendor",
  "model",
  "description",
];

const STEP_ITEMS = [
  { id: "upload", index: 1, title: "上传文件", desc: "多文件接入与模板校验" },
  { id: "parse", index: 2, title: "智能解析", desc: "字段映射与清洗标准化" },
  { id: "confirm", index: 3, title: "确认补全", desc: "编辑资源与生成层级节点" },
  { id: "topology", index: 4, title: "拓扑验证", desc: "审阅 AI 推断关系" },
  { id: "import", index: 5, title: "导入 CMDB", desc: "执行落库并返回结果" },
] as const;

function extractErrorMessage(error: unknown) {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error || "");
}

function buildTemplateFile() {
  const content = `${IMPORT_TEMPLATE_HEADERS.join(",")}\n`;
  const blob = new Blob([content], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "cmdb-resource-import-template.csv";
  anchor.click();
  URL.revokeObjectURL(url);
}

function countSelectedRecords(groups: ResourceImportGroup[]) {
  return groups.reduce(
    (total, group) => total + group.records.filter((record) => record.selected).length,
    0,
  );
}

export function ResourceImportPanel() {
  const [metadata, setMetadata] = useState<ResourceImportMetadata | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [preview, setPreview] = useState<ResourceImportPreview | null>(null);
  const [resourceGroups, setResourceGroups] = useState<ResourceImportGroup[]>([]);
  const [relations, setRelations] = useState<ResourceImportRelation[]>([]);
  const [result, setResult] = useState<ResourceImportResult | null>(null);
  const [selectedType, setSelectedType] = useState("");
  const [loading, setLoading] = useState(false);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    let cancelled = false;
    void getResourceImportMetadata()
      .then((response) => {
        if (!cancelled) {
          setMetadata(response);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(extractErrorMessage(err) || "加载 CMDB 模板失败");
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!resourceGroups.length) {
      setSelectedType("");
      return;
    }
    if (!selectedType || !resourceGroups.some((group) => group.ciType === selectedType)) {
      setSelectedType(resourceGroups[0].ciType);
    }
  }, [resourceGroups, selectedType]);

  const activeGroup = useMemo(
    () => resourceGroups.find((group) => group.ciType === selectedType) || null,
    [resourceGroups, selectedType],
  );

  const recordMap = useMemo(() => {
    const map = new Map<string, ResourceImportRecord>();
    resourceGroups.forEach((group) => {
      group.records.forEach((record) => map.set(record.previewKey, record));
    });
    return map;
  }, [resourceGroups]);

  const chartOption = useMemo(() => {
    const selectedRecords = resourceGroups
      .flatMap((group) => group.records)
      .filter((record) => record.selected);
    const nodes = selectedRecords.map((record) => ({
      id: record.previewKey,
      name: record.name,
      category: record.category,
      symbolSize: record.generated ? 36 : 44,
      value: record.ciType,
    }));
    const links = relations
      .filter((relation) => relation.selected)
      .map((relation) => ({
        source: relation.sourceKey,
        target: relation.targetKey,
        value: relation.relationType,
        label: { show: true, formatter: relation.relationType },
        lineStyle: {
          opacity: relation.confidence === "high" ? 0.95 : relation.confidence === "medium" ? 0.72 : 0.5,
          width: relation.confidence === "high" ? 2 : 1,
        },
      }));

    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "item",
        formatter: (params: any) =>
          params.dataType === "edge"
            ? `${params.data.value}: ${recordMap.get(params.data.source)?.name || params.data.source} → ${recordMap.get(params.data.target)?.name || params.data.target}`
            : `${params.data.name}<br/>${params.data.value}`,
      },
      legend: [
        {
          bottom: 0,
          textStyle: { color: "#9fb3c8" },
          data: ["business", "resource", "dcim", "ipam"],
        },
      ],
      series: [
        {
          type: "graph",
          layout: "force",
          roam: true,
          draggable: true,
          force: {
            repulsion: 260,
            edgeLength: 130,
          },
          categories: [
            { name: "business" },
            { name: "resource" },
            { name: "dcim" },
            { name: "ipam" },
          ],
          label: {
            show: true,
            color: "#d8e5f2",
            fontSize: 12,
          },
          itemStyle: {
            borderColor: "rgba(255,255,255,0.16)",
            borderWidth: 1,
          },
          lineStyle: {
            color: "source",
            curveness: 0.12,
          },
          data: nodes,
          links,
        },
      ],
      color: ["#5dd6b3", "#5aa7ff", "#ff9d5c", "#d68bff"],
    };
  }, [recordMap, relations, resourceGroups]);

  const selectedRecordCount = useMemo(
    () => countSelectedRecords(resourceGroups),
    [resourceGroups],
  );
  const selectedRelationCount = useMemo(
    () => relations.filter((relation) => relation.selected).length,
    [relations],
  );
  const currentStep = result ? 5 : preview ? 4 : files.length ? 2 : 1;

  const handleFiles = (nextFiles: FileList | File[] | null) => {
    if (!nextFiles) {
      return;
    }
    const normalized = Array.from(nextFiles).filter((file) => file.size > 0);
    setFiles((previous) => {
      const existing = new Map(previous.map((file) => [`${file.name}:${file.size}`, file]));
      normalized.forEach((file) => existing.set(`${file.name}:${file.size}`, file));
      return Array.from(existing.values());
    });
    setNotice("");
    setError("");
  };

  const handlePreview = async () => {
    if (!files.length) {
      setError("请先上传至少一个资源文件");
      return;
    }
    setLoading(true);
    setError("");
    setNotice("");
    setResult(null);
    try {
      const nextPreview = await previewResourceImport(files);
      startTransition(() => {
        setPreview(nextPreview);
        setResourceGroups(nextPreview.resourceGroups);
        setRelations(nextPreview.relations);
      });
      setNotice("AI 解析完成，已经生成字段映射、清洗结果和拓扑草案。");
    } catch (err) {
      setError(extractErrorMessage(err) || "资源解析失败");
    } finally {
      setLoading(false);
    }
  };

  const handleReset = () => {
    setFiles([]);
    setPreview(null);
    setResourceGroups([]);
    setRelations([]);
    setResult(null);
    setNotice("");
    setError("");
  };

  const updateRecord = (
    previewKey: string,
    updater: (record: ResourceImportRecord) => ResourceImportRecord,
  ) => {
    setResourceGroups((current) =>
      current.map((group) => ({
        ...group,
        records: group.records.map((record) =>
          record.previewKey === previewKey ? updater(record) : record,
        ),
      })),
    );
  };

  const updateRelation = (
    targetRelation: ResourceImportRelation,
    updater: (relation: ResourceImportRelation) => ResourceImportRelation,
  ) => {
    setRelations((current) =>
      current.map((relation) =>
        relation.sourceKey === targetRelation.sourceKey
        && relation.targetKey === targetRelation.targetKey
        && relation.relationType === targetRelation.relationType
          ? updater(relation)
          : relation,
      ),
    );
  };

  const handleImport = async () => {
    if (!resourceGroups.length) {
      setError("当前没有可导入的资源草案");
      return;
    }
    setImporting(true);
    setError("");
    setNotice("");
    try {
      const response = await submitResourceImport({
        resourceGroups,
        relations,
      });
      setResult(response);
      setNotice(response.status === "success" ? "资源导入完成。" : "导入已执行，但存在部分失败项。");
    } catch (err) {
      setError(extractErrorMessage(err) || "资源导入失败");
    } finally {
      setImporting(false);
    }
  };

  return (
    <div className="resource-import-panel">
      <div className="resource-import-hero">
        <div>
          <p className="resource-import-eyebrow">CMDB Resource Intake</p>
          <h2>智能导入资源清单</h2>
          <p className="resource-import-summary">
            围绕 veops-cmdb 模型做文件解析、字段映射、数据清洗、拓扑推断与批量入库。
          </p>
        </div>
        <div className="resource-import-hero-actions">
          <button type="button" className="resource-import-secondary" onClick={buildTemplateFile}>
            下载模板
          </button>
          <button
            type="button"
            className="resource-import-primary"
            onClick={handlePreview}
            disabled={loading || !files.length}
          >
            {loading ? "解析中..." : "开始智能解析"}
          </button>
        </div>
      </div>

      <div className="resource-import-status-bar">
        <span className={metadata?.connected ? "resource-status-badge live" : "resource-status-badge"}>
          {metadata?.connected ? "已接入实时 CMDB 模板" : "默认模板模式"}
        </span>
        <span className="resource-status-copy">
          {metadata?.message || "正在加载 CMDB 模型元数据..."}
        </span>
      </div>

      {notice ? <div className="resource-import-notice">{notice}</div> : null}
      {error ? <div className="resource-import-error">{error}</div> : null}

      <div className="resource-import-workspace">
        <aside className="resource-import-rail">
          <div className="resource-import-step-stack">
            {STEP_ITEMS.map((step) => (
              <div
                key={step.id}
                className={step.index <= currentStep ? "resource-step active" : "resource-step"}
              >
                <span className="resource-step-index">{step.index}</span>
                <div>
                  <strong>{step.title}</strong>
                  <p>{step.desc}</p>
                </div>
              </div>
            ))}
          </div>

          <div
            className="resource-upload-zone"
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => {
              event.preventDefault();
              handleFiles(event.dataTransfer.files);
            }}
          >
            <div className="resource-upload-copy">
              <strong>拖拽文件到此处</strong>
              <p>支持 {metadata?.supportedFormats?.join(" / ") || ".csv / .xlsx / .docx"}</p>
            </div>
            <label className="resource-import-secondary resource-file-trigger">
              选择文件
              <input
                type="file"
                hidden
                multiple
                accept={metadata?.supportedFormats?.join(",")}
                onChange={(event) => handleFiles(event.target.files)}
              />
            </label>
          </div>

          <div className="resource-file-list">
            {files.length ? (
              files.map((file) => (
                <div key={`${file.name}:${file.size}`} className="resource-file-item">
                  <div>
                    <strong>{file.name}</strong>
                    <p>{(file.size / 1024).toFixed(1)} KB</p>
                  </div>
                  <button
                    type="button"
                    className="resource-file-remove"
                    onClick={() =>
                      setFiles((current) => current.filter((item) => item !== file))
                    }
                  >
                    ×
                  </button>
                </div>
              ))
            ) : (
              <div className="resource-file-empty">当前还没有上传文件</div>
            )}
          </div>

          <div className="resource-rail-actions">
            <button type="button" className="resource-import-secondary" onClick={handleReset}>
              清空草案
            </button>
            <button
              type="button"
              className="resource-import-primary"
              onClick={handleImport}
              disabled={importing || !resourceGroups.length}
            >
              {importing ? "导入中..." : "确认导入 CMDB"}
            </button>
          </div>
        </aside>

        <section className="resource-import-main">
          <div className="resource-metric-strip">
            <div>
              <span>已选资源</span>
              <strong>{selectedRecordCount}</strong>
            </div>
            <div>
              <span>拓扑关系</span>
              <strong>{selectedRelationCount}</strong>
            </div>
            <div>
              <span>质量评分</span>
              <strong>{preview?.summary.qualityScore ?? "--"}%</strong>
            </div>
            <div>
              <span>待确认</span>
              <strong>{preview?.summary.needsConfirmation ?? "--"}</strong>
            </div>
          </div>

          <div className="resource-insight-grid">
            <section className="resource-section">
              <div className="resource-section-header">
                <div>
                  <h3>字段映射</h3>
                  <p>展示本次文件识别出的表头到 CMDB 标准字段的映射结果。</p>
                </div>
              </div>
              <div className="resource-chip-grid">
                {preview?.mappingSummary?.length ? (
                  preview.mappingSummary.slice(0, 12).map((item) => (
                    <div key={`${item.sourceField}-${item.targetField}`} className="resource-chip-card">
                      <strong>{item.sourceField}</strong>
                      <span>{item.targetField}</span>
                      <small>{item.count} 次</small>
                    </div>
                  ))
                ) : (
                  <div className="resource-empty-state">上传后展示字段映射结果</div>
                )}
              </div>
            </section>

            <section className="resource-section">
              <div className="resource-section-header">
                <div>
                  <h3>清洗报告</h3>
                  <p>标准化 IP、状态、类型，并自动补齐可推断字段。</p>
                </div>
              </div>
              <div className="resource-cleaning-list">
                {preview?.cleaningSummary?.length ? (
                  preview.cleaningSummary.map((item) => (
                    <div key={item.label} className="resource-cleaning-item">
                      <span>{item.label}</span>
                      <strong>{item.count}</strong>
                    </div>
                  ))
                ) : (
                  <div className="resource-empty-state">等待解析生成清洗统计</div>
                )}
              </div>
            </section>
          </div>

          <div className="resource-editor-layout">
            <section className="resource-section resource-group-panel">
              <div className="resource-section-header">
                <div>
                  <h3>资源分组</h3>
                  <p>按推断后的 CMDB 模型拆分上传清单与自动生成节点。</p>
                </div>
              </div>
              <div className="resource-group-list">
                {resourceGroups.length ? (
                  resourceGroups.map((group) => (
                    <button
                      key={group.ciType}
                      type="button"
                      className={group.ciType === selectedType ? "resource-group-item active" : "resource-group-item"}
                      onClick={() => setSelectedType(group.ciType)}
                    >
                      <strong>{group.label}</strong>
                      <span>{group.ciType}</span>
                      <small>{group.records.length} 条</small>
                    </button>
                  ))
                ) : (
                  <div className="resource-empty-state">解析后会按模型生成资源分组</div>
                )}
              </div>
            </section>

            <section className="resource-section resource-record-panel">
              <div className="resource-section-header">
                <div>
                  <h3>可编辑资源表</h3>
                  <p>针对当前模型修正名称、IP、状态与是否纳入本次导入。</p>
                </div>
              </div>
              {activeGroup ? (
                <div className="resource-record-table">
                  <div className="resource-record-head">
                    <span>导入</span>
                    <span>名称</span>
                    <span>类型</span>
                    <span>IP / 状态</span>
                    <span>来源</span>
                  </div>
                  {activeGroup.records.map((record) => (
                    <div key={record.previewKey} className="resource-record-row">
                      <label className="resource-check">
                        <input
                          type="checkbox"
                          checked={record.selected}
                          onChange={(event) =>
                            updateRecord(record.previewKey, (current) => ({
                              ...current,
                              selected: event.target.checked,
                            }))
                          }
                        />
                      </label>
                      <div className="resource-record-editors">
                        <input
                          value={record.name}
                          onChange={(event) =>
                            updateRecord(record.previewKey, (current) => ({
                              ...current,
                              name: event.target.value,
                              attributes: {
                                ...current.attributes,
                                name: event.target.value,
                              },
                            }))
                          }
                        />
                        <small>{record.generated ? "系统补全节点" : "来自上传文件"}</small>
                      </div>
                      <div className="resource-record-type">
                        <select
                          value={record.ciType}
                          onChange={(event) =>
                            updateRecord(record.previewKey, (current) => ({
                              ...current,
                              ciType: event.target.value,
                            }))
                          }
                        >
                          {(metadata?.ciTypes || []).map((item) => (
                            <option key={item.name} value={item.name}>
                              {item.alias || item.name}
                            </option>
                          ))}
                        </select>
                      </div>
                      <div className="resource-record-meta">
                        <input
                          value={record.attributes.private_ip || ""}
                          placeholder="IP"
                          onChange={(event) =>
                            updateRecord(record.previewKey, (current) => ({
                              ...current,
                              attributes: {
                                ...current.attributes,
                                private_ip: event.target.value,
                              },
                            }))
                          }
                        />
                        <select
                          value={record.attributes.status || "未监控"}
                          onChange={(event) =>
                            updateRecord(record.previewKey, (current) => ({
                              ...current,
                              attributes: {
                                ...current.attributes,
                                status: event.target.value,
                              },
                            }))
                          }
                        >
                          {["未监控", "在线", "离线", "已纳管"].map((status) => (
                            <option key={status} value={status}>
                              {status}
                            </option>
                          ))}
                        </select>
                      </div>
                      <div className="resource-record-source">
                        {record.sourceRows[0]?.filename || "自动生成"}
                        {record.sourceRows[0]?.sheet ? ` / ${record.sourceRows[0]?.sheet}` : ""}
                        {record.sourceRows[0]?.rowIndex ? ` / 行 ${record.sourceRows[0]?.rowIndex}` : ""}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="resource-empty-state">选择左侧分组查看资源明细</div>
              )}
            </section>
          </div>

          <div className="resource-topology-layout">
            <section className="resource-section">
              <div className="resource-section-header">
                <div>
                  <h3>拓扑关系草案</h3>
                  <p>基于业务字段、部署目标、网段与机柜层级推断关系，可逐条修正。</p>
                </div>
              </div>
              <div className="resource-relation-list">
                {relations.length ? (
                  relations.map((relation) => (
                    <div
                      key={`${relation.sourceKey}-${relation.targetKey}-${relation.relationType}`}
                      className="resource-relation-item"
                    >
                      <label className="resource-check">
                        <input
                          type="checkbox"
                          checked={relation.selected}
                          onChange={(event) =>
                            updateRelation(relation, (current) => ({
                              ...current,
                              selected: event.target.checked,
                            }))
                          }
                        />
                      </label>
                      <div className="resource-relation-copy">
                        <strong>
                          {recordMap.get(relation.sourceKey)?.name || relation.sourceKey}
                          {" "}
                          →{" "}
                          {recordMap.get(relation.targetKey)?.name || relation.targetKey}
                        </strong>
                        <p>{relation.reason}</p>
                      </div>
                      <div className="resource-relation-controls">
                        <select
                          value={relation.relationType}
                          onChange={(event) =>
                            updateRelation(relation, (current) => ({
                              ...current,
                              relationType: event.target.value,
                            }))
                          }
                        >
                          {(metadata?.relationTypes || []).map((item) => (
                            <option key={item} value={item}>
                              {item}
                            </option>
                          ))}
                        </select>
                        <span className={`resource-confidence ${relation.confidence}`}>
                          {relation.confidence}
                        </span>
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="resource-empty-state">解析后生成拓扑关系候选</div>
                )}
              </div>
            </section>

            <section className="resource-section">
              <div className="resource-section-header">
                <div>
                  <h3>关系图谱</h3>
                  <p>以业务、资源、机房、IPAM 四类节点展示导入草案。</p>
                </div>
              </div>
              <div className="resource-topology-chart">
                {resourceGroups.length ? (
                  <ReactECharts option={chartOption} style={{ height: 420 }} />
                ) : (
                  <div className="resource-empty-state">完成预解析后展示拓扑图</div>
                )}
              </div>
            </section>
          </div>

          <section className="resource-section">
            <div className="resource-section-header">
              <div>
                <h3>解析日志与导入结果</h3>
                <p>记录 AI 推断过程、异常提醒以及最终的 CMDB 落库反馈。</p>
              </div>
            </div>
            <div className="resource-log-layout">
              <div className="resource-log-box">
                {(preview?.logs || []).length ? (
                  preview?.logs.map((log, index) => (
                    <div key={`${log}-${index}`} className="resource-log-item">
                      {log}
                    </div>
                  ))
                ) : (
                  <div className="resource-empty-state">等待执行解析</div>
                )}
              </div>
              <div className="resource-result-box">
                {result ? (
                  <>
                    <div className="resource-result-summary">
                      <strong>{result.status === "success" ? "导入成功" : "导入完成（含失败项）"}</strong>
                      <p>
                        新建 {result.created} 个 CI，创建 {result.relationsCreated} 条关系，跳过 {result.skipped} 项。
                      </p>
                    </div>
                    {result.error ? <div className="resource-result-error">{result.error}</div> : null}
                  </>
                ) : preview?.warnings?.length ? (
                  preview.warnings.map((warning, index) => (
                    <div key={`${warning}-${index}`} className="resource-result-warning">
                      {warning}
                    </div>
                  ))
                ) : (
                  <div className="resource-empty-state">导入完成后在这里展示结果</div>
                )}
              </div>
            </div>
          </section>
        </section>
      </div>
    </div>
  );
}
