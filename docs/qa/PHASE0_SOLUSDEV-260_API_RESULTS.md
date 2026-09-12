# SOLUSDEV-260 Phase 0 — full API suite by file

Command: full `packages/api/tests` suite on the merged 251 tree, four workers,
explicit checkout-specific test database base `solus_test_436a6e18`. The five
new regression tests were added after collection and ran separately (4 failed,
1 passed); they are not included in these totals.

**4694 passed, 14 failed, 7 skipped, 8 warnings; 844.33 seconds.**

| File                                                               | Passed | Failed | Errors | Skipped |
| ------------------------------------------------------------------ | -----: | -----: | -----: | ------: |
| `packages/api/tests/bom/test_bundle_folder.py`                     |      2 |      0 |      0 |       0 |
| `packages/api/tests/bom/test_routes.py`                            |     16 |      0 |      0 |       0 |
| `packages/api/tests/bom/test_rows.py`                              |     40 |      0 |      0 |       0 |
| `packages/api/tests/contracts/test_action_gate.py`                 |     22 |      0 |      0 |       0 |
| `packages/api/tests/contracts/test_extension_manifest_contract.py` |     52 |      0 |      0 |       0 |
| `packages/api/tests/contracts/test_field_manifest.py`              |      1 |      0 |      0 |       0 |
| `packages/api/tests/contracts/test_impact.py`                      |     29 |      0 |      0 |       0 |
| `packages/api/tests/contracts/test_tool_knowledge.py`              |     81 |      0 |      0 |       0 |
| `packages/api/tests/corpus/test_corpus_c3_acceptance.py`           |      4 |      0 |      0 |       0 |
| `packages/api/tests/corpus/test_corpus_chunking.py`                |     14 |      0 |      0 |       0 |
| `packages/api/tests/corpus/test_corpus_context.py`                 |     10 |      0 |      0 |       0 |
| `packages/api/tests/corpus/test_corpus_contract.py`                |     85 |      0 |      0 |       0 |
| `packages/api/tests/corpus/test_corpus_domains.py`                 |      9 |      0 |      0 |       0 |
| `packages/api/tests/corpus/test_corpus_eval.py`                    |     10 |      0 |      0 |       0 |
| `packages/api/tests/corpus/test_corpus_eval_live.py`               |      0 |      0 |      0 |       1 |
| `packages/api/tests/corpus/test_corpus_ingest.py`                  |     12 |      0 |      0 |       0 |
| `packages/api/tests/corpus/test_corpus_licenses.py`                |      4 |      0 |      0 |       0 |
| `packages/api/tests/corpus/test_corpus_retrieval.py`               |     13 |      0 |      0 |       0 |
| `packages/api/tests/corpus/test_corpus_router.py`                  |      8 |      0 |      0 |       0 |
| `packages/api/tests/sourcing/test_sourcing_candidates.py`          |     12 |      0 |      0 |       0 |
| `packages/api/tests/sourcing/test_sourcing_routes.py`              |     17 |      0 |      0 |       0 |
| `packages/api/tests/sourcing/test_sourcing_rules.py`               |      6 |      0 |      0 |       0 |
| `packages/api/tests/sourcing/test_sourcing_torque.py`              |      5 |      0 |      0 |       0 |
| `packages/api/tests/test_access_modes.py`                          |     11 |      0 |      0 |       0 |
| `packages/api/tests/test_account_deletion.py`                      |      8 |      0 |      0 |       0 |
| `packages/api/tests/test_activity.py`                              |     12 |      0 |      0 |       0 |
| `packages/api/tests/test_allowlist.py`                             |     11 |      0 |      0 |       0 |
| `packages/api/tests/test_altium_connector.py`                      |     11 |      0 |      0 |       0 |
| `packages/api/tests/test_artifact_retention.py`                    |      5 |      0 |      0 |       0 |
| `packages/api/tests/test_artifact_store.py`                        |     25 |      0 |      0 |       0 |
| `packages/api/tests/test_artifact_upload.py`                       |     16 |      0 |      0 |       0 |
| `packages/api/tests/test_artifacts.py`                             |      3 |      0 |      0 |       0 |
| `packages/api/tests/test_attributes.py`                            |     10 |      0 |      0 |       0 |
| `packages/api/tests/test_bench_robot_provider.py`                  |      5 |      3 |      0 |       0 |
| `packages/api/tests/test_bench_router.py`                          |     23 |      0 |      0 |       0 |
| `packages/api/tests/test_billing_checkout.py`                      |     18 |      0 |      0 |       0 |
| `packages/api/tests/test_billing_webhook.py`                       |     30 |      0 |      0 |       0 |
| `packages/api/tests/test_bridge.py`                                |     18 |      0 |      0 |       0 |
| `packages/api/tests/test_bridge_allowlist_url.py`                  |      3 |      0 |      0 |       0 |
| `packages/api/tests/test_bridge_artifacts.py`                      |     12 |      0 |      0 |       0 |
| `packages/api/tests/test_bridge_change_frame.py`                   |     11 |      0 |      0 |       0 |
| `packages/api/tests/test_bridge_credentials.py`                    |     18 |      0 |      0 |       0 |
| `packages/api/tests/test_bridge_e2e.py`                            |      0 |      1 |      0 |       0 |
| `packages/api/tests/test_bridge_hello_cap.py`                      |      5 |      0 |      0 |       0 |
| `packages/api/tests/test_bridge_resync.py`                         |      3 |      0 |      0 |       0 |
| `packages/api/tests/test_bridge_status.py`                         |      5 |      0 |      0 |       0 |
| `packages/api/tests/test_bridge_tool.py`                           |      7 |      0 |      0 |       0 |
| `packages/api/tests/test_buffer.py`                                |     13 |      0 |      0 |       0 |
| `packages/api/tests/test_builtin.py`                               |     10 |      0 |      0 |       0 |
| `packages/api/tests/test_checker_graphs.py`                        |      3 |      0 |      0 |       0 |
| `packages/api/tests/test_choice.py`                                |      3 |      0 |      0 |       0 |
| `packages/api/tests/test_code_environment.py`                      |      8 |      0 |      0 |       0 |
| `packages/api/tests/test_code_host.py`                             |      5 |      0 |      0 |       0 |
| `packages/api/tests/test_codec.py`                                 |     30 |      0 |      0 |       0 |
| `packages/api/tests/test_complexity.py`                            |     62 |      0 |      0 |       0 |
| `packages/api/tests/test_complexity_labels.py`                     |      3 |      0 |      0 |       0 |
| `packages/api/tests/test_config.py`                                |     19 |      0 |      0 |       0 |
| `packages/api/tests/test_confirmations.py`                         |     45 |      0 |      0 |       0 |
| `packages/api/tests/test_connect_integration.py`                   |     15 |      0 |      0 |       0 |
| `packages/api/tests/test_connection_adoption.py`                   |     30 |      0 |      0 |       0 |
| `packages/api/tests/test_connection_health.py`                     |      9 |      0 |      0 |       0 |
| `packages/api/tests/test_connections.py`                           |     24 |      0 |      0 |       0 |
| `packages/api/tests/test_connector_conformance.py`                 |      8 |      0 |      0 |       0 |
| `packages/api/tests/test_connector_quota.py`                       |     18 |      0 |      0 |       0 |
| `packages/api/tests/test_consequences.py`                          |     21 |      0 |      0 |       0 |
| `packages/api/tests/test_context.py`                               |     40 |      0 |      0 |       0 |
| `packages/api/tests/test_contracts.py`                             |      7 |      0 |      0 |       0 |
| `packages/api/tests/test_contracts_package.py`                     |      6 |      0 |      0 |       0 |
| `packages/api/tests/test_conversation.py`                          |      5 |      0 |      0 |       0 |
| `packages/api/tests/test_core.py`                                  |     23 |      0 |      0 |       0 |
| `packages/api/tests/test_cost.py`                                  |     14 |      0 |      0 |       0 |
| `packages/api/tests/test_credits.py`                               |     12 |      0 |      0 |       0 |
| `packages/api/tests/test_db.py`                                    |      2 |      0 |      0 |       0 |
| `packages/api/tests/test_deps.py`                                  |      5 |      0 |      0 |       0 |
| `packages/api/tests/test_eda.py`                                   |     25 |      0 |      0 |       0 |
| `packages/api/tests/test_embeddings.py`                            |     14 |      0 |      0 |       0 |
| `packages/api/tests/test_engine.py`                                |     13 |      0 |      0 |       0 |
| `packages/api/tests/test_entities.py`                              |     14 |      0 |      0 |       0 |
| `packages/api/tests/test_entities_prefix.py`                       |      8 |      0 |      0 |       0 |
| `packages/api/tests/test_entities_search.py`                       |      6 |      0 |      0 |       0 |
| `packages/api/tests/test_enums.py`                                 |      3 |      0 |      0 |       0 |
| `packages/api/tests/test_environment.py`                           |      8 |      0 |      0 |       0 |
| `packages/api/tests/test_errors.py`                                |      5 |      0 |      0 |       0 |
| `packages/api/tests/test_escalation.py`                            |     22 |      0 |      0 |       0 |
| `packages/api/tests/test_events.py`                                |      2 |      0 |      0 |       0 |
| `packages/api/tests/test_events_ingest.py`                         |     19 |      0 |      0 |       0 |
| `packages/api/tests/test_exec.py`                                  |     11 |      0 |      0 |       0 |
| `packages/api/tests/test_export_acquisition.py`                    |     10 |      0 |      0 |       0 |
| `packages/api/tests/test_export_common.py`                         |      9 |      0 |      0 |       0 |
| `packages/api/tests/test_extension_bundle.py`                      |     63 |      0 |      0 |       0 |
| `packages/api/tests/test_extension_bundle_download.py`             |     22 |      0 |      0 |       0 |
| `packages/api/tests/test_extension_bundle_store.py`                |      6 |      0 |      0 |       0 |
| `packages/api/tests/test_extension_catalog.py`                     |     39 |      0 |      0 |       0 |
| `packages/api/tests/test_extension_checks.py`                      |     39 |      0 |      0 |       0 |
| `packages/api/tests/test_extension_credit_attribution.py`          |     33 |      0 |      0 |       0 |
| `packages/api/tests/test_extension_install_isolation.py`           |     32 |      0 |      0 |       0 |
| `packages/api/tests/test_extension_installs.py`                    |     35 |      0 |      0 |       0 |
| `packages/api/tests/test_extension_manifest.py`                    |      8 |      0 |      0 |       0 |
| `packages/api/tests/test_extension_permissions.py`                 |     28 |      0 |      0 |       0 |
| `packages/api/tests/test_extension_publish.py`                     |     41 |      0 |      0 |       0 |
| `packages/api/tests/test_extension_ratelimit.py`                   |      4 |      0 |      0 |       0 |
| `packages/api/tests/test_extension_red_team.py`                    |      5 |      0 |      0 |       0 |
| `packages/api/tests/test_extension_registry_models.py`             |     30 |      0 |      0 |       0 |
| `packages/api/tests/test_extension_review_job.py`                  |     31 |      0 |      0 |       0 |
| `packages/api/tests/test_extension_review_status.py`               |     28 |      0 |      0 |       0 |
| `packages/api/tests/test_extension_router_wiring.py`               |      5 |      0 |      0 |       0 |
| `packages/api/tests/test_extension_settings_values.py`             |     30 |      0 |      0 |       0 |
| `packages/api/tests/test_extension_svg.py`                         |     45 |      0 |      0 |       0 |
| `packages/api/tests/test_extension_team_policy.py`                 |     45 |      0 |      0 |       0 |
| `packages/api/tests/test_featurescript_preview.py`                 |     14 |      0 |      0 |       0 |
| `packages/api/tests/test_feeds.py`                                 |     11 |      0 |      0 |       0 |
| `packages/api/tests/test_fingerprint_contract.py`                  |      9 |      0 |      0 |       0 |
| `packages/api/tests/test_fingerprint_eval.py`                      |     60 |      0 |      0 |       0 |
| `packages/api/tests/test_fingerprint_hardware_modalities.py`       |      5 |      0 |      0 |       0 |
| `packages/api/tests/test_fingerprint_labels.py`                    |     11 |      0 |      0 |       0 |
| `packages/api/tests/test_fixture_bundle_folder.py`                 |      2 |      0 |      0 |       0 |
| `packages/api/tests/test_frames.py`                                |     11 |      0 |      0 |       0 |
| `packages/api/tests/test_gates.py`                                 |      9 |      0 |      0 |       0 |
| `packages/api/tests/test_gateway.py`                               |     33 |      0 |      0 |       0 |
| `packages/api/tests/test_get_entity.py`                            |      8 |      0 |      0 |       0 |
| `packages/api/tests/test_github_connector.py`                      |     30 |      0 |      0 |       0 |
| `packages/api/tests/test_gitlab_connector.py`                      |     18 |      0 |      0 |       0 |
| `packages/api/tests/test_graph_live.py`                            |      1 |      0 |      0 |       0 |
| `packages/api/tests/test_hardware_attach.py`                       |      9 |      0 |      0 |       0 |
| `packages/api/tests/test_hardware_config.py`                       |     28 |      0 |      0 |       0 |
| `packages/api/tests/test_hardware_config_migration.py`             |      5 |      0 |      0 |       0 |
| `packages/api/tests/test_hardware_detect.py`                       |     18 |      4 |      0 |       0 |
| `packages/api/tests/test_hardware_operations.py`                   |      5 |      0 |      0 |       0 |
| `packages/api/tests/test_hardware_ownership.py`                    |      9 |      0 |      0 |       0 |
| `packages/api/tests/test_hardware_router.py`                       |     28 |      3 |      0 |       0 |
| `packages/api/tests/test_hosted_mcp_spec.py`                       |      9 |      0 |      0 |       0 |
| `packages/api/tests/test_hosted_oauth.py`                          |     17 |      0 |      0 |       0 |
| `packages/api/tests/test_hosted_routes.py`                         |     19 |      0 |      0 |       0 |
| `packages/api/tests/test_hosted_tool_build.py`                     |     13 |      0 |      0 |       0 |
| `packages/api/tests/test_httpcache.py`                             |      5 |      0 |      0 |       0 |
| `packages/api/tests/test_ingest.py`                                |     28 |      0 |      0 |       0 |
| `packages/api/tests/test_injection_corpus.py`                      |     11 |      0 |      0 |       0 |
| `packages/api/tests/test_integration_cache.py`                     |     11 |      0 |      0 |       0 |
| `packages/api/tests/test_integration_setup.py`                     |      4 |      0 |      0 |       0 |
| `packages/api/tests/test_integrations.py`                          |     17 |      0 |      0 |       0 |
| `packages/api/tests/test_integrations_stack.py`                    |      1 |      0 |      0 |       0 |
| `packages/api/tests/test_interface.py`                             |      9 |      0 |      0 |       0 |
| `packages/api/tests/test_invites.py`                               |     13 |      0 |      0 |       0 |
| `packages/api/tests/test_jobs.py`                                  |      7 |      0 |      0 |       0 |
| `packages/api/tests/test_kicad_acquisition_fallback.py`            |      6 |      0 |      0 |       0 |
| `packages/api/tests/test_kicad_connector.py`                       |     18 |      0 |      0 |       0 |
| `packages/api/tests/test_kicad_formats.py`                         |     22 |      0 |      0 |       0 |
| `packages/api/tests/test_kicad_ingest_e2e.py`                      |      7 |      0 |      0 |       0 |
| `packages/api/tests/test_kicad_netlist.py`                         |     21 |      0 |      0 |       0 |
| `packages/api/tests/test_kicad_netlist_sexpr.py`                   |     17 |      0 |      0 |       0 |
| `packages/api/tests/test_kicad_pcb.py`                             |     26 |      0 |      0 |       0 |
| `packages/api/tests/test_kicad_reconcile.py`                       |     31 |      0 |      0 |       0 |
| `packages/api/tests/test_kicad_sexpr.py`                           |     38 |      0 |      0 |       0 |
| `packages/api/tests/test_knowledge.py`                             |      6 |      0 |      0 |       0 |
| `packages/api/tests/test_library.py`                               |     24 |      0 |      0 |       0 |
| `packages/api/tests/test_library_router.py`                        |     18 |      1 |      0 |       0 |
| `packages/api/tests/test_limits.py`                                |      9 |      0 |      0 |       0 |
| `packages/api/tests/test_linker.py`                                |     25 |      0 |      0 |       0 |
| `packages/api/tests/test_links.py`                                 |     21 |      0 |      0 |       0 |
| `packages/api/tests/test_live_connection.py`                       |     11 |      0 |      0 |       0 |
| `packages/api/tests/test_live_events.py`                           |     17 |      0 |      0 |       0 |
| `packages/api/tests/test_live_kicad_write.py`                      |      0 |      0 |      0 |       1 |
| `packages/api/tests/test_live_onshape_write.py`                    |      0 |      0 |      0 |       1 |
| `packages/api/tests/test_live_smoke.py`                            |      0 |      0 |      0 |       3 |
| `packages/api/tests/test_local_acquire.py`                         |     11 |      0 |      0 |       0 |
| `packages/api/tests/test_local_folder.py`                          |     40 |      0 |      0 |       0 |
| `packages/api/tests/test_local_folder_routes.py`                   |     15 |      0 |      0 |       0 |
| `packages/api/tests/test_local_links.py`                           |      7 |      0 |      0 |       0 |
| `packages/api/tests/test_main.py`                                  |      3 |      0 |      0 |       0 |
| `packages/api/tests/test_matcher.py`                               |     45 |      0 |      0 |       0 |
| `packages/api/tests/test_mcp_acquire.py`                           |     18 |      0 |      0 |       0 |
| `packages/api/tests/test_mcp_acquire_artifact.py`                  |     19 |      0 |      0 |       0 |
| `packages/api/tests/test_mcp_license.py`                           |     20 |      0 |      0 |       0 |
| `packages/api/tests/test_mcp_tool.py`                              |     28 |      0 |      0 |       0 |
| `packages/api/tests/test_mechanical.py`                            |     24 |      0 |      0 |       0 |
| `packages/api/tests/test_members.py`                               |      6 |      0 |      0 |       0 |
| `packages/api/tests/test_meta.py`                                  |      6 |      0 |      0 |       0 |
| `packages/api/tests/test_models.py`                                |      9 |      0 |      0 |       0 |
| `packages/api/tests/test_modes.py`                                 |      7 |      0 |      0 |       0 |
| `packages/api/tests/test_neighborhood.py`                          |     27 |      0 |      0 |       0 |
| `packages/api/tests/test_never_raises_groups.py`                   |      7 |      0 |      0 |       0 |
| `packages/api/tests/test_no_hardcoded_models.py`                   |      2 |      0 |      0 |       0 |
| `packages/api/tests/test_normalize.py`                             |     43 |      0 |      0 |       0 |
| `packages/api/tests/test_notifications.py`                         |      6 |      0 |      0 |       0 |
| `packages/api/tests/test_oauth_refresh.py`                         |     11 |      0 |      0 |       0 |
| `packages/api/tests/test_onshape_call_budget.py`                   |     13 |      0 |      0 |       0 |
| `packages/api/tests/test_onshape_connector.py`                     |     78 |      0 |      0 |       0 |
| `packages/api/tests/test_onshape_ops.py`                           |     25 |      0 |      0 |       0 |
| `packages/api/tests/test_onshape_refs.py`                          |     17 |      0 |      0 |       0 |
| `packages/api/tests/test_onshape_session_cost.py`                  |      1 |      0 |      0 |       0 |
| `packages/api/tests/test_onshape_tools.py`                         |     29 |      0 |      0 |       0 |
| `packages/api/tests/test_onshape_writes.py`                        |     18 |      0 |      0 |       0 |
| `packages/api/tests/test_orchestration.py`                         |     13 |      0 |      0 |       0 |
| `packages/api/tests/test_packet.py`                                |     17 |      0 |      0 |       0 |
| `packages/api/tests/test_pagination.py`                            |      3 |      0 |      0 |       0 |
| `packages/api/tests/test_panel.py`                                 |     33 |      0 |      0 |       0 |
| `packages/api/tests/test_panel_assets.py`                          |      7 |      0 |      0 |       0 |
| `packages/api/tests/test_perf.py`                                  |      9 |      0 |      0 |       0 |
| `packages/api/tests/test_perf_rag_retrieval.py`                    |      1 |      0 |      0 |       0 |
| `packages/api/tests/test_persist.py`                               |     10 |      0 |      0 |       0 |
| `packages/api/tests/test_physical_robots.py`                       |     59 |      0 |      0 |       0 |
| `packages/api/tests/test_pins.py`                                  |     13 |      0 |      0 |       0 |
| `packages/api/tests/test_plans.py`                                 |      7 |      0 |      0 |       0 |
| `packages/api/tests/test_preferences.py`                           |     15 |      0 |      0 |       0 |
| `packages/api/tests/test_previews.py`                              |     11 |      0 |      0 |       0 |
| `packages/api/tests/test_projects.py`                              |     21 |      0 |      0 |       0 |
| `packages/api/tests/test_prompt.py`                                |    109 |      0 |      0 |       0 |
| `packages/api/tests/test_protel_netlist.py`                        |      8 |      0 |      0 |       0 |
| `packages/api/tests/test_provider_tools.py`                        |     25 |      0 |      0 |       0 |
| `packages/api/tests/test_providers.py`                             |     25 |      0 |      0 |       0 |
| `packages/api/tests/test_ratelimit.py`                             |     10 |      0 |      0 |       0 |
| `packages/api/tests/test_reason.py`                                |     16 |      0 |      0 |       0 |
| `packages/api/tests/test_reason_eval.py`                           |      3 |      0 |      0 |       0 |
| `packages/api/tests/test_reconciliation.py`                        |      5 |      0 |      0 |       0 |
| `packages/api/tests/test_registry.py`                              |      5 |      0 |      0 |       0 |
| `packages/api/tests/test_resolution.py`                            |      8 |      0 |      0 |       0 |
| `packages/api/tests/test_resolver.py`                              |      3 |      0 |      0 |       0 |
| `packages/api/tests/test_responses.py`                             |      2 |      0 |      0 |       0 |
| `packages/api/tests/test_retrieval.py`                             |     19 |      0 |      0 |       0 |
| `packages/api/tests/test_retry.py`                                 |     10 |      0 |      0 |       0 |
| `packages/api/tests/test_router.py`                                |     18 |      0 |      0 |       0 |
| `packages/api/tests/test_runtime.py`                               |     11 |      0 |      0 |       0 |
| `packages/api/tests/test_schema_drift_warning.py`                  |      3 |      0 |      0 |       0 |
| `packages/api/tests/test_schemas.py`                               |      9 |      0 |      0 |       0 |
| `packages/api/tests/test_secrets.py`                               |      8 |      0 |      0 |       0 |
| `packages/api/tests/test_security.py`                              |     12 |      0 |      0 |       0 |
| `packages/api/tests/test_seed_script.py`                           |      4 |      0 |      0 |       0 |
| `packages/api/tests/test_service.py`                               |     13 |      0 |      0 |       0 |
| `packages/api/tests/test_sessions.py`                              |     12 |      0 |      0 |       0 |
| `packages/api/tests/test_shapes.py`                                |      8 |      0 |      0 |       0 |
| `packages/api/tests/test_shared_models.py`                         |      5 |      0 |      0 |       0 |
| `packages/api/tests/test_sol.py`                                   |     32 |      0 |      0 |       0 |
| `packages/api/tests/test_sol_interface.py`                         |      5 |      0 |      0 |       0 |
| `packages/api/tests/test_sol_red_team.py`                          |     63 |      0 |      0 |       0 |
| `packages/api/tests/test_sol_runtime.py`                           |     14 |      0 |      0 |       0 |
| `packages/api/tests/test_solus_config.py`                          |     12 |      0 |      0 |       0 |
| `packages/api/tests/test_solus_config_parse.py`                    |      5 |      0 |      0 |       0 |
| `packages/api/tests/test_solus_entry.py`                           |      2 |      0 |      0 |       0 |
| `packages/api/tests/test_solus_graph.py`                           |     11 |      0 |      0 |       0 |
| `packages/api/tests/test_solx01_hardening.py`                      |     11 |      0 |      0 |       0 |
| `packages/api/tests/test_sources.py`                               |     15 |      0 |      0 |       0 |
| `packages/api/tests/test_step_parser.py`                           |     17 |      0 |      0 |       1 |
| `packages/api/tests/test_store.py`                                 |      5 |      2 |      0 |       0 |
| `packages/api/tests/test_stream.py`                                |      7 |      0 |      0 |       0 |
| `packages/api/tests/test_stripe_gateway.py`                        |      6 |      0 |      0 |       0 |
| `packages/api/tests/test_stripe_setup.py`                          |     61 |      0 |      0 |       0 |
| `packages/api/tests/test_supabase_admin.py`                        |      5 |      0 |      0 |       0 |
| `packages/api/tests/test_sync_live_acquisition.py`                 |      8 |      0 |      0 |       0 |
| `packages/api/tests/test_sync_write_path.py`                       |      6 |      0 |      0 |       0 |
| `packages/api/tests/test_teams.py`                                 |      9 |      0 |      0 |       0 |
| `packages/api/tests/test_telemetry.py`                             |     18 |      0 |      0 |       0 |
| `packages/api/tests/test_telemetry_corpus.py`                      |     60 |      0 |      0 |       0 |
| `packages/api/tests/test_tool.py`                                  |      3 |      0 |      0 |       0 |
| `packages/api/tests/test_tool_docs.py`                             |     17 |      0 |      0 |       0 |
| `packages/api/tests/test_tool_registry.py`                         |     10 |      0 |      0 |       0 |
| `packages/api/tests/test_traversal.py`                             |      8 |      0 |      0 |       0 |
| `packages/api/tests/test_type_estimator.py`                        |     38 |      0 |      0 |       0 |
| `packages/api/tests/test_type_labels.py`                           |      4 |      0 |      0 |       0 |
| `packages/api/tests/test_untrusted.py`                             |      6 |      0 |      0 |       0 |
| `packages/api/tests/test_usage.py`                                 |     10 |      0 |      0 |       0 |
| `packages/api/tests/test_users.py`                                 |     17 |      0 |      0 |       0 |
| `packages/api/tests/test_vendor_hygiene_api.py`                    |      1 |      0 |      0 |       0 |
| `packages/api/tests/test_verification.py`                          |     10 |      0 |      0 |       0 |
| `packages/api/tests/test_visual.py`                                |     17 |      0 |      0 |       0 |
| `packages/api/tests/test_webhook_token.py`                         |      5 |      0 |      0 |       0 |
| `packages/api/tests/test_webhooks.py`                              |     14 |      0 |      0 |       0 |
| `packages/api/tests/test_widget_bundle_routes.py`                  |     14 |      0 |      0 |       0 |
| `packages/api/tests/test_widget_bundles.py`                        |     23 |      0 |      0 |       0 |
| `packages/api/tests/test_widget_graph_nodes.py`                    |     19 |      0 |      0 |       0 |
| `packages/api/tests/test_widget_graph_routes.py`                   |      7 |      0 |      0 |       0 |
| `packages/api/tests/test_widget_layout.py`                         |     18 |      0 |      0 |       0 |
| `packages/api/tests/test_worker.py`                                |      3 |      0 |      0 |       0 |
| `packages/api/tests/test_worker_main.py`                           |      1 |      0 |      0 |       0 |
| `packages/api/tests/test_workspace_layout.py`                      |     49 |      0 |      0 |       0 |
| `packages/api/tests/test_workspace_service_phase3.py`              |     49 |      0 |      0 |       0 |
| `packages/api/tests/toolkb/router_test.py`                         |     14 |      0 |      0 |       0 |
| `packages/api/tests/toolkb/test_catalog.py`                        |     18 |      0 |      0 |       0 |
| `packages/api/tests/toolkb/test_feedback.py`                       |     11 |      0 |      0 |       0 |
| `packages/api/tests/toolkb/test_guard.py`                          |     30 |      0 |      0 |       0 |
| `packages/api/tests/toolkb/test_guides.py`                         |      6 |      0 |      0 |       0 |
| `packages/api/tests/toolkb/test_kicad.py`                          |     14 |      0 |      0 |       0 |
| `packages/api/tests/toolkb/test_review.py`                         |      4 |      0 |      0 |       0 |
| `packages/api/tests/toolkb/test_schema.py`                         |     36 |      0 |      0 |       0 |
| `packages/api/tests/toolkb/test_sharing.py`                        |     15 |      0 |      0 |       0 |
| `packages/api/tests/toolkb/test_staleness.py`                      |      8 |      0 |      0 |       0 |
| `packages/api/tests/toolkb/test_storage.py`                        |      6 |      0 |      0 |       0 |
| `packages/api/tests/toolkb/visual_test.py`                         |      7 |      0 |      0 |       0 |

