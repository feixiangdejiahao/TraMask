cd /app && git config user.email "dev@arcane.local" && git config user.name "Arcane Dev" && git commit -m "feat: implement drift detection engine with compliance baselines

- Add ContainerConfig, EnvironmentBaseline, DriftRecord, ComplianceSnapshot models
- Add SQLite and Postgres migration 041 for drift detection tables
- Implement DriftDetectionService with baseline capture, detection, auto-resolve,
  compliance snapshots, and scheduled runs
- Add drift-detection scheduler job controlled by driftDetection settings
- Add native Gin compliance handler under /environments/:id/compliance
- Wire drift detection service, routes, and job into bootstrap
- Add driftDetectionEnabled and driftDetectionInterval settings" | tail -5