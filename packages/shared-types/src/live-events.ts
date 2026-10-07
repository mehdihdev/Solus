import type { CompleteKeysOf } from "./json";

// SOLUSDEV-312 (ADR-037) — live change-hint frames.
// Wire twin of packages/contracts/python/solus_contracts/live_events.py.
//
// Two SSE streams carry these frames:
//   GET /api/v1/projects/{project_id}/events — the project channel
//   GET /api/v1/users/me/events              — the user channel + every team channel
//
// Every frame is an invalidation HINT (ids, counts, versions). It never carries
// names, emails, invite tokens or CAD data: answer it by refetching through the
// REST route you already use. The SSE `event:` name is the frame's `type`; the
// `ready` event carries no `type` field. Wire shapes are snake_case.
//
// See docs/contracts/live-events.md.

export const KEEPALIVE_SECONDS = 25;
export const REVERIFY_SECONDS = 30;

export const JOB_STATUSES = [
  "queued",
  "running",
  "succeeded",
  "failed",
  "cancelled",
] as const;
export type JobStatusName = (typeof JOB_STATUSES)[number];

// ------------------------------------------------------------ project channel

export interface GraphChangeCounts {
  entities_created: number;
  entities_updated: number;
  entities_deleted: number;
  relations_created: number;
  relations_deleted: number;
}

export interface GraphChanged {
  type: "graph.changed";
  project_id: string;
  source_id: string | null;
  sync_id: string | null;
  counts: GraphChangeCounts;
  at: string;
}

export interface HardwareDevicesChanged {
  type: "hardware.devices_changed";
  project_id: string;
  devices: Record<string, unknown>[];
  at: string;
}

export interface LayoutChanged {
  type: "layout.changed";
  project_id: string;
  version: number;
  at: string;
}

export interface SourcesChanged {
  type: "sources.changed";
  project_id: string;
  source_id: string | null;
  at: string;
}

export interface ProjectUpdated {
  type: "project.updated";
  project_id: string;
  team_id: string;
  at: string;
}

export interface JobUpdated {
  type: "job.updated";
  project_id: string;
  job_id: string;
  status: JobStatusName;
  at: string;
}

export interface ProjectStreamReady {
  project_id: string;
}

// -------------------------------------------------------- team + user channels

export interface TeamUpdated {
  type: "team.updated";
  team_id: string;
  at: string;
}

export interface TeamMembersChanged {
  type: "team.members_changed";
  team_id: string;
  at: string;
}

/** Only admins can refetch the invite list; members may ignore this hint. */
export interface TeamInvitesChanged {
  type: "team.invites_changed";
  team_id: string;
  at: string;
}

export interface TeamProjectsChanged {
  type: "team.projects_changed";
  team_id: string;
  project_id: string | null;
  at: string;
}

export interface TeamActivity {
  type: "team.activity";
  team_id: string;
  project_id: string | null;
  actor_id: string | null;
  at: string;
}

export interface NotificationCreated {
  type: "notification.created";
  user_id: string;
  at: string;
}

export interface MembershipChanged {
  type: "membership.changed";
  user_id: string;
  team_id: string | null;
  project_id: string | null;
  at: string;
}

/** At least one of the three ids is non-null. */
export interface AccessRevoked {
  type: "access.revoked";
  user_id: string | null;
  team_id: string | null;
  project_id: string | null;
  at: string;
}

export interface AccountStreamReady {
  user_id: string;
  team_ids: string[];
}

export type ProjectFrame =
  | GraphChanged
  | HardwareDevicesChanged
  | LayoutChanged
  | SourcesChanged
  | ProjectUpdated
  | JobUpdated
  | AccessRevoked;

export type AccountFrame =
  | TeamUpdated
  | TeamMembersChanged
  | TeamInvitesChanged
  | TeamProjectsChanged
  | TeamActivity
  | NotificationCreated
  | MembershipChanged
  | AccessRevoked;

export const PROJECT_EVENT_TYPES = [
  "graph.changed",
  "hardware.devices_changed",
  "layout.changed",
  "sources.changed",
  "project.updated",
  "job.updated",
  "access.revoked",
] as const satisfies readonly ProjectFrame["type"][];

