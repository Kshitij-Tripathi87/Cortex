export type Role = "cfo" | "coo" | "logistics" | "procurement";

export interface RoleConfig {
  id: Role;
  label: string;
  subtitle: string;
  primaryMetric: "financial" | "operational" | "logistics" | "sourcing";
  ordering: ("critical" | "financial" | "operational" | "timeline" | "recommendations" | "evidence" | "trust")[];
}

export const ROLES: RoleConfig[] = [
  {
    id: "cfo",
    label: "CFO",
    subtitle: "Financial exposure view",
    primaryMetric: "financial",
    ordering: ["critical", "financial", "operational", "recommendations", "timeline", "evidence", "trust"],
  },
  {
    id: "coo",
    label: "COO",
    subtitle: "Operational risk view",
    primaryMetric: "operational",
    ordering: ["critical", "operational", "timeline", "financial", "recommendations", "evidence", "trust"],
  },
  {
    id: "logistics",
    label: "Logistics",
    subtitle: "Supply chain ops view",
    primaryMetric: "logistics",
    ordering: ["critical", "timeline", "operational", "recommendations", "financial", "evidence", "trust"],
  },
  {
    id: "procurement",
    label: "Procurement",
    subtitle: "Sourcing & mitigation view",
    primaryMetric: "sourcing",
    ordering: ["critical", "recommendations", "evidence", "operational", "timeline", "financial", "trust"],
  },
];

export function getRole(id: Role): RoleConfig {
  return ROLES.find((r) => r.id === id) ?? ROLES[0];
}
