cd /app && cat > backend/resources/migrations/sqlite/041_create_drift_detection_tables.up.sql <<'EOF'
CREATE TABLE IF NOT EXISTS environment_baselines (
    id TEXT PRIMARY KEY,
    environment_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    created_by TEXT NOT NULL DEFAULT '',
    container_configs TEXT,
    captured_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    container_count INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME
);

CREATE TABLE IF NOT EXISTS drift_records (
    id TEXT PRIMARY KEY,
    baseline_id TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    container_name TEXT NOT NULL DEFAULT '',
    container_id TEXT NOT NULL DEFAULT '',
    drift_type TEXT NOT NULL DEFAULT '',
    field TEXT NOT NULL DEFAULT '',
    expected_value TEXT NOT NULL DEFAULT '',
    actual_value TEXT NOT NULL DEFAULT '',
    severity TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'detected',
    detected_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME
);

CREATE TABLE IF NOT EXISTS compliance_snapshots (
    id TEXT PRIMARY KEY,
    environment_id TEXT NOT NULL,
    baseline_id TEXT NOT NULL,
    total_containers INTEGER NOT NULL DEFAULT 0,
    compliant_containers INTEGER NOT NULL DEFAULT 0,
    drifted_containers INTEGER NOT NULL DEFAULT 0,
    missing_containers INTEGER NOT NULL DEFAULT 0,
    added_containers INTEGER NOT NULL DEFAULT 0,
    critical_drifts INTEGER NOT NULL DEFAULT 0,
    high_drifts INTEGER NOT NULL DEFAULT 0,
    medium_drifts INTEGER NOT NULL DEFAULT 0,
    low_drifts INTEGER NOT NULL DEFAULT 0,
    compliance_score REAL NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME
);

CREATE INDEX IF NOT EXISTS idx_environment_baselines_environment_id ON environment_baselines(environment_id);
CREATE INDEX IF NOT EXISTS idx_drift_records_baseline_id ON drift_records(baseline_id);
CREATE INDEX IF NOT EXISTS idx_drift_records_environment_id ON drift_records(environment_id);
CREATE INDEX IF NOT EXISTS idx_drift_records_status ON drift_records(status);
CREATE INDEX IF NOT EXISTS idx_compliance_snapshots_environment_id ON compliance_snapshots(environment_id);
CREATE INDEX IF NOT EXISTS idx_compliance_snapshots_baseline_id ON compliance_snapshots(baseline_id);
EOF
cat > backend/resources/migrations/sqlite/041_create_drift_detection_tables.down.sql <<'EOF'
DROP TABLE IF EXISTS compliance_snapshots;
DROP TABLE IF EXISTS drift_records;
DROP TABLE IF EXISTS environment_baselines;
EOF
cat > backend/resources/migrations/postgres/041_create_drift_detection_tables.up.sql <<'EOF'
CREATE TABLE IF NOT EXISTS environment_baselines (
    id TEXT PRIMARY KEY,
    environment_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    created_by TEXT NOT NULL DEFAULT '',
    container_configs TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    container_count INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS drift_records (
    id TEXT PRIMARY KEY,
    baseline_id TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    container_name TEXT NOT NULL DEFAULT '',
    container_id TEXT NOT NULL DEFAULT '',
    drift_type TEXT NOT NULL DEFAULT '',
    field TEXT NOT NULL DEFAULT '',
    expected_value TEXT NOT NULL DEFAULT '',
    actual_value TEXT NOT NULL DEFAULT '',
    severity TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'detected',
    detected_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS compliance_snapshots (
    id TEXT PRIMARY KEY,
    environment_id TEXT NOT NULL,
    baseline_id TEXT NOT NULL,
    total_containers INTEGER NOT NULL DEFAULT 0,
    compliant_containers INTEGER NOT NULL DEFAULT 0,
    drifted_containers INTEGER NOT NULL DEFAULT 0,
    missing_containers INTEGER NOT NULL DEFAULT 0,
    added_containers INTEGER NOT NULL DEFAULT 0,
    critical_drifts INTEGER NOT NULL DEFAULT 0,
    high_drifts INTEGER NOT NULL DEFAULT 0,
    medium_drifts INTEGER NOT NULL DEFAULT 0,
    low_drifts INTEGER NOT NULL DEFAULT 0,
    compliance_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_environment_baselines_environment_id ON environment_baselines(environment_id);
CREATE INDEX IF NOT EXISTS idx_drift_records_baseline_id ON drift_records(baseline_id);
CREATE INDEX IF NOT EXISTS idx_drift_records_environment_id ON drift_records(environment_id);
CREATE INDEX IF NOT EXISTS idx_drift_records_status ON drift_records(status);
CREATE INDEX IF NOT EXISTS idx_compliance_snapshots_environment_id ON compliance_snapshots(environment_id);
CREATE INDEX IF NOT EXISTS idx_compliance_snapshots_baseline_id ON compliance_snapshots(baseline_id);
EOF
cat > backend/resources/migrations/postgres/041_create_drift_detection_tables.down.sql <<'EOF'
DROP TABLE IF EXISTS compliance_snapshots;
DROP TABLE IF EXISTS drift_records;
DROP TABLE IF EXISTS environment_baselines;
EOF
ls backend/resources/migrations/sqlite/041* backend/resources/migrations/postgres/041*