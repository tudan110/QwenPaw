import { request } from "../request";

export interface ControlState {
  frozen: number;
  epoch: number;
  reason: string;
  updated_at: number;
}

export interface ArchiveStatus {
  pending: number;
  oldest_at: number | null;
  external_retention_verified: boolean;
}

export const executionControlApi = {
  get: () => request<ControlState>("/security/control"),
  archive: () => request<ArchiveStatus>("/security/control/audit-status"),
  transition: (frozen: boolean, epoch: number, reason: string) =>
    request<ControlState>(
      `/security/control/${frozen ? "freeze" : "unfreeze"}`,
      {
        method: "POST",
        body: JSON.stringify({ expected_epoch: epoch, reason }),
      },
    ),
};
