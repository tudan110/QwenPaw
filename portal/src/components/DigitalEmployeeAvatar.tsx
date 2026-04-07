import "./digital-employee-avatar.css";
import type { CSSProperties } from "react";
import type { DigitalEmployeeAvatarProps } from "../types/portal";

export default function DigitalEmployeeAvatar({
  employee,
  className = "",
  style,
}: DigitalEmployeeAvatarProps) {
  if (!employee) {
    return null;
  }

  const avatarStyle = {
    "--de-avatar-gradient":
      employee.gradient || "linear-gradient(135deg, #3b82f6, #8b5cf6)",
    ...style,
  } as CSSProperties;

  return (
    <div
      className={`digital-employee-avatar ${className}`.trim()}
      style={avatarStyle}
    >
      <i className={`fas ${employee.icon}`} />
      {employee.status === "running" && !employee.urgent ? (
        <div className="de-avatar-animation de-avatar-running">
          <svg viewBox="0 0 24 24" fill="none">
            <circle cx="12" cy="5" r="3" fill="#fff" />
            <path d="M12 9v5" stroke="#fff" strokeWidth="2" strokeLinecap="round" />
            <path d="M8 17l4-3 4 3" stroke="#fff" strokeWidth="2" strokeLinecap="round" />
            <path
              d="M9 12h6"
              stroke="#FFD700"
              strokeWidth="2"
              strokeLinecap="round"
              transform="rotate(45, 12, 12)"
            />
            <rect
              x="14"
              y="10"
              width="3"
              height="8"
              rx="1"
              fill="#8B4513"
              transform="rotate(-30, 15, 14)"
            />
          </svg>
        </div>
      ) : null}
      {employee.urgent ? (
        <div className="de-avatar-animation de-avatar-urgent">
          <div className="de-avatar-urgent-ring" />
          <svg viewBox="0 0 24 24" fill="none">
            <circle cx="12" cy="12" r="8" fill="#EF4444" />
            <circle cx="12" cy="12" r="5" fill="#FCA5A5" />
            <circle cx="10" cy="10" r="2" fill="#fff" opacity="0.6" />
          </svg>
        </div>
      ) : null}
      {employee.status !== "running" && !employee.urgent ? (
        <div className="de-avatar-animation de-avatar-stopped">
          <span className="de-avatar-zzz">Z</span>
          <svg viewBox="0 0 24 24" fill="none">
            <rect x="5" y="10" width="14" height="8" rx="3" fill="#94A3B8" />
            <circle cx="8" cy="14" r="1.5" fill="#475569" />
            <circle cx="16" cy="14" r="1.5" fill="#475569" />
            <path d="M9 17h6" stroke="#475569" strokeWidth="1" strokeLinecap="round" />
            <rect x="9" y="6" width="6" height="4" rx="1" fill="#64748B" />
          </svg>
        </div>
      ) : null}
    </div>
  );
}