## Failing cases

- `packages/api/tests/test_bench_robot_provider.py::test_robot_session_opens_from_the_config` — AssertionError: {"error":{"code":"not_found","message":"Hardware entity not found","details":[]}}
- `packages/api/tests/test_bench_robot_provider.py::test_robot_session_maps_open_failures_honestly[error0-404-device_not_found]` — AssertionError: {"error":{"code":"not_found","message":"Hardware entity not found","details":[]}}
- `packages/api/tests/test_bench_robot_provider.py::test_robot_session_maps_open_failures_honestly[error1-503-source_unavailable]` — AssertionError: {"error":{"code":"not_found","message":"Hardware entity not found","details":[]}}
- `packages/api/tests/test_bridge_e2e.py::test_full_companion_cloud_round_trip` — AssertionError: assert {'mock.add', ...'mock.sleepy'} <= set()
- `packages/api/tests/test_hardware_detect.py::test_confirm_creates_the_robot_parts_config_and_optionally_the_session` — AssertionError: assert None == '/dev/serial/by-id/usb-1a86-5B42134331'
- `packages/api/tests/test_hardware_detect.py::test_confirm_with_a_chosen_repo_config_imports_calibration_with_repo_provenance` — AssertionError: assert 'source:7994f...-b0c4f274d9e8' == '/cal/cfg1.json'
- `packages/api/tests/test_library_router.py::test_import_part_into_a_robot` — KeyError: 'parts.01a08dd6-33ea-7af2-a933-391df189499a'
- `packages/api/tests/test_hardware_detect.py::test_the_second_arm_is_offered_only_the_remaining_repo_config` — pydantic_core.\_pydantic_core.ValidationError: 4 validation errors for HardwareConfig
- `packages/api/tests/test_hardware_detect.py::test_a_library_robot_and_the_same_machine_on_the_wire_reconcile_to_one_robot` — pydantic_core.\_pydantic_core.ValidationError: 4 validation errors for HardwareConfig
- `packages/api/tests/test_hardware_router.py::test_put_config_replaces_the_document` — AssertionError: {"error":{"code":"not_found","message":"Hardware entity not found","details":[]}}
- `packages/api/tests/test_hardware_router.py::test_post_parts_creates_a_contained_planned_part_recorded_in_the_config` — assert []
- `packages/api/tests/test_hardware_router.py::test_write_routes_emit_data_events_when_consented` — AssertionError: {"error":{"code":"not_found","message":"Hardware entity not found","details":[]}}
- `packages/api/tests/test_store.py::test_ensure_config_creates_one_entry_and_references_it_from_the_robot` — AssertionError: assert EntityHardwar...3ce1746ec9f')) == HardwareConfi...provenance={})
- `packages/api/tests/test_store.py::test_create_part_lands_under_the_category_and_in_the_config` — AttributeError: 'EntityHardwareConfig' object has no attribute 'parts'

Raw evidence: `/tmp/solus260-api-phase0.log` and `/tmp/solus260-api-phase0.xml`.
These are baseline failures, not a passing release gate.

## Targeted bridge retest

`test_bridge_e2e.py` subsequently **passed (1 test, 5.20 seconds)** with this
checkout's `.venv/bin` prepended to PATH and separate database
`solus_test_436a6e18_bridge`. The tracked mock interpreter shim executes
`python3` from PATH; the original full-suite launch inherited the host Python.
No production or fixture code changed. Evidence: `/tmp/solus260-bridge-phase0.log`
and `/tmp/solus260-bridge-phase0.xml`. The table preserves the original full run;
13 baseline failures remain unresolved after this targeted retest.
