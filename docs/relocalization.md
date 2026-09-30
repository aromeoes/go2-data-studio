# Saved-map relocalization

Select a space and a ready reference map under Space map (or Use for localization in Generated maps). Pause movement and save the recording first. Selection reconnects the session with movement idle. Mapping and LiDAR must be enabled.

The application subclasses DimOS Go2Relocalization. It reuses the DimOS accumulated voxel map, LidarRelocalizer (FPFH, RANSAC, ICP), transform publication, and saved/live map merge. The Deck and Mac run this on CPU. Catalog-owned maps are read directly from disk, without framework dataset discovery or Git lookup. Map initialization errors are exposed in localization status instead of aborting the robot session. Structural-surface filtering avoids floor-dominated false matches observed with the apartment recording. The room configuration is experimental, separate from the upstream outdoor Mid360 preset.

A candidate needs overlap at least 90%, fit RMSE at most 8 cm, plausible gravity orientation and three successive transformations within 25 cm and 5 degrees. These scores do not prove location. Check the displayed robot position against the real room, then select Confirm robot location. Until confirmed, autonomous navigation is blocked, while Teleop is available. Confirmation does not start motion. Retry restarts the session idle. Selecting Live map only clears the saved-map requirement.

The map display and planner stay in live odometry coordinates. The saved map is transformed into that frame. Map-relative coordinates appear in the localization panel. Names tagged after confirmed localization are stored in the saved map frame and keyed to that map's ID and content hash. They can be reused after reconnecting and confirming localization to the same map. Older, unanchored tags need to be tagged again. Another generated map, even in the same space, is a different anchor.

Alignment freezes after acceptance. This is startup relocalization, not continuous drift correction, automatic room recognition, or multi-session map fusion. A reconnect requires a new match and confirmation. Stale aligned-map telemetry blocks autonomous commands. The CPU merge conservatively retains old obstacles; regenerate the map when the layout changes.

Testing includes backend gates, map identity, coordinate transforms, saved-name round trips, UI status, and an offline recorded-data harness at scripts/test_relocalization_recording.py. Recovery tests using the recording that generated the map are smoke tests, not independent accuracy validation. An unaccepted baseline is reported as inconclusive. Unrelated clouds and flat floor geometry must be rejected. Use independent recordings and operator-verified poses before relying on patrol localization.

The reproducible stream integration test is `scripts/test_relocalization_pipeline.py`. Pass a local PointCloud2 map path. It launches only a recorded-cloud source, the relocalizer, CostMapper and a costmap observer on a separate local transport. It checks recovery of a planted transform, candidate status, merged costmap publication, and confirmation. It never instantiates a robot connection. This test passed on both macOS and the Steam Deck.

## Offline diagnosis after the first live trial

The original integration matched only the latest 15 scans. Walking did not retain earlier views for registration. The matcher now consumes VoxelGridMapper.global_map, which accumulates geometry in the live odometry frame, at the existing four-second attempt interval. It never consumes its own merged output. Mapping is already a required dependency, so this adds no additional mapper. As a startup matcher, it should be used early in a session; long walks can accumulate odometry drift that no single rigid transform can correct.

Acceptance limits are unchanged. Status messages distinguish low overlap, excessive fit error, tilted transforms, and inconsistent candidates. Each attempt logs its candidate matrix, structural point count, cloud extent, metrics, and rejection reason to runtime.log. Candidate matrices are diagnostic only; they never replace world_from_map before acceptance.

The apartment reference map was generated with pose-graph optimization (PGO). Raw recording coordinates are therefore not ground truth for this saved map. A planted-transform comparison must use a consistent accepted baseline and remains a recovery smoke test, not independent proof of a correct room match. No live success has yet been established. A fresh powered-on test is still required.
