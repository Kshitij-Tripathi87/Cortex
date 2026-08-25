import { NexusScenario } from "./nexus-types";

export const supplierDelayScenario: NexusScenario = {
  id: "supplier-delay-001",
  label: "Supplier delay",
  description:
    "A delayed component begins affecting Plant 2 and downstream distribution.",
  metrics: {
    exposure: "$4.85M",
    timeToImpact: "36h",
    ordersAtRisk: 18,
    validatedOptions: 3,
  },
  nodes: [
    {
      id: "supplier-a",
      label: "SUPPLIER A",
      type: "supplier",
      subtitle: "On time",
      x: 100,
      y: 130,
      status: "normal",
      metadata: { location: "Shenzhen, CN", leadTime: "14 days", capacity: "500 units/day" },
    },
    {
      id: "supplier-x",
      label: "SUPPLIER X",
      type: "supplier",
      subtitle: "Delay risk",
      x: 100,
      y: 300,
      status: "risk",
      metadata: { location: "Taipei, TW", leadTime: "21 days", capacity: "300 units/day" },
    },
    {
      id: "plant-2",
      label: "PLANT 2",
      type: "plant",
      subtitle: "Operational",
      x: 380,
      y: 300,
      status: "at-risk",
      metadata: { location: "Austin, US", leadTime: "3 days", capacity: "1000 units/day" },
    },
    {
      id: "port-la",
      label: "PORT OF LOS ANGELES",
      type: "port",
      subtitle: "Risk propagated",
      x: 620,
      y: 220,
      status: "risk",
      metadata: { location: "Los Angeles, US", leadTime: "2 days", capacity: "5000 TEU/day" },
    },
    {
      id: "dc-west",
      label: "DC WEST",
      type: "warehouse",
      subtitle: "At risk",
      x: 850,
      y: 220,
      status: "at-risk",
      metadata: { location: "Phoenix, US", leadTime: "1 day", capacity: "20000 units/day" },
    },
    {
      id: "customer-1",
      label: "CUSTOMER 1",
      type: "customer",
      subtitle: "At risk",
      x: 1080,
      y: 180,
      status: "risk",
      metadata: { location: "San Francisco, US", leadTime: "0 days", capacity: "N/A" },
    },
  ],
  edges: [
    {
      id: "supplier-x-plant-2",
      source: "supplier-x",
      target: "plant-2",
      status: "risk",
      animated: true,
    },
    {
      id: "plant-2-port-la",
      source: "plant-2",
      target: "port-la",
      status: "risk",
      animated: true,
    },
    {
      id: "port-la-dc-west",
      source: "port-la",
      target: "dc-west",
      status: "risk",
      animated: true,
    },
    {
      id: "dc-west-customer-1",
      source: "dc-west",
      target: "customer-1",
      status: "risk",
      animated: true,
    },
  ],
};

export const validatedMitigationScenario: NexusScenario = {
  ...supplierDelayScenario,
  id: "supplier-delay-001-validated",
  label: "Supplier delay — Validated",
  description:
    "Alternative supplier qualified. Mitigation path validated and active.",
  nodes: supplierDelayScenario.nodes.map((node) => {
    if (node.id === "supplier-x") {
      return { ...node, status: "blocked" as const, subtitle: "Blocked" };
    }
    if (node.id === "supplier-a") {
      return { ...node, status: "validated" as const, subtitle: "Validated alt." };
    }
    if (node.id === "plant-2") {
      return { ...node, status: "validated" as const, subtitle: "Secured" };
    }
    if (["port-la", "dc-west", "customer-1"].includes(node.id)) {
      return { ...node, status: "validated" as const, subtitle: "Protected" };
    }
    return node;
  }),
  edges: supplierDelayScenario.edges.map((edge) => {
    if (edge.source === "supplier-x" || edge.target === "supplier-x") {
      return { ...edge, status: "blocked" as const, animated: false };
    }
    if (edge.source === "supplier-a" || edge.target === "supplier-a") {
      return { ...edge, status: "validated" as const, animated: true };
    }
    return { ...edge, status: "validated" as const, animated: true };
  }),
  metrics: {
    exposure: "$0.42M",
    timeToImpact: "Resolved",
    ordersAtRisk: 0,
    validatedOptions: 3,
  },
};