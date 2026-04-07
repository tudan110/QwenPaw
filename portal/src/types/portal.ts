import type { CSSProperties } from "react";

export interface PortalAgent {
  id: string;
  name: string;
  type: string;
  status: string;
  color: string;
  icon: string;
  description: string;
  skills: string[];
  execCount: number;
  successRate: number;
  avgDuration: string;
  lastRunTime: string;
  employeeId: string;
}

export interface DigitalEmployee {
  id: string;
  name: string;
  desc: string;
  icon: string;
  tasks: number;
  success: string;
  status: string;
  urgent: boolean;
  gradient: string;
  capabilities: string[];
  quickCommands: string[];
  welcome: string;
}

export type OperationsBoardColumnId = "pending" | "running" | "completed" | "closed";
export type OperationsBoardTone = "blue" | "green" | "orange" | "red" | "purple";

export interface OperationsBoardTask {
  id: string;
  ownerEmployeeIds: DigitalEmployee["id"][];
  ownerLabel: string;
  ownerColor: string;
  title: string;
  description: string;
  label: string;
  tone: OperationsBoardTone;
  tagBg: string;
  tagColor: string;
  timeText: string;
  statusText?: string;
  progress?: number;
  score?: number;
}

export interface OperationsBoardColumn {
  id: OperationsBoardColumnId;
  title: string;
  items: OperationsBoardTask[];
}

export interface PortalStatSummary {
  total: number;
  active: number;
  tasksToday: number;
  efficiency: number;
}

export interface AlarmWorkorder {
  [key: string]: unknown;
  id?: string;
  workorderNo?: string;
  title?: string;
  deviceName?: string;
  manageIp?: string;
  locateName?: string;
  eventTime?: string;
}

export interface DigitalEmployeeAvatarProps {
  employee: DigitalEmployee | null | undefined;
  className?: string;
  style?: CSSProperties;
}
