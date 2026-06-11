// Types shared between the desktop/web frontends and the backend.
// Domain types (Entity, Relation, etc.) will be generated from packages/contracts later.
export interface ApiError {
  code: string;
  message: string;
}
