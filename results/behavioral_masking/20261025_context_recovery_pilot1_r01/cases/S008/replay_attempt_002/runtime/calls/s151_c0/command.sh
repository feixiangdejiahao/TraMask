cd /app && git add -A && git status --short && git commit -m "feat: implement drift detection engine with compliance baselines

- Add ContainerConfig, EnvironmentBaseline, DriftRecord, ComplianceSnapshot models
- Add SQLite and Postgres migration 041 for drift detection tables
- Implement DriftDetectionService with baseline capture, detection, auto-resolve,
  compliance snapshots, and scheduled runs
- Add drift-detection scheduler job controlled by driftDetection settings
- Add native Gin compliance handler under /environments/:id/compliance
- Wire drift detection service, routes, and job into bootstrap
- Add driftDetectionEnabled and driftDetectionInterval settings" | tail -5