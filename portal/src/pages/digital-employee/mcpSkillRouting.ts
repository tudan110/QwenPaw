// These are the bundled skills that have an existing script implementation.
// Keys identify Drivers, not their editable display names.
const SCRIPT_SKILLS: Readonly<Record<string, readonly string[]>> = {
  alarm: ["real-alarm", "alarm-analyst"],
  "cmdb-query": ["zgops-cmdb", "inspection-analyst", "alarm-analyst"],
  inspection: ["inspection-analyst", "alarm-analyst"],
  resource: ["resource-insight-query", "monitoring-overview-query"],
  order: ["order-workflow"],
  "web-check-app": ["web-availability-monitor"],
};

export function getMcpSkillRoutingInfo(key: string, enabled: boolean) {
  const skills = Object.prototype.hasOwnProperty.call(SCRIPT_SKILLS, key)
    ? SCRIPT_SKILLS[key]
    : undefined;
  if (!skills) return undefined;
  return {
    skills,
    description: enabled
      ? "关联技能已安装并启用时，对应能力在 MCP 就绪后优先使用 MCP；停用后直接使用已有脚本。"
      : "关联技能已安装并启用时，对应能力直接使用已有脚本，不先尝试 MCP；仍需脚本依赖、凭据和授权。",
  };
}