export const ACCOUNT_EVENT_TYPES = [
  "team.updated",
  "team.members_changed",
  "team.invites_changed",
  "team.projects_changed",
  "team.activity",
  "notification.created",
  "membership.changed",
  "access.revoked",
] as const satisfies readonly AccountFrame["type"][];

// ------------------------------------------------------- drift field lists

const GCC = [
  "entities_created",
  "entities_updated",
  "entities_deleted",
  "relations_created",
  "relations_deleted",
] as const;
export const GRAPH_CHANGE_COUNTS_FIELDS: CompleteKeysOf<
  GraphChangeCounts,
  typeof GCC
> = GCC;
const GC = [
  "type",
  "project_id",
  "source_id",
  "sync_id",
  "counts",
  "at",
] as const;
export const GRAPH_CHANGED_FIELDS: CompleteKeysOf<GraphChanged, typeof GC> = GC;
const HDC = ["type", "project_id", "devices", "at"] as const;
export const HARDWARE_DEVICES_CHANGED_FIELDS: CompleteKeysOf<
  HardwareDevicesChanged,
  typeof HDC
> = HDC;
const LC = ["type", "project_id", "version", "at"] as const;
export const LAYOUT_CHANGED_FIELDS: CompleteKeysOf<LayoutChanged, typeof LC> =
  LC;
const SC = ["type", "project_id", "source_id", "at"] as const;
export const SOURCES_CHANGED_FIELDS: CompleteKeysOf<SourcesChanged, typeof SC> =
  SC;
const PU = ["type", "project_id", "team_id", "at"] as const;
export const PROJECT_UPDATED_FIELDS: CompleteKeysOf<ProjectUpdated, typeof PU> =
  PU;
const JU = ["type", "project_id", "job_id", "status", "at"] as const;
export const JOB_UPDATED_FIELDS: CompleteKeysOf<JobUpdated, typeof JU> = JU;
const PSR = ["project_id"] as const;
export const PROJECT_STREAM_READY_FIELDS: CompleteKeysOf<
  ProjectStreamReady,
  typeof PSR
> = PSR;
const TU = ["type", "team_id", "at"] as const;
export const TEAM_UPDATED_FIELDS: CompleteKeysOf<TeamUpdated, typeof TU> = TU;
const TMC = ["type", "team_id", "at"] as const;
export const TEAM_MEMBERS_CHANGED_FIELDS: CompleteKeysOf<
  TeamMembersChanged,
  typeof TMC
> = TMC;
const TIC = ["type", "team_id", "at"] as const;
export const TEAM_INVITES_CHANGED_FIELDS: CompleteKeysOf<
  TeamInvitesChanged,
  typeof TIC
> = TIC;
const TPC = ["type", "team_id", "project_id", "at"] as const;
export const TEAM_PROJECTS_CHANGED_FIELDS: CompleteKeysOf<
  TeamProjectsChanged,
  typeof TPC
> = TPC;
const TA = ["type", "team_id", "project_id", "actor_id", "at"] as const;
export const TEAM_ACTIVITY_FIELDS: CompleteKeysOf<TeamActivity, typeof TA> = TA;
const NC = ["type", "user_id", "at"] as const;
export const NOTIFICATION_CREATED_FIELDS: CompleteKeysOf<
  NotificationCreated,
  typeof NC
> = NC;
const MC = ["type", "user_id", "team_id", "project_id", "at"] as const;
export const MEMBERSHIP_CHANGED_FIELDS: CompleteKeysOf<
  MembershipChanged,
  typeof MC
> = MC;
const AR = ["type", "user_id", "team_id", "project_id", "at"] as const;
export const ACCESS_REVOKED_FIELDS: CompleteKeysOf<AccessRevoked, typeof AR> =
  AR;
const ASR = ["user_id", "team_ids"] as const;
export const ACCOUNT_STREAM_READY_FIELDS: CompleteKeysOf<
  AccountStreamReady,
  typeof ASR
> = ASR;
