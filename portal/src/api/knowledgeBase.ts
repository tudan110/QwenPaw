/**
 * Typed client for the qwenpaw knowledge_kb subsystem
 * (FastAPI router at /api/portal/knowledge/*).
 *
 * All calls go through nginx /portal-api/* → qwenpaw /api/portal/* in prod,
 * Vite proxy /portal-api/* → http://127.0.0.1:8088/api/portal/* in dev.
 */
import { requestPortalApi } from "./portalWorkorders";

export interface KbHealth {
  status: string;
  llm_enabled: boolean;
  embedding_enabled: boolean;
  embedding_key_configured: boolean;
  embedding_env_forced_off: boolean;
}

export interface KbEvidenceSource {
  filename?: string;
  scope_label?: string;
  locator?: string;
  source_type?: string;
}

export interface KbEvidence {
  id: string;
  title: string;
  excerpt: string;
  confidence: number;
  confidence_band: "high" | "medium" | "low";
  source: KbEvidenceSource;
  highlight_terms?: string[];
}

export interface KbQueryResponse {
  summary: string;
  overall_confidence: number | null;
  layout_mode: "rich" | "compact_chat";
  answer_intent?: string;
  relevant_evidence: KbEvidence[];
  evidence_boundary_statement?: string;
  flags: {
    insufficient_evidence: boolean;
    contradictory_evidence: boolean;
    access_limited_evidence: boolean;
    stale_evidence: boolean;
  };
}

export interface KbSourceRecord {
  id: number;
  filename: string;
  source_type: string;
  source_scope: string;
  uploaded_at: string;
  archived_at?: string | null;
  archive_reason?: string | null;
  unit_count?: number;
  display_title?: string | null;
  builtin_pack_id?: string | null;
  builtin_pack_version?: string | null;
  meta?: Record<string, unknown>;
  note?: string | null;
}

export interface KbSourceRecordsResponse {
  total: number;
  items: KbSourceRecord[];
}

export interface KbIngestionJob {
  job_id: string;
  filename: string;
  source_type: string;
  status: "queued" | "processing" | "succeeded" | "failed" | string;
  progress_pct?: number;
  current_stage?: string;
  unit_count?: number;
  note?: string;
  poll_url?: string;
}

const KB_PREFIX = "/knowledge";

export async function getKnowledgeHealth(): Promise<KbHealth> {
  return requestPortalApi<KbHealth>(`${KB_PREFIX}/health`);
}

export async function queryKnowledge(
  query: string,
  filters: Record<string, string | undefined> = {},
): Promise<KbQueryResponse> {
  return requestPortalApi<KbQueryResponse>(`${KB_PREFIX}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, filters }),
  });
}

export async function listKnowledgeSourceRecords(params: {
  limit?: number;
  offset?: number;
  include_archived?: boolean;
  source_scope?: string;
  source_type?: string;
  filename?: string;
} = {}): Promise<KbSourceRecordsResponse> {
  const search = new URLSearchParams();
  if (params.limit !== undefined) search.set("limit", String(params.limit));
  if (params.offset !== undefined) search.set("offset", String(params.offset));
  if (params.include_archived) search.set("include_archived", "true");
  if (params.source_scope) search.set("source_scope", params.source_scope);
  if (params.source_type) search.set("source_type", params.source_type);
  if (params.filename) search.set("filename", params.filename);
  const qs = search.toString();
  return requestPortalApi<KbSourceRecordsResponse>(
    `${KB_PREFIX}/source-records${qs ? `?${qs}` : ""}`,
  );
}

export async function archiveKnowledgeSources(
  sourceRecordIds: number[],
  reason = "manual archive from portal",
): Promise<unknown> {
  return requestPortalApi(`${KB_PREFIX}/source-records/archive`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_record_ids: sourceRecordIds, reason }),
  });
}

export async function unarchiveKnowledgeSources(
  sourceRecordIds: number[],
): Promise<unknown> {
  return requestPortalApi(`${KB_PREFIX}/source-records/unarchive`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_record_ids: sourceRecordIds }),
  });
}

export async function manualEntryKnowledge(payload: {
  title: string;
  content: string;
  tags?: string[];
  source_query?: string;
}): Promise<unknown> {
  return requestPortalApi(`${KB_PREFIX}/manual-entry`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

/**
 * Upload a file. Multipart fetch handled directly (requestPortalApi only
 * does JSON). Path matches Vite/nginx proxy rules.
 */
export async function ingestKnowledgeFile(
  file: File,
): Promise<KbIngestionJob> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`/portal-api${KB_PREFIX}/ingest`, {
    method: "POST",
    body: form,
  });
  if (!response.ok) {
    const errorText = await response.text().catch(() => "");
    throw new Error(errorText || "上传失败");
  }
  return response.json();
}

export async function getIngestionJobProgress(
  jobId: string,
): Promise<KbIngestionJob> {
  return requestPortalApi<KbIngestionJob>(
    `${KB_PREFIX}/ingestion-jobs/${encodeURIComponent(jobId)}/progress`,
  );
}
