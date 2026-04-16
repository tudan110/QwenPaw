import { startTransition, useEffect, useMemo, useRef, useState } from "react";
import ReactECharts from "echarts-for-react";
import {
  getResourceImportMetadata,
  getResourceImportStart,
  previewResourceImport,
} from "../../api/resourceImport";
import type {
  ResourceImportCiTypeAttributeDefinition,
  ResourceImportCiTypeMetadata,
  ResourceImportGroup,
  ResourceImportMetadata,
  ResourceImportPreviewJob,
  ResourceImportPreview,
  ResourceImportRecord,
  ResourceImportRelation,
  ResourceImportResult,
  ResourceImportStartPayload,
} from "../../types/resourceImport";
import "./resource-import-conversation.css";

export type ResourceImportFlowStage =
  | "intro"
  | "parsing"
  | "structure"
  | "confirm"
  | "topology"
  | "importing"
  | "result";

type ResourceImportFileSummary = {
  name: string;
  size: number;
};

export type ResourceImportFlowPayload = {
  flowId: string;
  stage: ResourceImportFlowStage;
  files?: ResourceImportFileSummary[];
  status?: "idle" | "running" | "completed" | "error";
  preview?: ResourceImportPreview | null;
  resourceGroups?: ResourceImportGroup[];
  relations?: ResourceImportRelation[];
  result?: ResourceImportResult | null;
  error?: string;
  locked?: boolean;
  readonly?: boolean;
};

type ResourceImportConversationCardProps = {
  agentId?: string | null;
  message: {
    id: string;
    resourceImportFlow?: ResourceImportFlowPayload;
  };
  onUploadFiles: (payload: {
    sourceMessageId: string;
    flowId: string;
    files: File[];
  }) => void;
  onStartParse: (payload: {
    messageId: string;
    flowId: string;
  }) => void;
  onParseResolved: (payload: {
    messageId: string;
    flowId: string;
    preview: ResourceImportPreview;
  }) => void;
  onParseFailed: (payload: {
    messageId: string;
    flowId: string;
    error: string;
  }) => void;
  onReturnToUpload: (payload: {
    flowId: string;
    sourceMessageId?: string;
  }) => void;
  onBuildTopology: (payload: {
    messageId: string;
    flowId: string;
    preview: ResourceImportPreview | null;
    resourceGroups: ResourceImportGroup[];
    relations: ResourceImportRelation[];
  }) => void;
  onConfirmStructure: (payload: {
    messageId: string;
    flowId: string;
    preview: ResourceImportPreview | null;
    resourceGroups: ResourceImportGroup[];
    relations: ResourceImportRelation[];
  }) => void;
  onBackToConfirm: (payload: {
    messageId: string;
    flowId: string;
  }) => void;
  onSubmitImport: (payload: {
    messageId: string;
    flowId: string;
    preview: ResourceImportPreview | null;
    resourceGroups: ResourceImportGroup[];
    relations: ResourceImportRelation[];
  }) => void;
  onContinueImport: (payload: {
    flowId: string;
  }) => void;
  onOpenSystemTopology: (payload: {
    flowId: string;
  }) => void;
  onScrollToStage: (payload: {
    flowId: string;
    stage: ResourceImportFlowStage;
  }) => void;
  resolveFiles: (flowId: string) => File[];
  releaseFiles: (flowId: string) => void;
};

const FLOW_STEPS = [
  { index: 1, icon: "📂", label: "上传文件" },
  { index: 2, icon: "🔍", label: "AI解析" },
  { index: 3, icon: "✅", label: "确认数据" },
  { index: 4, icon: "🔗", label: "建立关系" },
  { index: 5, icon: "🚀", label: "导入CMDB" },
] as const;

const CUSTOM_STRUCTURE_OPTION_VALUE = "__custom__";

const STATUS_OPTIONS = ["待确认", "未监控", "已纳管", "在线", "离线", "告警"] as const;
const ATTRIBUTE_FIELD_LABELS: Record<string, string> = {
  asset_code: "资产编号",
  name: "名称",
  private_ip: "内网IP",
  public_ip: "公网IP",
  status: "状态",
  vendor: "厂商",
  model: "型号",
  version: "版本",
  service_port: "服务端口",
  monitor_status: "监控接入",
  host_name: "宿主机/部署主机",
  deploy_target: "部署目标",
  upstream_resource: "上联/依赖资源",
  os_version: "操作系统版本",
  owner: "维护团队",
  environment: "运行环境",
  description: "说明",
  dev_no: "设备编码",
  dev_name: "设备名称",
  manage_ip: "管理IP",
  dev_model: "设备型号",
  dev_class: "设备类型",
  alarm_status: "告警状态",
  dev_software_version: "设备软件版本",
  dev_sn: "设备序列号",
  property_no: "资产编号",
  city: "地市",
  county: "区县",
  data_center: "所属数据中心",
  server_room: "所属机房",
  platform: "平台",
  op_duty: "运维负责人",
  u_count: "U数",
  u_start: "起始U位",
  cabinet: "所属机柜",
  buy_date: "采购日期",
  maintain_enddate: "过保日期",
  proto_snmp: "SNMP版本",
  snmp_port: "SNMP端口",
  snmp_read: "读口令",
  snmp_write: "写口令",
};
const ATTRIBUTE_FIELD_ORDER = [
  "asset_code",
  "name",
  "private_ip",
  "public_ip",
  "status",
  "vendor",
  "model",
  "version",
  "service_port",
  "monitor_status",
  "host_name",
  "deploy_target",
  "upstream_resource",
  "os_version",
  "owner",
  "environment",
  "description",
] as const;
const DEFAULT_PARSE_LOGS = [
  "✓ 文件读取成功",
  "✓ 识别到资源清单结构",
  "→ 开始智能字段映射...",
  "✓ 自动映射标准字段",
  "→ 执行数据清洗和标准化...",
  "✓ 生成清洗报告",
  "→ 推断资源拓扑关系...",
  "✓ 生成待确认拓扑草案",
] as const;

function extractErrorMessage(error: unknown) {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error || "");
}

