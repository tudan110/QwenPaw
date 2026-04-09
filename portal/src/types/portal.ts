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
export type TaskViewStatus = "running" | "urgent" | "completed" | "pending";
export type TaskViewActionKind = "view" | "detail" | "confirm" | "approve" | "none";
export type TaskViewStatusVariant =
  | "running"
  | "urgent"
  | "completed"
  | "pending"
  | "auto-push"
  | "need-confirm"
  | "auto-exec";

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

export interface TaskViewItem {
  id: string;
  title: string;
  employeeId: DigitalEmployee["id"];
  employeeLabel?: string;
  source: string;
  status: TaskViewStatus;
  statusText: string;
  statusVariant?: TaskViewStatusVariant;
  priority: "P0" | "P1" | "P2" | "P3";
  scheduledAt: string;
  timeLabel: string;
  auto?: boolean;
  includeInDailyOverview?: boolean;
  actionKind: TaskViewActionKind;
  actionLabel?: string;
}

export interface PortalStatSummary {
  total: number;
  active: number;
  tasksToday: number;
  efficiency: number;
}

export interface OpsExpert {
  id: string;
  name: string;
  title: string;
  desc: string;
  tags: string[];
  skills: string[];
  avatar: string;
  bg: string;
  color: string;
  category: string;
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
