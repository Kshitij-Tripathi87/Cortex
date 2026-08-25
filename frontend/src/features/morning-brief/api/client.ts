import type { components } from "@/types/api";
import { api } from "@/lib/api";

export type SupplierFailureRequest = components["schemas"]["SupplierFailureRequest"];
export type DecisionBrief = components["schemas"]["DecisionBriefResponse"];
export type BusinessImpact = components["schemas"]["BusinessImpactBlock"];
export type Confidence = components["schemas"]["ConfidenceBlock"];
export type Recommendation = components["schemas"]["RecommendationBlock"];

export function createSupplierFailureBrief(request: SupplierFailureRequest): Promise<DecisionBrief> {
  return api.post<DecisionBrief>("/mvp/briefs/supplier-failure", request);
}
