// Fields the backend's environment-plan schema has (verify_blocked, approval) that the shared TS types do not list yet.
import type { EnvironmentPlan, Relation } from "@contracts";

export interface BlockedPath { from_host: string; to_host: string; port?: number; protocol?: string; reason?: string }
export interface PlanApproval { approved: boolean; approved_by?: string; approved_at?: string; connections_digest?: string; note?: string }
export type PlanX = EnvironmentPlan & { verify_blocked?: BlockedPath[]; approval?: PlanApproval };

/** A dependency relation only opens a host-to-host path in the topology once an analyst confirmed it. */
export type RelationX = Relation & { confirmed?: boolean };

export const planApproval = (plan: EnvironmentPlan | undefined | null): PlanApproval | undefined => (plan as PlanX | undefined | null)?.approval;
export const isPlanApproved = (plan: EnvironmentPlan | undefined | null): boolean => planApproval(plan)?.approved === true;
