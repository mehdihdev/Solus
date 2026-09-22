# Hosted add-on in account connect — SOLUSDEV-261

Extends Home and sources-connect-wizard under the approved ADR-035 account grant.
The existing registry-hosted notice is shown before authorization. After account
OAuth exchange, the link stage automatically checks stored add-on readiness. A ready
grant skips redundant OAuth; otherwise start the hosted OAuth leg through the same
desktop bridge. No separate Enable click is required following a successful connect.
Vendor consent is still the user's action, never simulated as automatic approval.

Capability success adds the hosted enabled note. Cancellation or vendor refusal
preserves the connected account and reports incomplete hosted setup honestly.
Home connected account rows show authoritative hosted status and a recovery action;
no project needs to exist. Recovery opens the same disclosed hosted flow. For a
subscription/admin requirement show the registry link and automatically recheck
capability on return while the flow remains open (bounded attempts; cancel/sign-out
stops it). Never infer subscription from a return URL. Existing project-source
recovery routes remain supported, with account owner required for account grants.
