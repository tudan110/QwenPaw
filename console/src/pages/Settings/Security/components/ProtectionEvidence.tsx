import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Empty,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import {
  securityEvidenceApi,
  type ProtectionEvidence as Evidence,
  type RedactionCheck,
} from "@/api/modules/securityEvidence";

export function ProtectionEvidence() {
  const { t } = useTranslation();
  const [data, setData] = useState<Evidence>();
  const [check, setCheck] = useState<RedactionCheck>();
  const [error, setError] = useState<"adminReadError" | "checkError" | "">("");
  const [checking, setChecking] = useState(false);
  const [loading, setLoading] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    setData(undefined);
    setCheck(undefined);
    void securityEvidenceApi
      .protection()
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch(() => {
        if (!cancelled) setError("adminReadError");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [revision]);
  const runCheck = async () => {
    setChecking(true);
    setError("");
    setCheck(undefined);
    try {
      setCheck(await securityEvidenceApi.checkRedaction());
    } catch {
      setError("checkError");
    } finally {
      setChecking(false);
    }
  };
  const status = (value: boolean) => (
    <Tag color={value ? "blue" : "default"}>
      {t(
        value
          ? "trustedEvidence.configEnabled"
          : "trustedEvidence.configDisabled",
        value ? "Configured on" : "Configured off",
      )}
    </Tag>
  );
  return (
    <Space
      direction="vertical"
      size="middle"
      style={{ width: "100%", padding: 20 }}
    >
      <Space wrap>
        <Button
          onClick={() => setRevision((value) => value + 1)}
          loading={loading}
          disabled={checking}
        >
          {t("trustedEvidence.refresh", "Refresh snapshot")}
        </Button>
        {data && (
          <Typography.Text type="secondary">
            {t("trustedEvidence.queriedAt", "Read at")}:{" "}
            {new Date(data.queried_at).toLocaleString()}
          </Typography.Text>
        )}
      </Space>
      {error && (
        <Alert
          type="error"
          showIcon
          message={t(
            `trustedEvidence.${error}`,
            error === "checkError"
              ? "Sample check failed. No result has been recorded."
              : "Unable to read evidence. A verified administrator session is required; check access and service status.",
          )}
        />
      )}
      <Alert
        type="info"
        showIcon
        message={t(
          "trustedEvidence.configBoundary",
          "This view shows resolved configuration. It does not verify delivery through every channel or prove runtime content-safety coverage. Missing or unreadable configuration can fall back to built-in defaults.",
        )}
      />
      <Card
        title={t("trustedEvidence.redaction", "Output redaction")}
        loading={loading}
      >
        {data ? (
          <>
            <Descriptions size="small" column={2} bordered>
              <Descriptions.Item label={t("trustedEvidence.status", "Status")}>
                {status(data.output_guard.active)}
              </Descriptions.Item>
              <Descriptions.Item label={t("trustedEvidence.mode", "Mode")}>
                {data.output_guard.mode}
              </Descriptions.Item>
              <Descriptions.Item
                label={t(
                  "trustedEvidence.streaming",
                  "Streaming masking configuration",
                )}
              >
                {status(data.output_guard.mask_streaming)}
              </Descriptions.Item>
              <Descriptions.Item
                label={t("trustedEvidence.lexicon", "Lexicon source")}
              >
                {t(
                  `trustedEvidence.${data.output_guard.lexicon}`,
                  data.output_guard.lexicon,
                )}
              </Descriptions.Item>
            </Descriptions>
            <div style={{ marginTop: 16 }}>
              {data.output_guard.patterns.map((rule) => (
                <Tag key={rule.id} color={rule.enabled ? "blue" : "default"}>
                  {rule.id} ·{" "}
                  {t(
                    rule.enabled
                      ? "trustedEvidence.configEnabled"
                      : "trustedEvidence.configDisabled",
                  )}
                </Tag>
              ))}
            </div>
          </>
        ) : (
          <Empty
            description={t(
              "trustedEvidence.noSnapshot",
              "No readable snapshot",
            )}
          />
        )}
      </Card>
      <Card
        title={t("trustedEvidence.sampleTitle", "Fictional sample check")}
        extra={
          <Button
            onClick={runCheck}
            loading={checking}
            disabled={!data || loading}
          >
            {t("trustedEvidence.runCheck", "Run sample check")}
          </Button>
        }
      >
        <Typography.Paragraph type="secondary">
          {t(
            "trustedEvidence.sampleBoundary",
            "Runs fixed fictional values through the existing redactor. It sends no model or MCP requests, changes no settings, and does not test full conversations, prompt injection, or harmful-content handling.",
          )}
        </Typography.Paragraph>
        {check ? (
          <>
            <Typography.Paragraph>
              {t("trustedEvidence.checkedAt", "Checked at")}:{" "}
              {new Date(check.checked_at).toLocaleString()} ·{" "}
              {status(check.active)}
            </Typography.Paragraph>
            <Table
              pagination={false}
              size="small"
              dataSource={check.results}
              rowKey="label"
              scroll={{ x: 760 }}
              columns={[
                {
                  title: t("trustedEvidence.sample", "Sample"),
                  dataIndex: "label",
                },
                {
                  title: t("trustedEvidence.input", "Fictional input"),
                  dataIndex: "input",
                  render: (text: string) => (
                    <Typography.Text code>{text}</Typography.Text>
                  ),
                },
                {
                  title: t("trustedEvidence.output", "Actual output"),
                  dataIndex: "output",
                  render: (text: string) => (
                    <Typography.Text code>{text}</Typography.Text>
                  ),
                },
                {
                  title: t("trustedEvidence.change", "Observed change"),
                  dataIndex: "changed",
                  render: (value: boolean) =>
                    t(
                      value
                        ? "trustedEvidence.changed"
                        : "trustedEvidence.unchanged",
                    ),
                },
                {
                  title: t("trustedEvidence.hits", "Rule hits"),
                  dataIndex: "hit_ids",
                  render: (ids: string[]) => ids.join(", ") || "—",
                },
              ]}
            />
          </>
        ) : (
          <Empty
            description={t(
              "trustedEvidence.notChecked",
              "No check has been run",
            )}
          />
        )}
      </Card>
      <Card
        title={t(
          "trustedEvidence.external",
          "External services and endpoint controls",
        )}
      >
        {data && (
          <Descriptions size="small" column={2} bordered>
            <Descriptions.Item
              label={t(
                "trustedEvidence.productionGuards",
                "Production guard configuration",
              )}
            >
              {status(data.mcp_boundary.production_guards)}
            </Descriptions.Item>
            <Descriptions.Item
              label={t(
                "trustedEvidence.hostCount",
                "Explicitly declared MCP hosts",
              )}
            >
              {data.mcp_boundary.declared_host_count}
            </Descriptions.Item>
          </Descriptions>
        )}
        <Typography.Paragraph style={{ marginTop: 12 }}>
          {t(
            "trustedEvidence.externalBoundary",
            "MCP endpoint checks and component access policies have separate scopes. The explicit-host count excludes built-in local/service-domain allowances. Network reachability, certificates, device controls and actual policy enforcement require separate verification.",
          )}
        </Typography.Paragraph>
        <Space wrap>
          <Link to="/mcp">
            {t("trustedEvidence.openMcp", "View MCP services and permissions")}
          </Link>
          <Link to="/inbox">
            {t("trustedEvidence.openInbox", "View pending approvals")}
          </Link>
        </Space>
      </Card>
    </Space>
  );
}
