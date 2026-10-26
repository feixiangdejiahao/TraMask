cd /app && cat > backend/internal/models/drift_detection.go <<'EOF'
package models

import (
	"encoding/json"
	"time"
)

// ContainerConfig represents the desired/live configuration for a single container
// used by the drift detection engine.
type ContainerConfig struct {
	Image         string            `json:"image"`
	RestartPolicy string            `json:"restartPolicy"`
	NetworkMode   string            `json:"networkMode"`
	Env           []string          `json:"env"`
	Ports         []string          `json:"ports"`
	Volumes       []string          `json:"volumes"`
	Labels        map[string]string `json:"labels"`
	MemoryLimit   int64             `json:"memoryLimit"`
	CpuLimit      float64           `json:"cpuLimit"`
}

// EnvironmentBaseline stores a captured baseline of container configurations for
// an environment. The actual container configs are stored as JSON.
type EnvironmentBaseline struct {
	EnvironmentID    string      `json:"environmentId" gorm:"column:environment_id;index"`
	Name             string      `json:"name" gorm:"column:name"`
	Description      string      `json:"description" gorm:"column:description"`
	CreatedBy        string      `json:"createdBy" gorm:"column:created_by"`
	ContainerConfigs JSON        `json:"containerConfigs,omitempty" gorm:"column:container_configs;type:text"`
	CapturedAt       time.Time   `json:"capturedAt" gorm:"column:captured_at"`
	ContainerCount   int         `json:"containerCount" gorm:"column:container_count"`
	IsActive         bool        `json:"isActive" gorm:"column:is_active;default:false"`
	BaseModel
}

func (EnvironmentBaseline) TableName() string {
	return "environment_baselines"
}

// GetContainerConfigs decodes the stored JSON container configs into a typed map.
func (b *EnvironmentBaseline) GetContainerConfigs() (map[string]ContainerConfig, error) {
	if b.ContainerConfigs == nil {
		return map[string]ContainerConfig{}, nil
	}

	raw, err := json.Marshal(b.ContainerConfigs)
	if err != nil {
		return nil, err
	}

	var out map[string]ContainerConfig
	if err := json.Unmarshal(raw, &out); err != nil {
		return nil, err
	}
	return out, nil
}

// SetContainerConfigs encodes a typed container config map for JSON storage.
func (b *EnvironmentBaseline) SetContainerConfigs(configs map[string]ContainerConfig) error {
	raw, err := json.Marshal(configs)
	if err != nil {
		return err
	}

	var out JSON
	if err := json.Unmarshal(raw, &out); err != nil {
		return err
	}
	b.ContainerConfigs = out
	return nil
}

// DriftRecord represents a single detected configuration drift.
type DriftRecord struct {
	BaselineID    string     `json:"baselineId" gorm:"column:baseline_id;index"`
	EnvironmentID string     `json:"environmentId" gorm:"column:environment_id;index"`
	ContainerName string     `json:"containerName" gorm:"column:container_name"`
	ContainerID   string     `json:"containerId" gorm:"column:container_id"`
	DriftType     string     `json:"driftType" gorm:"column:drift_type"`
	Field         string     `json:"field" gorm:"column:field"`
	ExpectedValue string     `json:"expectedValue" gorm:"column:expected_value"`
	ActualValue   string     `json:"actualValue" gorm:"column:actual_value"`
	Severity      string     `json:"severity" gorm:"column:severity"`
	Status        string     `json:"status" gorm:"column:status;index"`
	DetectedAt    time.Time  `json:"detectedAt" gorm:"column:detected_at"`
	ResolvedAt    *time.Time `json:"resolvedAt,omitempty" gorm:"column:resolved_at"`
	BaseModel
}

func (DriftRecord) TableName() string {
	return "drift_records"
}

// ComplianceSnapshot stores the result of a single drift detection run.
type ComplianceSnapshot struct {
	EnvironmentID       string  `json:"environmentId" gorm:"column:environment_id;index"`
	BaselineID          string  `json:"baselineId" gorm:"column:baseline_id;index"`
	TotalContainers     int     `json:"totalContainers" gorm:"column:total_containers"`
	CompliantContainers int     `json:"compliantContainers" gorm:"column:compliant_containers"`
	DriftedContainers   int     `json:"driftedContainers" gorm:"column:drifted_containers"`
	MissingContainers   int     `json:"missingContainers" gorm:"column:missing_containers"`
	AddedContainers     int     `json:"addedContainers" gorm:"column:added_containers"`
	CriticalDrifts      int     `json:"criticalDrifts" gorm:"column:critical_drifts"`
	HighDrifts          int     `json:"highDrifts" gorm:"column:high_drifts"`
	MediumDrifts        int     `json:"mediumDrifts" gorm:"column:medium_drifts"`
	LowDrifts           int     `json:"lowDrifts" gorm:"column:low_drifts"`
	ComplianceScore     float64 `json:"complianceScore" gorm:"column:compliance_score"`
	BaseModel
}

func (ComplianceSnapshot) TableName() string {
	return "compliance_snapshots"
}

// Drift statuses
const (
	DriftStatusDetected     = "detected"
	DriftStatusAcknowledged = "acknowledged"
	DriftStatusIgnored      = "ignored"
	DriftStatusResolved     = "resolved"
)
EOF
gofmt -w backend/internal/models/drift_detection.go && echo OK