function formatFileSize(size: number) {
  if (size < 1024) {
    return `${size} B`;
  }
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`;
  }
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function getFileEmoji(name: string) {
  const extension = name.split(".").pop()?.toLowerCase() || "";
  if (["xlsx", "xls", "csv"].includes(extension)) {
    return "📊";
  }
  if (["doc", "docx", "txt", "md"].includes(extension)) {
    return "📝";
  }
  if (["png", "jpg", "jpeg"].includes(extension)) {
    return "🖼️";
  }
  return "📄";
}

function countSelectedRecords(groups: ResourceImportGroup[]) {
  return groups.reduce(
    (total, group) => total + group.records.filter((record) => record.selected).length,
    0,
  );
}

function getRecordAddress(record: ResourceImportRecord) {
  return (
    record.attributes.manage_ip
    || record.attributes.private_ip
    || record.attributes.host
    || record.attributes.host_name
    || record.attributes.public_ip
    || "-"
  );
}

function getDisplayName(record: ResourceImportRecord) {
  return record.name || "待确认";
}

function getDisplayStatus(record: ResourceImportRecord) {
  return record.attributes.status || record.attributes.alarm_status || "待确认";
}

function getAttributeLabel(key: string) {
  return ATTRIBUTE_FIELD_LABELS[key] || key;
}

function getCiTypeMeta(
  preview: ResourceImportPreview | null | undefined,
  ciType: string,
) {
  return preview?.ciTypeMetadata?.[ciType] || null;
}

function getMetadataCiTypeMeta(
  metadata: ResourceImportMetadata | null | undefined,
  ciType: string,
) {
  return (metadata?.ciTypes || []).find((item) => item.name === ciType) || null;
}

function getVisibleAttributeDefinitions(
  preview: ResourceImportPreview | null | undefined,
  ciType: string,
  record: ResourceImportRecord,
) {
  const typeMeta = getCiTypeMeta(preview, ciType);
  const definitions = typeMeta?.attributeDefinitions || [];
  const visibleDefinitions = definitions.filter((item) => item.default_show || item.required);
  const definitionMap = new Map(definitions.map((item) => [item.name, item]));

  Object.keys(record.attributes || {}).forEach((key) => {
    if (!definitionMap.has(key)) {
      visibleDefinitions.push({
        name: key,
        alias: getAttributeLabel(key),
      });
      definitionMap.set(key, visibleDefinitions[visibleDefinitions.length - 1]);
    }
  });

  return visibleDefinitions.sort((left, right) => {
    const leftRequired = left.required ? 0 : 1;
    const rightRequired = right.required ? 0 : 1;
    return leftRequired - rightRequired || (left.alias || left.name).localeCompare(right.alias || right.name, "zh-CN");
  });
}

function getChoiceOptions(definition?: ResourceImportCiTypeAttributeDefinition | null) {
  return definition?.choices || [];
}

type ResourceImportStructureItem = NonNullable<
  ResourceImportPreview["structureAnalysis"]
>["items"][number];

function getStructureStatusLabel(status: ResourceImportStructureItem["status"]) {
  switch (status) {
    case "matched":
      return "已匹配";
    case "ambiguous_model":
      return "待确认模型";
    case "missing_group":
      return "待创建分组";
    case "missing_model":
      return "待创建模型";
    default:
      return "待确认";
  }
}

function getStructureSelectValue(
  currentValue: string,
  options: Array<{ name: string; existing: boolean }>,
) {
  const targetValue = String(currentValue || "").trim();
  if (targetValue && options.some((option) => option.existing && option.name === targetValue)) {
    return targetValue;
  }
  return CUSTOM_STRUCTURE_OPTION_VALUE;
}

function getStructureModelOptions(
  item: ResourceImportStructureItem,
  metadata: ResourceImportMetadata | null,
  selectedGroupName: string,
) {
  const optionMap = new Map<string, {
    id?: number | string;
    name: string;
    alias?: string;
    groupName?: string;
    existing: boolean;
  }>();

  (item.modelOptions || [])
    .filter((option) => !selectedGroupName || !option.groupName || option.groupName === selectedGroupName)
    .forEach((option) => {
      if (!option?.name) {
        return;
      }
      optionMap.set(option.name, {
        id: option.id,
        name: option.name,
        alias: option.alias,
        groupName: option.groupName,
        existing: option.existing !== false,
      });
    });

  const selectedGroup = (metadata?.ciTypeGroups || []).find((group) => group.name === selectedGroupName);
  if (selectedGroup) {
    selectedGroup.ciTypes.forEach((ciType) => {
      if (!ciType?.name) {
        return;
      }
      optionMap.set(ciType.name, {
        id: ciType.id,
        name: ciType.name,
        alias: ciType.alias,
        groupName: selectedGroup.name,
        existing: true,
      });
    });
  }

  return Array.from(optionMap.values()).sort((left, right) =>
    left.name.localeCompare(right.name, "zh-CN"),
  );
}

function getStructureGroupOptions(
  item: ResourceImportStructureItem,
  metadata: ResourceImportMetadata | null,
) {
  const optionMap = new Map<string, {
    id?: number | string;
    name: string;
    existing: boolean;
  }>();

  (item.groupOptions || []).forEach((option) => {
    if (!option?.name) {
      return;
    }
    optionMap.set(option.name, {
      id: option.id,
      name: option.name,
      existing: option.existing !== false,
    });
  });

  (metadata?.ciTypeGroups || []).forEach((group) => {
    if (!group?.name) {
      return;
    }
    optionMap.set(group.name, {
      id: group.id,
      name: group.name,
      existing: true,
    });
  });

  return Array.from(optionMap.values()).sort((left, right) =>
    left.name.localeCompare(right.name, "zh-CN"),
  );
}

function isExistingStructureGroup(
  item: ResourceImportStructureItem,
  metadata: ResourceImportMetadata | null,
  groupName: string,
) {
  const targetName = String(groupName || "").trim();
  if (!targetName) {
    return false;
  }
  return getStructureGroupOptions(item, metadata).some(
    (option) => option.existing && option.name === targetName,
  );
}

function isExistingStructureModel(
  item: ResourceImportStructureItem,
  metadata: ResourceImportMetadata | null,
) {
  const selectedGroupName = String(item.selectedGroupName || "").trim();
  const selectedModelName = String(item.selectedModelName || "").trim();
  if (!selectedModelName) {
    return false;
  }
  return getStructureModelOptions(item, metadata, selectedGroupName).some(
    (option) => option.existing && option.name === selectedModelName,
  );
}

function getStructureTargetGroup(
  preview: ResourceImportPreview | null | undefined,
  item: ResourceImportStructureItem,
) {
  return (preview?.resourceGroups || []).find((group) => group.ciType === item.resourceCiType || group.label === item.resourceLabel) || null;
}

function getStructureUniqueKeyOptions(
  preview: ResourceImportPreview | null | undefined,
  item: ResourceImportStructureItem,
  metadata?: ResourceImportMetadata | null,
  draft?: {
    inheritFrom?: string;
    uniqueKey?: string;
  },
) {
  const targetGroup = getStructureTargetGroup(preview, item);
  const counts = new Map<string, number>();
  const labels = new Map<string, string>();
  const total = targetGroup?.records.length || 0;

  for (const record of targetGroup?.records || []) {
    const keys = new Set<string>([
      ...Object.keys(record.attributes || {}),
      ...Object.keys(record.analysisAttributes || {}),
    ]);
    keys.forEach((key) => {
      counts.set(key, (counts.get(key) || 0) + 1);
      labels.set(key, getAttributeLabel(key));
    });
  }

  const optionMap = new Map<string, {
    name: string;
    label: string;
    coverage: number;
    priority: number;
  }>();
  const preferredTypeName =
    draft?.inheritFrom
    || item.modelDraft?.inheritFrom
    || item.selectedModelName
    || item.suggestedModelName
    || item.resourceCiType;
  const preferredTypeMeta = getMetadataCiTypeMeta(metadata, preferredTypeName || "");
  const preferredUniqueKey = preferredTypeMeta?.unique_key || "";

  (preferredTypeMeta?.attributeDefinitions || []).forEach((definition) => {
    const name = definition.name;
    if (!name) {
      return;
    }
    const coverage = total ? Math.round(((counts.get(name) || 0) / total) * 100) : 0;
    const priority = name === preferredUniqueKey
      ? 0
      : counts.has(name)
        ? 1
        : ["dev_no", "property_no", "manage_ip", "private_ip", "name", "dev_name"].includes(name)
          ? 2
          : 5;
    optionMap.set(name, {
      name,
      label: definition.alias || getAttributeLabel(name),
      coverage,
      priority,
    });
  });

  Array.from(counts.entries()).forEach(([name, count]) => {
    if (count <= 0) {
      return;
    }
    const existing = optionMap.get(name);
    const priority = ["dev_no", "property_no", "asset_code", "private_ip", "manage_ip", "serverName", "name", "dev_name"].indexOf(name);
    optionMap.set(name, {
      name,
      label: labels.get(name) || existing?.label || name,
      coverage: total ? Math.round((count / total) * 100) : 0,
      priority: existing?.priority ?? (priority === -1 ? 9 : 3 + priority),
    });
  });

  return Array.from(optionMap.values())
    .sort((left, right) =>
      left.priority - right.priority
      || right.coverage - left.coverage
      || left.label.localeCompare(right.label, "zh-CN"),
    )
    .map(({ priority, ...option }) => option);
}

function getStructureInheritanceOptions(
  metadata: ResourceImportMetadata | null,
  item: ResourceImportStructureItem,
) {
  const options = getStructureModelOptions(item, metadata, item.selectedGroupName || "");
  if (options.length) {
    return options;
  }
  return (metadata?.ciTypes || []).map((ciType) => ({
    id: ciType.id,
    name: ciType.name,
    alias: ciType.alias,
    existing: true,
  }));
}

function getSuggestedUniqueKey(
  preview: ResourceImportPreview | null | undefined,
  item: ResourceImportStructureItem,
  metadata?: ResourceImportMetadata | null,
  draft?: {
    inheritFrom?: string;
    uniqueKey?: string;
  },
) {
  return getStructureUniqueKeyOptions(preview, item, metadata, draft)[0]?.name || "";
}

function applyStructureSelectionsToPreview(
  preview: ResourceImportPreview | null | undefined,
  items: ResourceImportStructureItem[],
): {
  preview: ResourceImportPreview | null;
  resourceGroups: ResourceImportGroup[];
} {
  if (!preview) {
    return {
      preview: null,
      resourceGroups: [],
    };
  }

  const itemMap = new Map(items.map((item) => [item.key, item]));
  const resourceGroups = (preview.resourceGroups || []).map((group) => {
    const structureItem = itemMap.get(group.ciType || group.label);
    if (!structureItem) {
      return group;
    }
    const nextCiType = structureItem.selectedModelName || group.ciType;
    const nextLabel = preview.ciTypeMetadata?.[nextCiType]?.alias || group.label;
    return {
      ...group,
      ciType: nextCiType,
      label: nextLabel,
      records: group.records.map((record) => ({
        ...record,
        ciType: nextCiType,
      })),
    };
  });

  return {
    preview: {
      ...preview,
      resourceGroups,
      structureAnalysis: {
        items,
      },
    },
    resourceGroups,
  };
}

function sortAttributeKeys(keys: string[]) {
  return [...keys].sort((left, right) => {
    const leftIndex = ATTRIBUTE_FIELD_ORDER.indexOf(left as typeof ATTRIBUTE_FIELD_ORDER[number]);
    const rightIndex = ATTRIBUTE_FIELD_ORDER.indexOf(right as typeof ATTRIBUTE_FIELD_ORDER[number]);
    if (leftIndex !== -1 || rightIndex !== -1) {
      return (leftIndex === -1 ? 999 : leftIndex) - (rightIndex === -1 ? 999 : rightIndex);
    }
    return getAttributeLabel(left).localeCompare(getAttributeLabel(right), "zh-CN");
  });
}

function getBatchEditorColumns(
  preview: ResourceImportPreview | null | undefined,
  groups: ResourceImportGroup[],
) {
  const columnMap = new Map<string, { key: string; label: string }>();
  for (const group of groups) {
    for (const record of group.records) {
      const definitions = getVisibleAttributeDefinitions(preview, record.ciType, record);
      for (const definition of definitions) {
        columnMap.set(definition.name, {
          key: definition.name,
          label: definition.alias || getAttributeLabel(definition.name),
        });
      }
      for (const key of Object.keys(record.attributes || {})) {
        if (!columnMap.has(key)) {
          columnMap.set(key, {
            key,
            label: getAttributeLabel(key),
          });
        }
      }
    }
  }
  return sortAttributeKeys(Array.from(columnMap.keys())).map((key) => columnMap.get(key)!);
}

function buildDownloadPayload(groups: ResourceImportGroup[]) {
  const rows = groups.flatMap((group) =>
    group.records.map((record) => ({
      ciType: record.ciType,
      name: record.name,
      selected: record.selected ? "是" : "否",
      importAction: record.importAction || "create",
      ...record.attributes,
    })),
  );
  return JSON.stringify(rows, null, 2);
}

function downloadConfirmationData(groups: ResourceImportGroup[]) {
  const blob = new Blob([buildDownloadPayload(groups)], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "resource-import-confirmation.json";
  anchor.click();
  URL.revokeObjectURL(url);
}

function getRecordIssues(record: ResourceImportRecord) {
  return record.issues || [];
}

function normalizeIssueFieldName(field: string) {
  const cleaned = String(field || "").trim();
  if (!cleaned) {
    return "";
  }
  if (cleaned.startsWith("attributes.")) {
    return cleaned.slice("attributes.".length);
  }
  return cleaned;
}

function getFieldIssues(record: ResourceImportRecord, field: string) {
  const normalizedField = normalizeIssueFieldName(field);
  return getRecordIssues(record).filter(
    (issue) => normalizeIssueFieldName(issue.field) === normalizedField,
  );
}

function isEmptyValue(value: unknown) {
  if (Array.isArray(value)) {
    return value.length === 0;
  }
  return String(value ?? "").trim() === "";
}

function hasAttentionField(record: ResourceImportRecord, field: string) {
  return (record.attentionFields || []).includes(field);
}

function fieldNeedsAttention(
  record: ResourceImportRecord,
  field: string,
  definition?: ResourceImportCiTypeAttributeDefinition | null,
) {
  if (hasAttentionField(record, field)) {
    return true;
  }
  if (getFieldIssues(record, field).length) {
    return true;
  }
  const value = field === "name" ? record.name : record.attributes?.[field];
  if (definition?.required && isEmptyValue(value)) {
    return true;
  }
  if (field === "name" && isEmptyValue(value)) {
    return true;
  }
  return false;
}

function getFieldAttentionMessage(
  record: ResourceImportRecord,
  field: string,
  definition?: ResourceImportCiTypeAttributeDefinition | null,
) {
  const issueMessage = getFieldIssues(record, field)[0]?.message;
  if (issueMessage) {
    return issueMessage;
  }
  const value = field === "name" ? record.name : record.attributes?.[field];
  if ((definition?.required || field === "name") && isEmptyValue(value)) {
    return `${definition?.alias || getAttributeLabel(field)} 为空，请补充`;
  }
  return "";
}

function getImportActionOptions(record: ResourceImportRecord) {
  if (record.existingCi?.ciId !== undefined) {
    return [
      { value: "update", label: "更新已存在资源" },
      { value: "skip", label: "跳过该资源" },
    ];
  }
  return [
    { value: "create", label: "新建资源" },
    { value: "skip", label: "跳过该资源" },
  ];
}

function getImportActionLabel(record: ResourceImportRecord) {
  if ((record.importAction || "create") === "skip") {
    return "跳过";
  }
  if ((record.importAction || "create") === "update") {
    return "更新";
  }
  return "新建";
}

function getEditableAttributeKeys(record: ResourceImportRecord) {
  const keys = new Set<string>(["name", "status"]);
  ATTRIBUTE_FIELD_ORDER.forEach((key) => {
    if (key === "name") {
      keys.add(key);
      return;
    }
    if (record.attributes[key] || key === "description") {
      keys.add(key);
    }
  });
  Object.keys(record.attributes || {}).forEach((key) => {
    if (record.attributes[key]) {
      keys.add(key);
    }
  });
  return Array.from(keys);
}

function buildRecordSource(record: ResourceImportRecord) {
  const firstSource = record.sourceRows[0];
  if (!firstSource) {
    return "自动补全";
  }

  const fragments = [
    firstSource.filename,
    firstSource.sheet,
    firstSource.rowIndex ? `行 ${firstSource.rowIndex}` : "",
  ];
  return fragments.filter(Boolean).join(" / ") || "上传文件";
}

function getGroupIcon(group: ResourceImportGroup) {
  const ciType = group.ciType.toLowerCase();
  if (ciType.includes("server")) {
    return "🖥️";
  }
  if (ciType.includes("switch") || ciType.includes("router") || ciType.includes("firewall")) {
    return "🌐";
  }
  if (
    ciType.includes("mysql")
    || ciType.includes("redis")
    || ciType.includes("kafka")
    || ciType.includes("nginx")
  ) {
    return "🔧";
  }
  return "📦";
}

function getCurrentStep(stage: ResourceImportFlowStage) {
  if (stage === "intro") {
    return 1;
  }
  if (stage === "parsing") {
    return 2;
  }
  if (stage === "structure") {
    return 3;
  }
  if (stage === "confirm") {
    return 3;
  }
  if (stage === "topology") {
    return 4;
  }
  return 5;
}

function FlowSteps({
  stage,
  forceCompleted = false,
}: {
  stage: ResourceImportFlowStage;
  forceCompleted?: boolean;
}) {
  const currentStep = getCurrentStep(stage);

  return (
    <div className="resource-import-flow-steps">
      {FLOW_STEPS.map((flowStep) => {
        const status = forceCompleted
          ? "completed"
          : flowStep.index < currentStep
            ? "completed"
            : flowStep.index === currentStep
              ? "active"
              : "";
        return (
          <div key={flowStep.index} className={`resource-import-flow-step ${status}`.trim()}>
            <span className="resource-import-flow-step-icon">{flowStep.icon}</span>
            <span className="resource-import-flow-step-label">{flowStep.label}</span>
          </div>
        );
      })}
    </div>
  );
}

function IntroStage({
  agentId,
  flow,
  flowId,
  messageId,
  onUploadFiles,
  onReturnToUpload,
  onStartParse,
}: {
  agentId?: string | null;
  flow: ResourceImportFlowPayload;
  flowId: string;
  messageId: string;
  onUploadFiles: ResourceImportConversationCardProps["onUploadFiles"];
  onReturnToUpload: ResourceImportConversationCardProps["onReturnToUpload"];
  onStartParse: ResourceImportConversationCardProps["onStartParse"];
}) {
  const [metadata, setMetadata] = useState<ResourceImportMetadata | null>(null);
  const [startPayload, setStartPayload] = useState<ResourceImportStartPayload | null>(null);
  const [error, setError] = useState("");
  const [dragActive, setDragActive] = useState(false);

  const fallbackStartPayload: ResourceImportStartPayload = {
    copyBlocks: [
      {
        title: "我将帮助您零门槛完成资源盘点和录入，您只需要提供手里的资料，剩下的交给我！",
      },
      {
        title: "🎯 我能处理的各种资料：",
        items: [
          "📊 Excel/CSV设备清单 - 自动识别表头，智能映射字段",
          "📸 网络拓扑图截图 - OCR识别设备信息",
          "📝 Word技术文档 - 提取配置信息",
          "☁️ 云账号资料 - 直接同步云资源（暂未开放）",
        ],
      },
      {
        title: "🔧 智能处理能力：",
        items: [
          "自动字段映射 - 无需手动配置",
          "数据清洗标准化 - IP、状态、类型自动规范",
          "拓扑关系推断 - 基于IP网段、命名规则自动发现",
          "交互式确认 - 每步都可查看和修改",
        ],
      },
      {
        title: "📋 5步快速纳管：",
        ordered: true,
        items: [
          "1️⃣ 上传资源文件（拖拽或选择）",
          "2️⃣ AI智能解析和字段映射",
          "3️⃣ 确认解析结果（可编辑）",
          "4️⃣ 查看推断的拓扑关系",
          "5️⃣ 一键导入CMDB",
        ],
      },
      {
        title: "💡 支持的关键字：",
        paragraphs: [
          "“导入资源清单” / “批量导入” / “资源纳管”",
          "直接拖拽Excel文件到对话框",
        ],
      },
    ],
    supportedFormats: ["Excel", "CSV", "Word", "图片"],
  };

  useEffect(() => {
    let cancelled = false;
    void getResourceImportMetadata(agentId || undefined)
      .then((response) => {
        if (!cancelled) {
          setMetadata(response);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(extractErrorMessage(err) || "CMDB 元数据加载失败");
        }
      });
    void getResourceImportStart(agentId || undefined)
      .then((response) => {
        if (!cancelled) {
          setStartPayload(response);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setStartPayload(null);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [agentId]);

  const handleFiles = (nextFiles: FileList | File[] | null) => {
    const normalized = nextFiles ? Array.from(nextFiles).filter((file) => file.size > 0) : [];
    if (!normalized.length) {
      return;
    }
    onUploadFiles({
      sourceMessageId: messageId,
      flowId,
      files: normalized,
    });
  };

  const introPayload = startPayload || fallbackStartPayload;
  const supportedFormats = metadata?.supportedFormats?.length
    ? metadata.supportedFormats
    : introPayload.supportedFormats;

  return (
    <div
      className={dragActive ? "resource-import-conversation-card drag-active" : "resource-import-conversation-card"}
      onDragEnter={(event) => {
        event.preventDefault();
        setDragActive(true);
      }}
      onDragOver={(event) => {
        event.preventDefault();
        if (!dragActive) {
          setDragActive(true);
        }
      }}
      onDragLeave={(event) => {
        event.preventDefault();
        const nextTarget = event.relatedTarget as Node | null;
        if (!event.currentTarget.contains(nextTarget)) {
          setDragActive(false);
        }
      }}
      onDrop={(event) => {
        event.preventDefault();
        setDragActive(false);
        handleFiles(event.dataTransfer.files);
      }}
    >
      <div className="resource-import-stage">
        {error ? <div className="resource-import-inline-error">{error}</div> : null}

        {introPayload.copyBlocks.map((block) => (
          <div key={block.title} className="resource-import-copy-block">
            <strong>{block.title}</strong>
            {block.ordered ? (
              <ol>
                {(block.items || []).map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ol>
            ) : block.items?.length ? (
              <ul>
                {block.items.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            ) : null}
            {(block.paragraphs || []).map((paragraph) => (
              <p key={paragraph}>{paragraph}</p>
            ))}
            {block.title.includes("关键词") ? (
              <p>支持格式：{supportedFormats.join("、") || "Excel、CSV、Word、图片"}</p>
            ) : null}
          </div>
        ))}

        <div className="resource-import-dropzone">
          <label className="resource-import-dropzone-inner">
            <input
              type="file"
              hidden
              multiple
              accept={supportedFormats.join(",")}
              onChange={(event) => handleFiles(event.target.files)}
            />
            <div className="resource-import-dropzone-icon">📂</div>
            <div className="resource-import-dropzone-title">拖拽文件到此处，或点击选择文件</div>
            <div className="resource-import-dropzone-hint">
              支持 Excel、CSV、Word、图片，可一次上传多个文件
            </div>
          </label>
        </div>

        {flow.files?.length ? (
          <div className="resource-import-file-stack">
            {flow.files.map((file) => (
              <div key={`${file.name}-${file.size}`} className="resource-import-file-chip">
                <span>{getFileEmoji(file.name)}</span>
                <div>
                  <strong>{file.name}</strong>
                  <small>{formatFileSize(file.size)}</small>
                </div>
              </div>
            ))}
          </div>
        ) : null}

        <div className="resource-import-action-row">
          <button
            type="button"
            className="secondary"
            onClick={() => onReturnToUpload({ flowId, sourceMessageId: messageId })}
          >
            清空文件
          </button>
          <button
            type="button"
            className="primary"
            disabled={!flow.files?.length}
            onClick={() =>
              onStartParse({
                messageId,
                flowId,
              })
            }
          >
            开始智能解析
          </button>
        </div>
      </div>
    </div>
  );
}

function ParsingStage({
  agentId,
  flow,
  messageId,
  resolveFiles,
  releaseFiles,
  onParseResolved,
  onParseFailed,
  onReturnToUpload,
}: {
  agentId?: string | null;
  flow: ResourceImportFlowPayload;
  messageId: string;
  resolveFiles: ResourceImportConversationCardProps["resolveFiles"];
  releaseFiles: ResourceImportConversationCardProps["releaseFiles"];
  onParseResolved: ResourceImportConversationCardProps["onParseResolved"];
  onParseFailed: ResourceImportConversationCardProps["onParseFailed"];
  onReturnToUpload: ResourceImportConversationCardProps["onReturnToUpload"];
}) {
  const startedRef = useRef(false);
  const [displayedLogs, setDisplayedLogs] = useState<string[]>([]);
  const [parsePercent, setParsePercent] = useState(flow.status === "completed" ? 100 : 8);

  useEffect(() => {
    if (flow.status !== "running" || startedRef.current) {
      return;
    }

    const files = resolveFiles(flow.flowId);
    if (!files.length) {
      onParseFailed({
        messageId,
        flowId: flow.flowId,
        error: "未找到待解析的上传文件，请重新上传。",
      });
      return;
    }

    startedRef.current = true;
    let cancelled = false;
    const defaultLogs = [...DEFAULT_PARSE_LOGS];
    setDisplayedLogs(defaultLogs.slice(0, 2));
    setParsePercent(8);

    void previewResourceImport(files, agentId || undefined, {
      onProgress: (job: ResourceImportPreviewJob) => {
        if (cancelled) {
          return;
        }
        const progressLogs = (job.progressEvents || [])
          .map((event) => String(event.message || "").trim())
          .filter(Boolean);
        startTransition(() => {
          setDisplayedLogs(progressLogs.length ? progressLogs : defaultLogs);
          setParsePercent(
            typeof job.progressPercent === "number"
              ? Math.max(8, Math.min(100, job.progressPercent))
              : 12,
          );
        });
      },
      maxWaitMs: 20 * 60 * 1000,
    })
      .then((preview) => {
        if (cancelled) {
          return;
        }
        const finalLogs = preview.logs.length ? preview.logs : defaultLogs;
        startTransition(() => {
          setDisplayedLogs(finalLogs);
          setParsePercent(100);
        });
        releaseFiles(flow.flowId);
        window.setTimeout(() => {
          if (!cancelled) {
            onParseResolved({
              messageId,
              flowId: flow.flowId,
              preview,
            });
          }
        }, 220);
      })
      .catch((error) => {
        if (cancelled) {
          return;
        }
        releaseFiles(flow.flowId);
        onParseFailed({
          messageId,
          flowId: flow.flowId,
          error: extractErrorMessage(error) || "资源解析失败",
        });
      });

    return () => {
      cancelled = true;
    };
  }, [
    agentId,
    flow.flowId,
    flow.status,
    messageId,
    onParseFailed,
    onParseResolved,
    releaseFiles,
    resolveFiles,
  ]);

  return (
    <div className="resource-import-conversation-card">
      <FlowSteps stage="parsing" forceCompleted={flow.status === "completed"} />

      {flow.error ? <div className="resource-import-inline-error">{flow.error}</div> : null}

      <div className="resource-import-stage">
        <div className="resource-import-file-stack">
          {(flow.files || []).map((file) => (
            <div key={`${file.name}-${file.size}`} className="resource-import-file-chip">
              <span>{getFileEmoji(file.name)}</span>
              <div>
                <strong>{file.name}</strong>
                <small>{formatFileSize(file.size)}</small>
              </div>
            </div>
          ))}
        </div>

        <div className="resource-import-parse-card">
          <div className="resource-import-parse-header">
            <strong>🔍 正在智能解析文件...</strong>
            <span>{flow.status === "error" ? "失败" : `${parsePercent}%`}</span>
          </div>
          <div className="resource-import-parse-bar">
            <div className="resource-import-parse-bar-fill" style={{ width: `${parsePercent}%` }} />
          </div>
          <div className="resource-import-parse-status">
            {flow.status === "completed"
              ? "解析完成"
              : flow.status === "error"
                ? "解析失败"
                : "解析中..."}
          </div>
          <div className="resource-import-parse-log">
            {(displayedLogs.length ? displayedLogs : ["→ 等待解析开始..."]).map((logLine, index) => (
              <div key={`${logLine}-${index}`} className="resource-import-log-line">
                {logLine}
              </div>
            ))}
          </div>
        </div>

        {flow.status === "error" ? (
          <div className="resource-import-action-row">
            <button
              type="button"
              className="secondary"
              onClick={() =>
                onReturnToUpload({
                  flowId: flow.flowId,
                  sourceMessageId: messageId,
                })
              }
            >
              重新上传
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function StructureStage({
  agentId,
  flow,
  messageId,
  onReturnToUpload,
  onConfirmStructure,
}: {
  agentId?: string | null;
  flow: ResourceImportFlowPayload;
  messageId: string;
  onReturnToUpload: ResourceImportConversationCardProps["onReturnToUpload"];
  onConfirmStructure: ResourceImportConversationCardProps["onConfirmStructure"];
}) {
  const [metadata, setMetadata] = useState<ResourceImportMetadata | null>(null);
  const [items, setItems] = useState<ResourceImportStructureItem[]>(
    flow.preview?.structureAnalysis?.items || [],
  );
  const [error, setError] = useState("");
  const [editingItemKey, setEditingItemKey] = useState<string | null>(null);
  const [modelDraft, setModelDraft] = useState<{
    groupName: string;
    name: string;
    alias: string;
    inheritFrom: string;
    uniqueKey: string;
  }>({
    groupName: "",
    name: "",
    alias: "",
    inheritFrom: "",
    uniqueKey: "",
  });

  useEffect(() => {
    setItems(flow.preview?.structureAnalysis?.items || []);
  }, [flow.preview]);

  useEffect(() => {
    let cancelled = false;
    void getResourceImportMetadata(agentId || undefined)
      .then((response) => {
        if (!cancelled) {
          setMetadata(response);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(extractErrorMessage(err) || "CMDB 元数据加载失败");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [agentId]);

  const updateItem = (
    key: string,
    updater: (item: ResourceImportStructureItem) => ResourceImportStructureItem,
  ) => {
    setItems((current) => current.map((item) => (item.key === key ? updater(item) : item)));
  };

  const openModelConfig = (item: ResourceImportStructureItem) => {
    const nextDraft = {
      groupName: item.selectedGroupName || item.suggestedGroupName || "",
      name: item.modelDraft?.name || item.selectedModelName || item.suggestedModelName || item.resourceCiType || "",
      alias: item.modelDraft?.alias || item.resourceLabel || "",
      inheritFrom: item.modelDraft?.inheritFrom || "",
      uniqueKey: item.modelDraft?.uniqueKey || "",
    };
    setEditingItemKey(item.key);
    setModelDraft({
      ...nextDraft,
      uniqueKey: nextDraft.uniqueKey || getSuggestedUniqueKey(flow.preview, item, metadata, nextDraft),
    });
  };

  const editingItem = editingItemKey
    ? items.find((item) => item.key === editingItemKey) || null
    : null;
  const editingGroupOptions = editingItem ? getStructureGroupOptions(editingItem, metadata) : [];
  const editingModelOptions = editingItem
    ? getStructureModelOptions(editingItem, metadata, modelDraft.groupName || "")
    : [];
  const editingGroupExists = editingItem
    ? isExistingStructureGroup(editingItem, metadata, modelDraft.groupName || "")
    : false;
  const editingModelExists = editingItem
    ? editingModelOptions.some((option) => option.existing && option.name === modelDraft.name)
    : false;
  const editingGroupSelectValue = getStructureSelectValue(modelDraft.groupName, editingGroupOptions);
  const editingModelSelectValue = getStructureSelectValue(modelDraft.name, editingModelOptions);

  const validationError = items.find((item) => {
    const existingGroupSelected = isExistingStructureGroup(
      item,
      metadata,
      item.selectedGroupName || "",
    );
    const existingModelSelected = isExistingStructureModel(item, metadata);
    const requiresGroupCreate = !existingGroupSelected;
    const requiresModelDraft = !existingModelSelected;
    const hasValidModelDraft = item.modelDraft?.name === item.selectedModelName && Boolean(item.modelDraft?.uniqueKey);
    if (requiresGroupCreate && !item.createGroupApproved) {
      return true;
    }
    if (requiresModelDraft && !item.createModelApproved) {
      return true;
    }
    if (requiresModelDraft && !hasValidModelDraft) {
      return true;
    }
    return !(item.selectedGroupName && item.selectedModelName);
  })
    ? "请先完成当前资源的分组/模型确认。"
    : "";

  return (
    <div className="resource-import-conversation-card">
      <FlowSteps stage="structure" />

      <div className="resource-import-stage">
        <section className="resource-import-section">
          <div className="resource-import-section-header">
            <div className="resource-import-section-title">分组与模型预检查</div>
            <span className="resource-import-section-subtitle">
              解析后先判断分组和模型，再进入数据确认
            </span>
          </div>

          {error ? <div className="resource-import-inline-error">{error}</div> : null}

          <div className="resource-import-structure-list">
            {items.map((item) => {
              const groupOptions = getStructureGroupOptions(item, metadata);
              const modelOptions = getStructureModelOptions(
                item,
                metadata,
                item.selectedGroupName || "",
              );
              const existingGroupSelected = isExistingStructureGroup(
                item,
                metadata,
                item.selectedGroupName || "",
              );
              const existingModelSelected = isExistingStructureModel(item, metadata);
              const requiresGroupCreate = !existingGroupSelected;
              const requiresModelDraft = !existingModelSelected;
              const groupSelectValue = getStructureSelectValue(item.selectedGroupName || "", groupOptions);
              const modelSelectValue = getStructureSelectValue(item.selectedModelName || "", modelOptions);

              return (
                <div key={item.key} className="resource-import-structure-card">
                  <div className="resource-import-structure-header">
                    <div>
                      <strong>{item.resourceLabel}</strong>
                      <small>{item.recordCount} 条记录</small>
                    </div>
                    <span className={`resource-import-structure-badge ${item.status}`.trim()}>
                      {getStructureStatusLabel(item.status)}
                    </span>
                  </div>

                  {item.reason ? <p className="resource-import-structure-reason">{item.reason}</p> : null}

                  {item.rawTypeHints?.length ? (
                    <div className="resource-import-structure-hints">
                      原始类型提示：{item.rawTypeHints.join(" / ")}
                    </div>
                  ) : null}

                  <div className="resource-import-structure-grid">
                    <label className="resource-import-structure-field">
                      <span>目标分组</span>
                      <select
                        value={groupSelectValue}
                        onChange={(event) => {
                          const selectedValue = event.target.value;
                          updateItem(item.key, (current) => {
                            const nextGroupName = selectedValue === CUSTOM_STRUCTURE_OPTION_VALUE
                              ? (isExistingStructureGroup(current, metadata, current.selectedGroupName || "")
                                ? ""
                                : String(current.selectedGroupName || "").trim())
                              : selectedValue;
                            const nextModelOptions = getStructureModelOptions(current, metadata, nextGroupName);
                            const nextModelName = nextModelOptions.some(
                              (option) => option.name === current.selectedModelName,
                            )
                              ? current.selectedModelName
                              : (nextModelOptions[0]?.name || current.selectedModelName);
                            const nextGroupExists = isExistingStructureGroup(current, metadata, nextGroupName);
                            return {
                              ...current,
                              selectedGroupName: nextGroupName,
                              selectedModelName: nextModelName,
                              createGroupApproved: nextGroupExists ? false : current.createGroupApproved,
                              createModelApproved: nextModelOptions.some(
                                (option) => option.existing && option.name === nextModelName,
                              )
                                ? false
                                : current.createModelApproved,
                              modelDraft: current.modelDraft?.name === nextModelName
                                ? current.modelDraft
                                : undefined,
                            };
                          });
                        }}
                      >
                        {groupOptions.map((option) => (
                          <option key={option.name} value={option.name}>
                            {option.name}
                          </option>
                        ))}
                        <option value={CUSTOM_STRUCTURE_OPTION_VALUE}>自定义新分组...</option>
                      </select>
                      {groupSelectValue === CUSTOM_STRUCTURE_OPTION_VALUE ? (
                        <input
                          type="text"
                          value={item.selectedGroupName || ""}
                          onChange={(event) => {
                            const nextGroupName = event.target.value;
                            updateItem(item.key, (current) => {
                              const nextModelOptions = getStructureModelOptions(current, metadata, nextGroupName);
                              const nextModelName = nextModelOptions.some(
                                (option) => option.name === current.selectedModelName,
                              )
                                ? current.selectedModelName
                                : "";
                              const nextGroupExists = isExistingStructureGroup(current, metadata, nextGroupName);
                              return {
                                ...current,
                                selectedGroupName: nextGroupName,
                                selectedModelName: nextModelName,
                                createGroupApproved: nextGroupExists ? false : current.createGroupApproved,
                                createModelApproved: nextModelOptions.some(
                                  (option) => option.existing && option.name === nextModelName,
                                )
                                  ? false
                                  : current.createModelApproved,
                                modelDraft: current.modelDraft?.name === nextModelName
                                  ? current.modelDraft
                                  : undefined,
                              };
                            });
                          }}
                          placeholder="输入新分组名称"
                        />
                      ) : null}
                    </label>

                    <label className="resource-import-structure-field">
                      <span>目标模型</span>
                      <select
                        value={modelSelectValue}
                        onChange={(event) =>
                          updateItem(item.key, (current) => ({
                            ...current,
                            selectedModelName: event.target.value === CUSTOM_STRUCTURE_OPTION_VALUE
                              ? (isExistingStructureModel(current, metadata)
                                ? ""
                                : String(current.selectedModelName || "").trim())
                              : event.target.value,
                            createModelApproved: event.target.value === CUSTOM_STRUCTURE_OPTION_VALUE
                              ? current.createModelApproved
                              : false,
                            modelDraft: undefined,
                          }))}
                      >
                        {modelOptions.map((option) => (
                          <option key={option.name} value={option.name}>
                            {option.alias ? `${option.alias} (${option.name})` : option.name}
                          </option>
                        ))}
                        <option value={CUSTOM_STRUCTURE_OPTION_VALUE}>自定义新模型...</option>
                      </select>
                      {modelSelectValue === CUSTOM_STRUCTURE_OPTION_VALUE ? (
                        <input
                          type="text"
                          value={item.selectedModelName || ""}
                          onChange={(event) =>
                            updateItem(item.key, (current) => ({
                              ...current,
                              selectedModelName: event.target.value,
                              createModelApproved: false,
                              modelDraft: undefined,
                            }))}
                          placeholder="输入新模型名称"
                        />
                      ) : null}
                    </label>
                  </div>

                  {requiresGroupCreate ? (
                    <label className="resource-import-structure-check">
                      <input
                        type="checkbox"
                        checked={existingGroupSelected ? false : Boolean(item.createGroupApproved)}
                        disabled={existingGroupSelected}
                        onChange={(event) =>
                          updateItem(item.key, (current) => ({
                            ...current,
                            createGroupApproved: event.target.checked,
                          }))}
                      />
                      <span>{existingGroupSelected ? "当前已选择现有分组，无需创建" : "若当前分组不存在，确认后续创建该分组"}</span>
                    </label>
                  ) : null}

                  {requiresModelDraft ? (
                    <label className="resource-import-structure-check">
                      <input
                        type="checkbox"
                        checked={Boolean(item.createModelApproved)}
                        onChange={(event) =>
                          updateItem(item.key, (current) => ({
                            ...current,
                            createModelApproved: event.target.checked,
                          }))}
                      />
                      <span>确认后续创建该模型，并补齐模型必填参数</span>
                    </label>
                  ) : null}

                  {requiresModelDraft ? (
                    <div className="resource-import-structure-draft">
                      <div>
                        <strong>
                          {item.modelDraft?.alias || item.modelDraft?.name || "尚未配置新模型"}
                        </strong>
                        <small>
                          模型名: {item.modelDraft?.name || "未填写"}
                          {" · "}继承: {item.modelDraft?.inheritFrom || "无"}
                          {" · "}唯一标识: {item.modelDraft?.uniqueKey || "未选择"}
                        </small>
                      </div>
                      <button
                        type="button"
                        className="secondary"
                        onClick={() => openModelConfig(item)}
                      >
                        配置新模型
                      </button>
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        </section>

        {validationError ? (
          <div className="resource-import-inline-error">{validationError}</div>
        ) : null}

        <div className="resource-import-action-row">
          <button
            type="button"
            className="secondary"
            onClick={() =>
              onReturnToUpload({
                flowId: flow.flowId,
                sourceMessageId: messageId,
              })}
          >
            结束本次导入
          </button>
          <button
            type="button"
            className="primary"
            disabled={Boolean(validationError)}
            onClick={() => {
              const next = applyStructureSelectionsToPreview(flow.preview, items);
              onConfirmStructure({
                messageId,
                flowId: flow.flowId,
                preview: next.preview,
                resourceGroups: next.resourceGroups,
                relations: flow.preview?.relations || flow.relations || [],
              });
            }}
          >
            进入数据确认
          </button>
        </div>
      </div>

      {editingItem ? (
        <div className="resource-import-modal-backdrop" onClick={() => setEditingItemKey(null)}>
          <div className="resource-import-modal" onClick={(event) => event.stopPropagation()}>
            <div className="resource-import-modal-header">
              <div>
                <h3>配置新模型</h3>
                <p>
                  为 {editingItem.resourceLabel} 补充模型创建参数。这里只采集参数，真正创建动作仍需用户确认。
                </p>
              </div>
              <button type="button" className="secondary" onClick={() => setEditingItemKey(null)}>
                关闭
              </button>
            </div>

            <div className="resource-import-modal-grid">
              <label className="resource-import-field">
                <span>所属分组</span>
                <select
                  value={editingGroupSelectValue}
                  onChange={(event) =>
                    setModelDraft((current) => {
                      const nextGroupName = event.target.value === CUSTOM_STRUCTURE_OPTION_VALUE
                        ? (editingGroupExists ? "" : String(current.groupName || "").trim())
                        : event.target.value;
                      const nextModelOptions = editingItem
                        ? getStructureModelOptions(editingItem, metadata, nextGroupName)
                        : [];
                      const nextModelName = nextModelOptions.some((option) => option.name === current.name)
                        ? current.name
                        : "";
                      return {
                        ...current,
                        groupName: nextGroupName,
                        name: nextModelName,
                      };
                    })}
                >
                  {editingGroupOptions.map((option) => (
                    <option key={option.name} value={option.name}>
                      {option.name}
                    </option>
                  ))}
                  <option value={CUSTOM_STRUCTURE_OPTION_VALUE}>自定义新分组...</option>
                </select>
                {editingGroupSelectValue === CUSTOM_STRUCTURE_OPTION_VALUE ? (
                  <input
                    type="text"
                    value={modelDraft.groupName}
                    onChange={(event) =>
                      setModelDraft((current) => ({
                        ...current,
                        groupName: event.target.value,
                        name: "",
                      }))}
                    placeholder="输入新分组名称"
                  />
                ) : null}
              </label>

              <label className="resource-import-field">
                <span>模型名</span>
                <select
                  value={editingModelSelectValue}
                  onChange={(event) =>
                    setModelDraft((current) => ({
                      ...current,
                      name: event.target.value === CUSTOM_STRUCTURE_OPTION_VALUE
                        ? (editingModelExists ? "" : String(current.name || "").trim())
                        : event.target.value,
                    }))}
                >
                  {editingModelOptions.map((option) => (
                    <option key={option.name} value={option.name}>
                      {option.alias ? `${option.alias} (${option.name})` : option.name}
                    </option>
                  ))}
                  <option value={CUSTOM_STRUCTURE_OPTION_VALUE}>自定义新模型...</option>
                </select>
                {editingModelSelectValue === CUSTOM_STRUCTURE_OPTION_VALUE ? (
                  <input
                    value={modelDraft.name}
                    onChange={(event) =>
                      setModelDraft((current) => ({
                        ...current,
                        name: event.target.value,
                      }))}
                    placeholder="输入新模型名称"
                  />
                ) : null}
              </label>

              <label className="resource-import-field">
                <span>模型别名</span>
                <input
                  value={modelDraft.alias}
                  onChange={(event) =>
                    setModelDraft((current) => ({
                      ...current,
                      alias: event.target.value,
                    }))}
                  placeholder="例如 网络设备扩展模型"
                />
              </label>

              <label className="resource-import-field">
                <span>继承模型</span>
                <select
                  value={modelDraft.inheritFrom}
                  onChange={(event) =>
                    setModelDraft((current) => {
                      const nextDraft = {
                        ...current,
                        inheritFrom: event.target.value,
                      };
                      const nextOptions = getStructureUniqueKeyOptions(
                        flow.preview,
                        editingItem,
                        metadata,
                        nextDraft,
                      );
                      return {
                        ...nextDraft,
                        uniqueKey: nextOptions.some((option) => option.name === nextDraft.uniqueKey)
                          ? nextDraft.uniqueKey
                          : (nextOptions[0]?.name || ""),
                      };
                    })}
                >
                  <option value="">不继承</option>
                  {getStructureInheritanceOptions(metadata, editingItem).map((option) => (
                    <option key={option.name} value={option.name}>
                      {option.alias ? `${option.alias} (${option.name})` : option.name}
                    </option>
                  ))}
                </select>
              </label>

              <label className="resource-import-field">
                <span>唯一标识</span>
                <select
                  value={modelDraft.uniqueKey}
                  onChange={(event) =>
                    setModelDraft((current) => ({
                      ...current,
                      uniqueKey: event.target.value,
                    }))}
                >
                  <option value="">请选择唯一标识字段</option>
                  {getStructureUniqueKeyOptions(flow.preview, editingItem, metadata, modelDraft).map((option) => (
                    <option key={option.name} value={option.name}>
                      {option.label} ({option.name}) {option.coverage ? `· 覆盖 ${option.coverage}%` : ""}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <div className="resource-import-modal-footer">
              <button type="button" className="secondary" onClick={() => setEditingItemKey(null)}>
                取消
              </button>
              <button
                type="button"
                className="primary"
                disabled={!modelDraft.groupName || !modelDraft.name || (!editingModelExists && !modelDraft.uniqueKey)}
                onClick={() => {
                  updateItem(editingItem.key, (current) => ({
                    ...current,
                    selectedGroupName: modelDraft.groupName,
                    selectedModelName: modelDraft.name,
                    createGroupApproved: editingGroupExists ? false : current.createGroupApproved,
                    createModelApproved: editingModelExists ? false : true,
                    modelDraft: {
                      name: modelDraft.name,
                      alias: modelDraft.alias,
                      inheritFrom: modelDraft.inheritFrom,
                      uniqueKey: modelDraft.uniqueKey,
                    },
                  }));
                  setEditingItemKey(null);
                }}
              >
                保存模型配置
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function ConfirmStage({
  flow,
  messageId,
  onReturnToUpload,
  onBuildTopology,
}: {
  flow: ResourceImportFlowPayload;
  messageId: string;
  onReturnToUpload: ResourceImportConversationCardProps["onReturnToUpload"];
  onBuildTopology: ResourceImportConversationCardProps["onBuildTopology"];
}) {
  const [resourceGroups, setResourceGroups] = useState<ResourceImportGroup[]>(flow.resourceGroups || []);
  const [relations, setRelations] = useState<ResourceImportRelation[]>(flow.relations || []);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editorFocusPreviewKey, setEditorFocusPreviewKey] = useState<string | null>(null);

  useEffect(() => {
    setResourceGroups(flow.resourceGroups || []);
    setRelations(flow.relations || []);
  }, [flow.resourceGroups, flow.relations, messageId]);

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

  const selectedCount = useMemo(
    () => countSelectedRecords(resourceGroups),
    [resourceGroups],
  );
  const ciTypeOptions = useMemo(
    () => Array.from(new Set(resourceGroups.map((group) => group.ciType).filter(Boolean))),
    [resourceGroups],
  );
  const batchEditorColumns = useMemo(
    () => getBatchEditorColumns(flow.preview || null, resourceGroups),
    [flow.preview, resourceGroups],
  );
  const batchColumnAttentionMap = useMemo(() => {
    const entries = batchEditorColumns.map((column) => {
      const needsAttention = resourceGroups.some((group) =>
        group.records.some((record) => {
          const definition = getVisibleAttributeDefinitions(flow.preview || null, record.ciType, record)
            .find((item) => item.name === column.key);
          return fieldNeedsAttention(record, column.key, definition);
        }),
      );
      return [column.key, needsAttention] as const;
    });
    return new Map(entries);
  }, [batchEditorColumns, flow.preview, resourceGroups]);

  useEffect(() => {
    if (!editorOpen || !editorFocusPreviewKey) {
      return;
    }
    const rafId = window.requestAnimationFrame(() => {
      document
        .querySelector(`[data-editor-preview-key="${editorFocusPreviewKey}"]`)
        ?.scrollIntoView({ behavior: "smooth", block: "center", inline: "center" });
    });
    return () => window.cancelAnimationFrame(rafId);
  }, [editorFocusPreviewKey, editorOpen]);

  const openBatchEditor = (previewKey?: string) => {
    setEditorOpen(true);
    setEditorFocusPreviewKey(previewKey || null);
  };

  const closeBatchEditor = () => {
    setEditorOpen(false);
    setEditorFocusPreviewKey(null);
  };

  return (
    <div className="resource-import-conversation-card">
      <FlowSteps stage="confirm" />

      {flow.error ? <div className="resource-import-inline-error">{flow.error}</div> : null}

      <div className="resource-import-stage">
        <div className="resource-import-stat-grid">
          <div className="resource-import-stat-card success">
            <strong>{flow.preview?.summary.resourceCount ?? 0}</strong>
            <span>资产记录数</span>
          </div>
          <div className="resource-import-stat-card success">
            <strong>{flow.preview?.summary.autoCleaned ?? 0}</strong>
            <span>自动清洗</span>
          </div>
          <div className="resource-import-stat-card warning">
            <strong>{flow.preview?.summary.needsConfirmation ?? 0}</strong>
            <span>需要确认</span>
          </div>
          <div className="resource-import-stat-card success">
            <strong>{flow.preview?.summary.qualityScore ?? 0}%</strong>
            <span>数据质量</span>
          </div>
        </div>

        <section className="resource-import-section">
          <div className="resource-import-section-title">🔗 智能字段映射</div>
          <div className="resource-import-mapping-grid">
            {(flow.preview?.mappingSummary || []).slice(0, 8).map((item) => (
              <div key={`${item.sourceField}-${item.targetField}`} className="resource-import-mapping-item">
                <span>{item.sourceField}</span>
                <strong>{item.targetField}</strong>
              </div>
            ))}
          </div>
        </section>

        <section className="resource-import-section cleaning">
          <div className="resource-import-section-title">✅ 数据清洗与标准化报告</div>
          <div className="resource-import-cleaning-list">
            {(flow.preview?.cleaningSummary || []).map((item) => (
              <div key={item.label} className="resource-import-cleaning-item">
                <span>{item.label}</span>
                <strong>{item.count}</strong>
              </div>
            ))}
          </div>
        </section>

        <section className="resource-import-section">
          <div className="resource-import-section-header">
            <div className="resource-import-section-title">📦 当前纳管范围</div>
            <span className="resource-import-section-subtitle">{selectedCount} 条已勾选</span>
          </div>
          <div className="resource-import-inline-notice">
            这里先看摘要，红色表示记录仍不完整。点击编辑后会进入统一的大表格页面，一次性核对全部字段。
          </div>
          <div className="resource-import-action-row">
            <button
              type="button"
              className="secondary"
              onClick={() => downloadConfirmationData(resourceGroups)}
            >
              下载确认数据
            </button>
            <button
              type="button"
              className="secondary"
              onClick={() => openBatchEditor()}
            >
              统一编辑全部数据
            </button>
          </div>
        </section>

        {resourceGroups.map((group) => (
          <section key={group.ciType} className="resource-import-section">
            <div className="resource-import-section-header">
              <div className="resource-import-section-title">
                {getGroupIcon(group)} {group.label}（{group.records.length}条）
              </div>
              <span className="resource-import-section-subtitle">{group.ciType}</span>
            </div>
            <div className="resource-import-table-wrap">
              <table className="resource-import-table">
                <thead>
                  <tr>
                    <th>纳入</th>
                    <th>名称</th>
                    <th>地址/主机</th>
                    <th>类型</th>
                    <th>状态</th>
                    <th>导入策略</th>
                    <th>来源</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {group.records.map((record) => {
                    const recordIssues = getRecordIssues(record);
                    return (
                      <tr
                        key={record.previewKey}
                        className={`${record.selected ? "" : "muted"} ${recordIssues.length ? "needs-attention" : ""}`.trim()}
                      >
                        <td>
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
                        </td>
                        <td>
                          <div className="resource-import-cell-main">
                            <strong>{getDisplayName(record)}</strong>
                            {record.generated ? <small>系统补全</small> : null}
                            <div className="resource-import-inline-tags">
                              {record.existingCi?.ciId !== undefined ? (
                                <span className="resource-import-alert-tag warning">
                                  已存在
                                </span>
                              ) : null}
                              {recordIssues.length ? (
                                <span className="resource-import-alert-tag danger">
                                  数据不完整 {recordIssues.length}
                                </span>
                              ) : null}
                            </div>
                            {recordIssues.length ? (
                              <small className="resource-import-inline-issue">
                                {recordIssues[0]?.message || "字段待确认，请点编辑补齐"}
                              </small>
                            ) : null}
                          </div>
                        </td>
                        <td>{getRecordAddress(record)}</td>
                        <td>{record.ciType}</td>
                        <td>
                          <span className={`resource-import-status-pill ${hasAttentionField(record, "status") || hasAttentionField(record, "alarm_status") ? "attention" : ""}`.trim()}>
                            {getDisplayStatus(record)}
                          </span>
                        </td>
                        <td>
                          <span className={`resource-import-action-pill ${(record.importAction || "create") === "skip" ? "muted" : record.existingCi?.ciId !== undefined ? "warning" : "success"}`.trim()}>
                            {getImportActionLabel(record)}
                          </span>
                        </td>
                        <td>{buildRecordSource(record)}</td>
                        <td>
                          <div className="resource-import-row-actions">
                            <button
                              type="button"
                              onClick={() =>
                                updateRecord(record.previewKey, (current) => ({
                                  ...current,
                                  selected: !current.selected,
                                }))
                              }
                            >
                              {record.selected ? "排除" : "恢复"}
                            </button>
                            <button
                              type="button"
                              onClick={() => openBatchEditor(record.previewKey)}
                            >
                              编辑
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        ))}

        <div className="resource-import-action-row">
          <button
            type="button"
            className="secondary"
            onClick={() => onReturnToUpload({ flowId: flow.flowId, sourceMessageId: messageId })}
          >
            返回上传
          </button>
          <button
            type="button"
            className="primary"
            disabled={flow.locked}
            onClick={() =>
              onBuildTopology({
                messageId,
                flowId: flow.flowId,
                preview: flow.preview || null,
                resourceGroups,
                relations,
              })
            }
          >
            {flow.locked ? "已生成关系卡片" : "确认数据，建立关系 →"}
          </button>
        </div>
      </div>

      {editorOpen ? (
        <div className="resource-import-modal-backdrop" onClick={closeBatchEditor}>
          <div className="resource-import-modal wide" onClick={(event) => event.stopPropagation()}>
            <div className="resource-import-modal-header">
              <div>
                <h3>批量编辑导入数据</h3>
                <p>按 Excel 表格方式统一核对全部记录，横向滚动可查看更多字段。</p>
              </div>
              <button type="button" className="secondary" onClick={closeBatchEditor}>
                关闭
              </button>
            </div>

            <div className="resource-import-batch-editor">
              <div className="resource-import-batch-editor-wrap">
                <table className="resource-import-batch-editor-table">
                  <thead>
                    <tr>
                      <th>纳入</th>
                      <th>分组</th>
                      <th>资源类型</th>
                      <th>导入策略</th>
                      <th className={batchColumnAttentionMap.get("name") ? "attention-head" : ""}>名称</th>
                      {batchEditorColumns
                        .filter((column) => column.key !== "name")
                        .map((column) => (
                          <th
                            key={column.key}
                            className={batchColumnAttentionMap.get(column.key) ? "attention-head" : ""}
                          >
                            {column.label}
                          </th>
                        ))}
                    </tr>
                  </thead>
                  <tbody>
                    {resourceGroups.flatMap((group) =>
                      group.records.map((record) => {
                        const attributeDefinitions = getVisibleAttributeDefinitions(
                          flow.preview || null,
                          record.ciType,
                          record,
                        );
                        const definitionMap = new Map(attributeDefinitions.map((item) => [item.name, item]));
                        const recordIssues = getRecordIssues(record);
                        return (
                          <tr
                            key={`editor-${record.previewKey}`}
                            data-editor-preview-key={record.previewKey}
                            className={`${record.selected ? "" : "muted"} ${recordIssues.length ? "needs-attention" : ""} ${editorFocusPreviewKey === record.previewKey ? "focused" : ""}`.trim()}
                          >
                            <td>
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
                            </td>
                            <td>{group.label}</td>
                            <td>
                              <select
                                value={record.ciType}
                                onChange={(event) =>
                                  updateRecord(record.previewKey, (current) => ({
                                    ...current,
                                    ciType: event.target.value,
                                  }))
                                }
                              >
                                {Array.from(new Set([...ciTypeOptions, record.ciType])).map((ciType) => (
                                  <option key={ciType} value={ciType}>
                                    {ciType}
                                  </option>
                                ))}
                              </select>
                            </td>
                            <td>
                              <select
                                value={record.importAction || (record.existingCi?.ciId !== undefined ? "update" : "create")}
                                onChange={(event) =>
                                  updateRecord(record.previewKey, (current) => ({
                                    ...current,
                                    importAction: event.target.value as "create" | "update" | "skip",
                                  }))
                                }
                              >
                                {getImportActionOptions(record).map((option) => (
                                  <option key={option.value} value={option.value}>
                                    {option.label}
                                  </option>
                                ))}
                              </select>
                            </td>
                            <td className={fieldNeedsAttention(record, "name") ? "attention-cell" : ""}>
                              <input
                                value={record.name || ""}
                                title={getFieldAttentionMessage(record, "name")}
                                onChange={(event) =>
                                  updateRecord(record.previewKey, (current) => ({
                                    ...current,
                                    name: event.target.value,
                                  }))
                                }
                              />
                            </td>
                            {batchEditorColumns
                              .filter((column) => column.key !== "name")
                              .map((column) => {
                                const definition = definitionMap.get(column.key);
                                const choiceOptions = getChoiceOptions(definition);
                                const currentValue = record.attributes[column.key] || "";
                                const isAttention = fieldNeedsAttention(record, column.key, definition);
                                const attentionMessage = getFieldAttentionMessage(record, column.key, definition);
                                return (
                                  <td key={`${record.previewKey}-${column.key}`} className={isAttention ? "attention-cell" : ""}>
                                    {choiceOptions.length ? (
                                      <select
                                        value={currentValue}
                                        title={attentionMessage}
                                        onChange={(event) =>
                                          updateRecord(record.previewKey, (current) => ({
                                            ...current,
                                            attributes: {
                                              ...current.attributes,
                                              [column.key]: event.target.value,
                                            },
                                          }))
                                        }
                                      >
                                        <option value="">请选择</option>
                                        {choiceOptions.map((option) => (
                                          <option key={`${column.key}-${option.value}`} value={option.value}>
                                            {option.label || option.value}
                                          </option>
                                        ))}
                                      </select>
                                    ) : (
                                      <input
                                        value={currentValue}
                                        title={attentionMessage}
                                        onChange={(event) =>
                                          updateRecord(record.previewKey, (current) => ({
                                            ...current,
                                            attributes: {
                                              ...current.attributes,
                                              [column.key]: event.target.value,
                                            },
                                          }))
                                        }
                                      />
                                    )}
                                  </td>
                                );
                              })}
                          </tr>
                        );
                      }),
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="resource-import-modal-footer">
              <div className="resource-import-inline-notice">
                红色单元格表示当前字段仍需确认，关闭后主列表会继续保留红色提示。
              </div>
              <button type="button" className="primary" onClick={closeBatchEditor}>
                完成编辑
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function TopologyStage({
  flow,
  messageId,
  onBackToConfirm,
  onSubmitImport,
}: {
  flow: ResourceImportFlowPayload;
  messageId: string;
  onBackToConfirm: ResourceImportConversationCardProps["onBackToConfirm"];
  onSubmitImport: ResourceImportConversationCardProps["onSubmitImport"];
}) {
  const [relations, setRelations] = useState<ResourceImportRelation[]>(flow.relations || []);

  useEffect(() => {
    setRelations(flow.relations || []);
  }, [flow.relations, messageId]);

  const selectedRecordCount = useMemo(
    () => countSelectedRecords(flow.resourceGroups || []),
    [flow.resourceGroups],
  );
  const selectedRelationCount = useMemo(
    () => relations.filter((relation) => relation.selected).length,
    [relations],
  );

  const topologyInsights = useMemo(() => {
    const selectedRelations = relations.filter((relation) => relation.selected);
    if (!selectedRelations.length) {
      return ["已根据网段、命名和部署信息推断关系。"];
    }
    return selectedRelations.slice(0, 4).map((relation) => {
      const confidenceLabel =
        relation.confidence === "high"
          ? "高"
          : relation.confidence === "medium"
            ? "中"
            : "低";
      return `${relation.reason || `${relation.sourceKey} → ${relation.targetKey}`}（${confidenceLabel}置信度）`;
    });
  }, [relations]);

  const chartOption = useMemo(() => {
    const nodes = (flow.resourceGroups || [])
      .flatMap((group) => group.records)
      .filter((record) => record.selected)
      .map((record) => ({
        id: record.previewKey,
        name: record.name,
        category: record.category,
        symbolSize: record.generated ? 34 : 42,
        value: record.ciType,
      }));

    const links = relations
      .filter((relation) => relation.selected)
      .map((relation) => ({
        source: relation.sourceKey,
        target: relation.targetKey,
        value: relation.relationType,
        label: {
          show: true,
          formatter: relation.relationType,
          fontSize: 10,
        },
        lineStyle: {
          opacity:
            relation.confidence === "high"
              ? 0.92
              : relation.confidence === "medium"
                ? 0.72
                : 0.52,
          width: relation.confidence === "high" ? 2 : 1,
          curveness: 0.18,
        },
      }));

    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "item",
      },
      legend: [
        {
          bottom: 0,
          textStyle: { color: "#64748b" },
          data: ["resource", "business", "dcim", "ipam"],
        },
      ],
      series: [
        {
          type: "graph",
          layout: "force",
          roam: true,
          force: {
            repulsion: 220,
            edgeLength: 110,
          },
          categories: [
            { name: "resource" },
            { name: "business" },
            { name: "dcim" },
            { name: "ipam" },
          ],
          label: {
            show: true,
            color: "#334155",
            fontSize: 11,
          },
          lineStyle: {
            color: "#94a3b8",
          },
          itemStyle: {
            borderColor: "rgba(255,255,255,0.9)",
            borderWidth: 1.2,
          },
          color: ["#5aa7ff", "#7c3aed", "#f59e0b", "#14b8a6"],
          data: nodes,
          links,
        },
      ],
    };
  }, [flow.resourceGroups, relations]);

  return (
    <div className="resource-import-conversation-card">
      <FlowSteps stage="topology" />

      <div className="resource-import-stage">
        <section className="resource-import-section topology">
          <div className="resource-import-section-title">🧠 智能拓扑推断</div>
          <div className="resource-import-topology-summary">
            <div>已选资源：{selectedRecordCount} 条</div>
            <div>推断关系：{selectedRelationCount} 条</div>
            <div>推断质量：{flow.preview?.summary.qualityScore ?? 0}%</div>
          </div>
          <ul className="resource-import-insight-list">
            {topologyInsights.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>

        <section className="resource-import-section">
          <div className="resource-import-section-header">
            <div className="resource-import-section-title">🔗 资源拓扑关系</div>
            <span className="resource-import-section-subtitle">{selectedRelationCount} 条关系</span>
          </div>
          <div className="resource-import-topology-chart">
            <ReactECharts option={chartOption} style={{ height: 320 }} notMerge lazyUpdate />
          </div>
        </section>

        <section className="resource-import-section">
          <div className="resource-import-section-title">推断的关系列表</div>
          <div className="resource-import-relation-list">
            {relations.map((relation) => (
              <label
                key={`${relation.sourceKey}-${relation.targetKey}-${relation.relationType}`}
                className="resource-import-relation-item"
              >
                <input
                  type="checkbox"
                  checked={relation.selected}
                  disabled={flow.readonly}
                  onChange={(event) =>
                    setRelations((current) =>
                      current.map((item) =>
                        item.sourceKey === relation.sourceKey
                        && item.targetKey === relation.targetKey
                        && item.relationType === relation.relationType
                          ? {
                              ...item,
                              selected: event.target.checked,
                            }
                          : item,
                      ),
                    )
                  }
                />
                <div>
                  <strong>
                    {relation.sourceKey} → {relation.targetKey}
                  </strong>
                  <p>
                    {relation.relationType}
                    {relation.requiresModelRelation ? " · 需先创建模型关系" : ""}
                    {" · "}
                    {relation.reason || "AI 自动推断"}
                  </p>
                </div>
              </label>
            ))}
          </div>
        </section>

        {flow.readonly ? (
          <div className="resource-import-inline-notice">这是已导入任务的拓扑快照，仅用于回看。</div>
        ) : null}

        <div className="resource-import-action-row">
          {!flow.readonly ? (
            <button
              type="button"
              className="secondary"
              onClick={() =>
                onBackToConfirm({
                  messageId,
                  flowId: flow.flowId,
                })
              }
            >
              返回修改
            </button>
          ) : null}
          {!flow.readonly ? (
            <button
              type="button"
              className="primary"
              disabled={flow.locked}
              onClick={() =>
                onSubmitImport({
                  messageId,
                  flowId: flow.flowId,
                  preview: flow.preview || null,
                  resourceGroups: flow.resourceGroups || [],
                  relations,
                })
              }
            >
              {flow.locked ? "导入任务已启动" : "确认导入CMDB"}
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function ImportingStage({
  flow,
}: {
  flow: ResourceImportFlowPayload;
}) {
  return (
    <div className="resource-import-conversation-card">
      <FlowSteps stage="importing" />

      {flow.error ? <div className="resource-import-inline-error">{flow.error}</div> : null}

      <div className="resource-import-section resource-import-importing-card">
        <div className="resource-import-result-icon">⏳</div>
        <div className="resource-import-importing-title">正在将资源写入 CMDB 系统，请稍候...</div>
        <div className="resource-import-parse-bar">
          <div className="resource-import-parse-bar-fill resource-import-importing-fill" />
        </div>
        <div className="resource-import-parse-status">
          {flow.status === "error" ? "导入失败" : "导入中..."}
        </div>
      </div>
    </div>
  );
}

function ResultStage({
  flow,
  onContinueImport,
  onOpenSystemTopology,
  onScrollToStage,
}: {
  flow: ResourceImportFlowPayload;
  onContinueImport: ResourceImportConversationCardProps["onContinueImport"];
  onOpenSystemTopology: ResourceImportConversationCardProps["onOpenSystemTopology"];
  onScrollToStage: ResourceImportConversationCardProps["onScrollToStage"];
}) {
  const structureResults = flow.result?.structureResults || [];
  const resourceResults = flow.result?.resourceResults || [];
  const relationResults = flow.result?.relationResults || [];

  return (
    <div className="resource-import-conversation-card">
      <FlowSteps stage="result" />

      {flow.error ? <div className="resource-import-inline-error">{flow.error}</div> : null}

      <div className="resource-import-stage">
        <div className="resource-import-result">
          <div className="resource-import-result-icon">
            {flow.result?.status === "success" ? "✅" : "⚠️"}
          </div>
          <h3>{flow.result?.status === "success" ? "导入成功！" : "导入完成"}</h3>
          <p>
            {flow.result?.status === "success"
              ? "资源已成功录入 CMDB，后续可继续追加新的清单。"
              : "导入已执行完成，请根据结果检查失败与跳过项。"}
          </p>
        </div>

        <div className="resource-import-stat-grid">
          <div className="resource-import-stat-card success">
            <strong>{flow.result?.created ?? 0}</strong>
            <span>CI实例</span>
          </div>
          <div className="resource-import-stat-card success">
            <strong>{flow.result?.relationsCreated ?? 0}</strong>
            <span>关系建立</span>
          </div>
          <div className="resource-import-stat-card warning">
            <strong>{flow.result?.skipped ?? 0}</strong>
            <span>跳过项</span>
          </div>
          <div className="resource-import-stat-card success">
            <strong>{flow.preview?.summary.qualityScore ?? 0}%</strong>
            <span>数据完整性</span>
          </div>
        </div>

        {flow.result?.error ? (
          <div className="resource-import-inline-error">
            {flow.result.error}
          </div>
        ) : null}

        {structureResults.length ? (
          <section className="resource-import-section">
            <div className="resource-import-section-header">
              <div className="resource-import-section-title">结构处理结果</div>
              <span className="resource-import-section-subtitle">{structureResults.length} 条</span>
            </div>
            <div className="resource-import-result-list">
              {structureResults.map((item, index) => (
                <div
                  key={`${item.kind}-${item.sourceType || item.groupName || item.modelName || item.name || index}`}
                  className={`resource-import-result-item ${item.status || "success"}`.trim()}
                >
                  <div>
                    <strong>
                      {item.kind === "relation-config"
                        ? `${item.sourceType} → ${item.relationType} → ${item.targetType}`
                        : item.groupName || item.modelName || item.name || item.kind}
                    </strong>
                    <p>{item.message}</p>
                  </div>
                  <div className="resource-import-result-meta">
                    <span>{item.status || "success"}</span>
                    {item.ctrId !== undefined ? <code>CTR ID: {item.ctrId}</code> : null}
                  </div>
                </div>
              ))}
            </div>
          </section>
        ) : null}

        {resourceResults.length ? (
          <section className="resource-import-section">
            <div className="resource-import-section-header">
              <div className="resource-import-section-title">资源导入结果</div>
              <span className="resource-import-section-subtitle">{resourceResults.length} 条</span>
            </div>
            <div className="resource-import-result-list">
              {resourceResults.map((item) => (
                <div key={item.previewKey} className={`resource-import-result-item ${item.status}`.trim()}>
                  <div>
                    <strong>{item.previewKey}</strong>
                    <p>{item.message}</p>
                  </div>
                  <div className="resource-import-result-meta">
                    <span>{item.status}</span>
                    {item.ciId !== undefined ? <code>CI ID: {item.ciId}</code> : null}
                  </div>
                </div>
              ))}
            </div>
          </section>
        ) : null}

        {relationResults.length ? (
          <section className="resource-import-section">
            <div className="resource-import-section-header">
              <div className="resource-import-section-title">关系导入结果</div>
              <span className="resource-import-section-subtitle">{relationResults.length} 条</span>
            </div>
            <div className="resource-import-result-list">
              {relationResults.map((item, index) => (
                <div
                  key={`${item.sourceKey}-${item.targetKey}-${index}`}
                  className={`resource-import-result-item ${item.status}`.trim()}
                >
                  <div>
                    <strong>{item.sourceKey} → {item.targetKey}</strong>
                    <p>{item.message}</p>
                  </div>
                  <div className="resource-import-result-meta">
                    <span>{item.status}</span>
                  </div>
                </div>
              ))}
            </div>
          </section>
        ) : null}

        <div className="resource-import-action-row">
          <button
            type="button"
            className="secondary"
            onClick={() => onContinueImport({ flowId: flow.flowId })}
          >
            继续导入
          </button>
          <button
            type="button"
            className="primary"
            onClick={() => onOpenSystemTopology({ flowId: flow.flowId })}
          >
            查看完整拓扑
          </button>
        </div>
      </div>
    </div>
  );
}

export function ResourceImportConversationCard({
  agentId,
  message,
  onUploadFiles,
  onStartParse,
  onParseResolved,
  onParseFailed,
  onReturnToUpload,
  onBuildTopology,
  onConfirmStructure,
  onBackToConfirm,
  onSubmitImport,
  onContinueImport,
  onOpenSystemTopology,
  onScrollToStage,
  resolveFiles,
  releaseFiles,
}: ResourceImportConversationCardProps) {
  const flow = message.resourceImportFlow;
  if (!flow) {
    return null;
  }

  if (flow.stage === "intro") {
    return (
      <IntroStage
        agentId={agentId}
        flow={flow}
        flowId={flow.flowId}
        messageId={message.id}
        onUploadFiles={onUploadFiles}
        onReturnToUpload={onReturnToUpload}
        onStartParse={onStartParse}
      />
    );
  }

  if (flow.stage === "parsing") {
    return (
      <ParsingStage
        agentId={agentId}
        flow={flow}
        messageId={message.id}
        resolveFiles={resolveFiles}
        releaseFiles={releaseFiles}
        onParseResolved={onParseResolved}
        onParseFailed={onParseFailed}
        onReturnToUpload={onReturnToUpload}
      />
    );
  }

  if (flow.stage === "structure") {
    return (
      <StructureStage
        agentId={agentId}
        flow={flow}
        messageId={message.id}
        onReturnToUpload={onReturnToUpload}
        onConfirmStructure={onConfirmStructure}
      />
    );
  }

  if (flow.stage === "confirm") {
    return (
      <ConfirmStage
        flow={flow}
        messageId={message.id}
        onReturnToUpload={onReturnToUpload}
        onBuildTopology={onBuildTopology}
      />
    );
  }

  if (flow.stage === "topology") {
    return (
      <TopologyStage
        flow={flow}
        messageId={message.id}
        onBackToConfirm={onBackToConfirm}
        onSubmitImport={onSubmitImport}
      />
    );
  }

  if (flow.stage === "importing") {
    return <ImportingStage flow={flow} />;
  }

  return (
    <ResultStage
      flow={flow}
      onContinueImport={onContinueImport}
      onOpenSystemTopology={onOpenSystemTopology}
      onScrollToStage={onScrollToStage}
    />
  );
}
