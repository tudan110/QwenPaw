import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  DatePicker,
  Empty,
  Input,
  Select,
  Space,
  Table,
  Typography,
} from "antd";
import { useTranslation } from "react-i18next";
import {
  securityEvidenceApi,
  type AuditPage,
  type AuditRecord,
} from "@/api/modules/securityEvidence";
import { auditCsvCell } from "@/utils/evidenceDisplay";

export function AuditEvidence() {
  const { t } = useTranslation();
  const [data, setData] = useState<AuditPage>();
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(false);
  const [filters, setFilters] = useState({
    agent_id: "",
    tool_name: "",
    decision: "",
  });
  const [times, setTimes] = useState<{ since?: number; until?: number }>({});
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState<Record<string, string | number>>({
    limit: 50,
    offset: 0,
  });
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);
    setData(undefined);
    void securityEvidenceApi
      .audit(query)
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [query]);
  const applyFilters = () => {
    setPage(1);
    setQuery({
      ...Object.fromEntries(
        Object.entries(filters).filter(([, value]) => value),
      ),
      ...times,
      limit: 50,
      offset: 0,
    });
  };
  const load = (nextPage: number) => {
    setPage(nextPage);
    setQuery({ ...query, offset: (nextPage - 1) * 50 });
  };
  const exportPage = () => {
    if (!data?.records.length) return;
    const fields: (keyof AuditRecord)[] = [
      "ts",
      "agent_id",
      "session_id",
      "tool_name",
      "target",
      "decision",
      "reason",
    ];
    const rows = [
      ["record_kind", "policy_decision", "execution_result", "not_recorded"],
      ["queried_at", data.queried_at, "scope", "current_page", "page", page],
      fields,
      ...data.records.map((record) => fields.map((field) => record[field])),
    ];
    const url = URL.createObjectURL(
      new Blob(
        [
          "\uFEFF",
          rows.map((row) => row.map(auditCsvCell).join(",")).join("\r\n"),
        ],
        { type: "text/csv;charset=utf-8" },
      ),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `policy-audit-page-${page}.csv`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return (
    <Space
      direction="vertical"
      size="middle"
      style={{ width: "100%", padding: 20 }}
    >
      <Alert
        type="info"
        showIcon
        message={t(
          "trustedEvidence.auditBoundary",
          "These are policy decisions. Allow means permission was granted, not that execution succeeded. Execution outcomes are not recorded here; this view does not verify six-month retention or tamper resistance.",
        )}
      />
      <Space wrap>
        <Input
          aria-label={t("trustedEvidence.agent", "Agent ID")}
          placeholder={t("trustedEvidence.agent", "Agent ID")}
          value={filters.agent_id}
          maxLength={200}
          onChange={(e) => setFilters({ ...filters, agent_id: e.target.value })}
          style={{ width: 160 }}
        />
        <Input
          aria-label={t("trustedEvidence.tool", "Tool name")}
          placeholder={t("trustedEvidence.tool", "Tool name")}
          value={filters.tool_name}
          maxLength={200}
          onChange={(e) =>
            setFilters({ ...filters, tool_name: e.target.value })
          }
          style={{ width: 180 }}
        />
        <Select
          aria-label={t("trustedEvidence.decision", "Policy decision")}
          value={filters.decision}
          onChange={(decision) => setFilters({ ...filters, decision })}
          style={{ width: 170 }}
          options={[
            {
              value: "",
              label: t("trustedEvidence.allDecisions", "All decisions"),
            },
            ...["allow", "deny", "ask", "sandbox_fallback"].map((value) => ({
              value,
              label: t(`trustedEvidence.decisionLabels.${value}`, value),
            })),
          ]}
        />
        <DatePicker.RangePicker
          showTime
          onChange={(values) =>
            setTimes(
              values?.[0] && values[1]
                ? { since: values[0].valueOf(), until: values[1].valueOf() }
                : {},
            )
          }
        />
        <Button onClick={applyFilters} loading={loading}>
          {t("trustedEvidence.query", "Query")}
        </Button>
        <Button
          onClick={exportPage}
          disabled={loading || !data?.records.length}
        >
          {t("trustedEvidence.exportPage", "Export displayed page")}
        </Button>
      </Space>
      {error && (
        <Alert
          type="error"
          showIcon
          message={t("trustedEvidence.adminReadError")}
        />
      )}
      {data && (
        <Typography.Text type="secondary">
          {data.source} · {t("trustedEvidence.queriedAt")}:{" "}
          {new Date(data.queried_at).toLocaleString()} ·{" "}
          {t(
            "trustedEvidence.executionUnknown",
            "Execution result: not recorded",
          )}
        </Typography.Text>
      )}
      {data && data.storage_status !== "available" && (
        <Alert
          type="warning"
          showIcon
          message={t(`trustedEvidence.storage.${data.storage_status}`)}
        />
      )}
      <Table<AuditRecord>
        rowKey="rowid"
        loading={loading}
        size="small"
        dataSource={data?.records ?? []}
        scroll={{ x: 1100 }}
        locale={{
          emptyText: (
            <Empty
              description={t(
                "trustedEvidence.noAudit",
                "No matching readable policy records",
              )}
            />
          ),
        }}
        pagination={{
          current: page,
          pageSize: 50,
          total: data?.total ?? 0,
          showSizeChanger: false,
          onChange: (next) => void load(next),
        }}
        columns={[
          {
            title: t("trustedEvidence.time", "Time"),
            dataIndex: "ts",
            width: 175,
            render: (value: number) => new Date(value).toLocaleString(),
          },
          {
            title: t("trustedEvidence.agent"),
            dataIndex: "agent_id",
            width: 120,
          },
          {
            title: t("trustedEvidence.session", "Session"),
            dataIndex: "session_id",
            width: 120,
          },
          {
            title: t("trustedEvidence.tool"),
            dataIndex: "tool_name",
            width: 160,
          },
          {
            title: t("trustedEvidence.target", "Target"),
            dataIndex: "target",
            width: 240,
          },
          {
            title: t("trustedEvidence.decision", "Policy decision"),
            dataIndex: "decision",
            width: 140,
            render: (value: string) =>
              t(`trustedEvidence.decisionLabels.${value}`, value),
          },
          {
            title: t("trustedEvidence.reason", "Reason"),
            dataIndex: "reason",
            width: 260,
          },
        ]}
      />
    </Space>
  );
}
