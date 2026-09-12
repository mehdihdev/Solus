# SOLUSDEV-251 migration preflight — SOLUSDEV-260 Phase 0

Date: 2026-09-10. Scope: the user's newly authorized **empty-start** 260 database,
not the historical database described in the original request.

Database `solus` on `127.0.0.1:5432`, PostgreSQL 16.14, session-owned container
`solusdev-260-db`, selected volume `solus_pgdata`. Pre-migration custom snapshot:
`/tmp/solus260-snapshots/phase0-before-migration.dump` (pg_restore listing validated).
Before migration there were no application tables. After migration the single
Alembic head/current is `a25100000001`. No data backfill has been run.

## Row inventory

| Class                                          |     Count | Classification            |
| ---------------------------------------------- | --------: | ------------------------- |
| Projects                                       |         0 | Empty                     |
| Graph entities                                 |         0 | Empty                     |
| Graph edges                                    |         0 | Empty                     |
| Solus entries, including historical            |         0 | Empty                     |
| Legacy robot configs                           |         0 | No data to classify       |
| Nested part configs                            |         0 | No data to classify       |
| Firmware-bearing robots                        |         0 | No data to classify       |
| Local-path source references                   |         0 | No data to classify       |
| Deleted robots                                 |         0 | No data to classify       |
| Duplicate/conflicting config copies            |         0 | No data to classify       |
| Valid / convertible / needs-manual config rows | 0 / 0 / 0 | Vacuous on empty data     |
| Account connections                            |         0 | No integrations connected |

Counts were read directly from this database after the schema migration. A
synthetic service-level config-loss reproduction used one transaction and rolled
back completely; graph counts remained 0 before and after it. Pytest used only
separate checkout-specific test databases. Nothing was copied from another volume.

Deletion proposal: empty. No cleanup or destructive graph operation was performed.
No real arms, Onshape documents, repositories, or user-authored .solus entries
were present to inventory or prove retained. A clean empty database does not prove
legacy migration correctness.

## Refresh after the user's successful login

The user subsequently created `My first robot`. A fresh database inventory and
workspace UI show **1 project, 6 graph entities, and 5 relations**. All six are
legitimate manual project nodes: `.solus` plus Hardware configs, Project details,
Error logging, Documentation, and Code environment sections. They were created at
2026-09-11 00:27:37 UTC and are protected user data, not cleanup candidates.
`solus_entries` and `account_connections` still have zero rows. All configuration
classes in the initial table remain zero; only project/graph counts changed.
Deletion list remains empty.

## Phase 2 prerequisites

Build the required legacy fixture dataset covering nested, duplicate, conflicting,
firmware-bearing, local-path, and deleted-owner records. Prove conversion and
constraints on real PostgreSQL with those fixtures before applying the data
revision. Re-inventory the dev database immediately before that application and
take a new pg_dump snapshot. Any content added after this report requires fresh
classification; this zero-row result must not be reused as a future preflight.

Both `uq_solus_config_subject_live` and `ck_solus_config_subject` are absent in
PostgreSQL after `a25100000001`, confirming the schema gap. No constraint was
created manually. Historical-data migration and retention remain unverified unless
the user later supplies an authorized copy of the original data.

## Phase 0b refresh

After continuation approval, a fresh snapshot was validated at
`/tmp/solus260-snapshots/phase0b-before-cleanup.dump` (SHA-256 recorded in
`PHASE0B_SOLUSDEV-260.md`). The live database still contains 1 project, 6 legitimate
manual `.solus` nodes, 5 relations and no CONFIG entries, suggestions or integration
connections. Live edge integrity reports zero dangling/cross-project edges.
The approved deletion list remains empty; no graph mutation was necessary.
All legacy configuration classes remain 0 valid / 0 convertible / 0 needs-manual.
Phase 2 must still prove migration behavior using PostgreSQL fixtures and take a
new snapshot immediately before applying its revisions.
