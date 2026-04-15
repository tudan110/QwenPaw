import { requestPortalApi } from "./portalWorkorders";

export interface PortalEmployeeRuntimeStatus {
  employeeId: string;
  employeeName: string;
  available: boolean;
  status: "running" | "idle";
  urgent: boolean;
  stateLabel: string;
  workStatus: string;
  currentJob: string;
  hasConversation: boolean;
  totalChatCount: number;
  activeTaskCount: number;
  activeChatCount: number;
  alertCount: number;
  latestSessionTitle: string;
  updatedAt: string;
}

export interface PortalEmployeeStatusResponse {
  employees: PortalEmployeeRuntimeStatus[];
  updatedAt: string;
}

export async function getPortalEmployeeStatuses() {
  return requestPortalApi<PortalEmployeeStatusResponse>("/employee-status");
}
