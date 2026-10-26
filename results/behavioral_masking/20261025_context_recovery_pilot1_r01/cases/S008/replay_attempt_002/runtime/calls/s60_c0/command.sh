cd /app && cat > backend/internal/services/drift_detection_service.go <<'EOF'
package services

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/getarcaneapp/arcane/backend/internal/database"
	"github.com/getarcaneapp/arcane/backend/internal/models"
	"github.com/getarcaneapp/arcane/types"
	"github.com/moby/moby/api/types/container"
	"gorm.io/gorm"
)

// DriftDetectionService compares live container state against captured baselines
// and records configuration drifts.
type DriftDetectionService struct {
	db                  *database.DB
	dockerService       *DockerClientService
	containerService    *ContainerService
	eventService        *EventService
	settingsService     *SettingsService
	notificationService *NotificationService
}

// NewDriftDetectionService creates a new drift detection service. All dependencies
// may be nil (the service gracefully degrades when optional dependencies are absent).
func NewDriftDetectionService(
	db *database.DB,
	dockerSvc *DockerClientService,
	containerSvc *ContainerService,
	eventSvc *EventService,
	settingsSvc *SettingsService,
	notificationSvc *NotificationService,
) *DriftDetectionService {
	return &DriftDetectionService{
		db:                  db,
		dockerService:       dockerSvc,
		containerService:    containerSvc,
		eventService:        eventSvc,
		settingsService:     settingsSvc,
		notificationService: notificationSvc,
	}
}

// CaptureBaselineFromConfigs creates a new active baseline for an environment,
// deactivating any previously active baselines.
func (s *DriftDetectionService) CaptureBaselineFromConfigs(
	ctx context.Context,
	envID, name, desc, userID string,
	containers map[string]models.ContainerConfig,
) (*models.EnvironmentBaseline, error) {
	baseline := &models.EnvironmentBaseline{
		EnvironmentID:  envID,
		Name:           name,
		Description:    desc,
		CreatedBy:      userID,
		CapturedAt:     time.Now().UTC(),
		ContainerCount: len(containers),
		IsActive:       true,
	}
	if err := baseline.SetContainerConfigs(containers); err != nil {
		return nil, fmt.Errorf("failed to encode container configs: %w", err)
	}

	err := s.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		if err := tx.Model(&models.EnvironmentBaseline{}).
			Where("environment_id = ? AND is_active = ?", envID, true).
			Update("is_active", false).Error; err != nil {
			return err
		}
		return tx.Create(baseline).Error
	})
	if err != nil {
		return nil, fmt.Errorf("failed to capture baseline: %w", err)
	}
	return baseline, nil
}

// GetBaseline returns a baseline by ID. It returns nil, nil when the baseline
// does not exist.
func (s *DriftDetectionService) GetBaseline(ctx context.Context, baselineID string) (*models.EnvironmentBaseline, error) {
	var baseline models.EnvironmentBaseline
	err := s.db.WithContext(ctx).First(&baseline, "id = ?", baselineID).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return &baseline, nil
}

// ListBaselines returns baselines for an environment, newest first, along with
// the total number of baselines.
func (s *DriftDetectionService) ListBaselines(ctx context.Context, envID string, limit, offset int) ([]models.EnvironmentBaseline, int64, error) {
	var total int64
	if err := s.db.WithContext(ctx).Model(&models.EnvironmentBaseline{}).
		Where("environment_id = ?", envID).
		Count(&total).Error; err != nil {
		return nil, 0, err
	}

	q := s.db.WithContext(ctx).
		Where("environment_id = ?", envID).
		Order("created_at DESC")
	if limit > 0 {
		q = q.Limit(limit)
	}
	if offset > 0 {
		q = q.Offset(offset)
	}

	var baselines []models.EnvironmentBaseline
	if err := q.Find(&baselines).Error; err != nil {
		return nil, 0, err
	}
	return baselines, total, nil
}

// SetActiveBaseline makes the given baseline the active baseline for its environment.
func (s *DriftDetectionService) SetActiveBaseline(ctx context.Context, baselineID string) error {
	var baseline models.EnvironmentBaseline
	err := s.db.WithContext(ctx).First(&baseline, "id = ?", baselineID).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return errors.New("baseline not found")
	}
	if err != nil {
		return err
	}

	return s.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		if err := tx.Model(&models.EnvironmentBaseline{}).
			Where("environment_id = ?", baseline.EnvironmentID).
			Update("is_active", false).Error; err != nil {
			return err
		}
		return tx.Model(&models.EnvironmentBaseline{}).
			Where("id = ?", baseline.ID).
			Update("is_active", true).Error
	})
}

// DeleteBaseline removes a baseline and, as an application-level cascade,
// explicitly deletes its associated drift records and compliance snapshots.
func (s *DriftDetectionService) DeleteBaseline(ctx context.Context, baselineID string) error {
	var baseline models.EnvironmentBaseline
	err := s.db.WithContext(ctx).First(&baseline, "id = ?", baselineID).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return errors.New("baseline not found")
	}
	if err != nil {
		return err
	}

	return s.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		if err := tx.Where("baseline_id = ?", baselineID).Delete(&models.DriftRecord{}).Error; err != nil {
			return err
		}
		if err := tx.Where("baseline_id = ?", baselineID).Delete(&models.ComplianceSnapshot{}).Error; err != nil {
			return err
		}
		return tx.Delete(&baseline).Error
	})
}

// DetectDriftFromConfigs compares the supplied live container configurations
// against the active baseline and records drifts and a compliance snapshot.
// It returns an error containing "no active baseline" when the environment has
// no active baseline.
func (s *DriftDetectionService) DetectDriftFromConfigs(
	ctx context.Context,
	envID string,
	containers map[string]models.ContainerConfig,
) (*models.ComplianceSnapshot, error) {
	baseline, err := s.getActiveBaseline(ctx, envID)
	if err != nil {
		return nil, err
	}
	if baseline == nil {
		return nil, errors.New("no active baseline")
	}

	baselineConfigs, err := baseline.GetContainerConfigs()
	if err != nil {
		return nil, fmt.Errorf("failed to decode baseline configs: %w", err)
	}

	current := s.computeDrifts(baselineConfigs, containers)
	conditionByKey := make(map[string]driftDetection, len(current))
	for _, d := range current {
		conditionByKey[driftRecordKey(d.ContainerName, d.DriftType, d.Field)] = d
	}

	// Load active records (detected/acknowledged/ignored). Resolved records are
	// treated as history, so a recurring drift creates a fresh detected record.
	var existing []models.DriftRecord
	if err := s.db.WithContext(ctx).
		Where("baseline_id = ? AND environment_id = ? AND status != ?", baseline.ID, envID, models.DriftStatusResolved).
		Find(&existing).Error; err != nil {
		return nil, err
	}

	existingByKey := make(map[string]models.DriftRecord, len(existing))
	for _, rec := range existing {
		existingByKey[driftRecordKey(rec.ContainerName, rec.DriftType, rec.Field)] = rec
	}

	now := time.Now().UTC()

	// Auto-resolve detected records whose condition has cleared. Acknowledged
	// and ignored records are never auto-resolved.
	for key, rec := range existingByKey {
		if rec.Status != models.DriftStatusDetected {
			continue
		}
		if _, stillPresent := conditionByKey[key]; stillPresent {
			continue
		}
		resolvedAt := now
		rec.Status = models.DriftStatusResolved
		rec.ResolvedAt = &resolvedAt
		if err := s.db.WithContext(ctx).Save(&rec).Error; err != nil {
			return nil, fmt.Errorf("failed to resolve drift record: %w", err)
		}
	}

	// Create records for conditions that do not already have an active record.
	var newRecords []models.DriftRecord
	for key, d := range conditionByKey {
		if _, exists := existingByKey[key]; exists {
			continue
		}
		newRecords = append(newRecords, models.DriftRecord{
			BaselineID:    baseline.ID,
			EnvironmentID: envID,
			ContainerName: d.ContainerName,
			ContainerID:   d.ContainerID,
			DriftType:     d.DriftType,
			Field:         d.Field,
			ExpectedValue: d.ExpectedValue,
			ActualValue:   d.ActualValue,
			Severity:      d.Severity,
			Status:        models.DriftStatusDetected,
			DetectedAt:    now,
		})
	}
	if len(newRecords) > 0 {
		if err := s.db.WithContext(ctx).Create(&newRecords).Error; err != nil {
			return nil, fmt.Errorf("failed to create drift records: %w", err)
		}
	}

	snapshot := s.buildComplianceSnapshot(baseline.ID, envID, baselineConfigs, containers, current)
	if err := s.db.WithContext(ctx).Create(snapshot).Error; err != nil {
		return nil, fmt.Errorf("failed to save compliance snapshot: %w", err)
	}
	return snapshot, nil
}

// GetActiveDrifts returns all currently detected drift records for an environment.
func (s *DriftDetectionService) GetActiveDrifts(ctx context.Context, envID string) ([]models.DriftRecord, error) {
	var records []models.DriftRecord
	err := s.db.WithContext(ctx).
		Where("environment_id = ? AND status = ?", envID, models.DriftStatusDetected).
		Order("detected_at DESC, created_at DESC").
		Find(&records).Error
	if err != nil {
		return nil, err
	}
	return records, nil
}

// AcknowledgeDrift marks a drift record as acknowledged.
func (s *DriftDetectionService) AcknowledgeDrift(ctx context.Context, driftID string) error {
	return s.updateDriftStatus(ctx, driftID, models.DriftStatusAcknowledged)
}

// IgnoreDrift marks a drift record as ignored.
func (s *DriftDetectionService) IgnoreDrift(ctx context.Context, driftID string) error {
	return s.updateDriftStatus(ctx, driftID, models.DriftStatusIgnored)
}

func (s *DriftDetectionService) updateDriftStatus(ctx context.Context, driftID, status string) error {
	var rec models.DriftRecord
	if err := s.db.WithContext(ctx).First(&rec, "id = ?", driftID).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return errors.New("drift record not found")
		}
		return err
	}
	return s.db.WithContext(ctx).Model(&rec).Update("status", status).Error
}

// GetComplianceHistory returns compliance snapshots for an environment, newest first.
func (s *DriftDetectionService) GetComplianceHistory(ctx context.Context, envID string, limit, offset int) ([]models.ComplianceSnapshot, error) {
	q := s.db.WithContext(ctx).
		Where("environment_id = ?", envID).
		Order("created_at DESC")
	if limit > 0 {
		q = q.Limit(limit)
	}
	if offset > 0 {
		q = q.Offset(offset)
	}

	var snapshots []models.ComplianceSnapshot
	if err := q.Find(&snapshots).Error; err != nil {
		return nil, err
	}
	return snapshots, nil
}

// GetDriftRecords returns all drift records for an environment (all statuses),
// newest first by DetectedAt, along with the total count.
func (s *DriftDetectionService) GetDriftRecords(ctx context.Context, envID string, limit, offset int) ([]models.DriftRecord, int64, error) {
	var total int64
	if err := s.db.WithContext(ctx).Model(&models.DriftRecord{}).
		Where("environment_id = ?", envID).
		Count(&total).Error; err != nil {
		return nil, 0, err
	}

	q := s.db.WithContext(ctx).
		Where("environment_id = ?", envID).
		Order("detected_at DESC, created_at DESC")
	if limit > 0 {
		q = q.Limit(limit)
	}
	if offset > 0 {
		q = q.Offset(offset)
	}

	var records []models.DriftRecord
	if err := q.Find(&records).Error; err != nil {
		return nil, 0, err
	}
	return records, total, nil
}

// IsEnabled reports whether scheduled drift detection is enabled. When the
// settings service is nil, drift detection is considered enabled.
func (s *DriftDetectionService) IsEnabled(ctx context.Context) bool {
	if s.settingsService == nil {
		return true
	}
	return s.settingsService.GetBoolSetting(ctx, "driftDetectionEnabled", true)
}

// RunAllEnvironments runs drift detection for all environments. It returns
// immediately when the docker or container services are nil, or when drift
// detection is disabled.
func (s *DriftDetectionService) RunAllEnvironments(ctx context.Context) error {
	if s.dockerService == nil || s.containerService == nil {
		return nil
	}
	if !s.IsEnabled(ctx) {
		return nil
	}

	var envs []models.Environment
	if err := s.db.WithContext(ctx).Find(&envs).Error; err != nil {
		return fmt.Errorf("failed to list environments for drift detection: %w", err)
	}

	for _, env := range envs {
		if env.ID != types.LOCAL_DOCKER_ENVIRONMENT_ID {
			slog.DebugContext(ctx, "drift detection for remote environments is not yet supported; skipping",
				"environment_id", env.ID)
			continue
		}

		summaries, err := s.dockerService.GetAllContainers(ctx)
		if err != nil {
			slog.WarnContext(ctx, "failed to list containers for drift detection",
				"environment_id", env.ID, "error", err)
			continue
		}

		liveConfigs := s.liveConfigsFromSummaries(ctx, summaries)
		if _, err := s.DetectDriftFromConfigs(ctx, env.ID, liveConfigs); err != nil {
			if strings.Contains(strings.ToLower(err.Error()), "no active baseline") {
				continue
			}
			slog.WarnContext(ctx, "drift detection failed for environment",
				"environment_id", env.ID, "error", err)
		}
	}
	return nil
}

func (s *DriftDetectionService) getActiveBaseline(ctx context.Context, envID string) (*models.EnvironmentBaseline, error) {
	var baseline models.EnvironmentBaseline
	err := s.db.WithContext(ctx).
		Where("environment_id = ? AND is_active = ?", envID, true).
		First(&baseline).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return &baseline, nil
}

type driftDetection struct {
	ContainerName string
	ContainerID   string
	DriftType     string
	Field         string
	ExpectedValue string
	ActualValue   string
	Severity      string
}

func driftRecordKey(containerName, driftType, field string) string {
	return containerName + "\x00" + driftType + "\x00" + field
}

func (s *DriftDetectionService) computeDrifts(
	baselineConfigs map[string]models.ContainerConfig,
	liveConfigs map[string]models.ContainerConfig,
) []driftDetection {
	var drifts []driftDetection

	for name, bc := range baselineConfigs {
		lc, ok := liveConfigs[name]
		if !ok {
			drifts = append(drifts, driftDetection{
				ContainerName: name,
				DriftType:     "container_missing",
				Severity:      "critical",
				ExpectedValue: "present",
				ActualValue:   "missing",
			})
			continue
		}

		if bc.Image != lc.Image {
			drifts = append(drifts, driftDetection{
				ContainerName: name,
				DriftType:     "image_changed",
				ExpectedValue: bc.Image,
				ActualValue:   lc.Image,
				Severity:      "critical",
			})
		}
		if !equalStringSlices(bc.Env, lc.Env) {
			drifts = append(drifts, driftDetection{
				ContainerName: name,
				DriftType:     "env_changed",
				ExpectedValue: joinSlice(bc.Env),
				ActualValue:   joinSlice(lc.Env),
				Severity:      "high",
			})
		}
		if bc.NetworkMode != lc.NetworkMode {
			drifts = append(drifts, driftDetection{
				ContainerName: name,
				DriftType:     "network_changed",
				ExpectedValue: bc.NetworkMode,
				ActualValue:   lc.NetworkMode,
				Severity:      "high",
			})
		}
		if !equalStringSlices(bc.Ports, lc.Ports) {
			drifts = append(drifts, driftDetection{
				ContainerName: name,
				DriftType:     "config_changed",
				Field:         "ports",
				ExpectedValue: joinSlice(bc.Ports),
				ActualValue:   joinSlice(lc.Ports),
				Severity:      "high",
			})
		}
		if !equalStringSlices(bc.Volumes, lc.Volumes) {
			drifts = append(drifts, driftDetection{
				ContainerName: name,
				DriftType:     "config_changed",
				Field:         "volumes",
				ExpectedValue: joinSlice(bc.Volumes),
				ActualValue:   joinSlice(lc.Volumes),
				Severity:      "high",
			})
		}
		if bc.RestartPolicy != lc.RestartPolicy {
			drifts = append(drifts, driftDetection{
				ContainerName: name,
				DriftType:     "restart_policy_changed",
				ExpectedValue: bc.RestartPolicy,
				ActualValue:   lc.RestartPolicy,
				Severity:      "medium",
			})
		}
		if bc.MemoryLimit != lc.MemoryLimit {
			drifts = append(drifts, driftDetection{
				ContainerName: name,
				DriftType:     "resource_changed",
				Field:         "memoryLimit",
				ExpectedValue: strconv.FormatInt(bc.MemoryLimit, 10),
				ActualValue:   strconv.FormatInt(lc.MemoryLimit, 10),
				Severity:      "medium",
			})
		}
		if bc.CpuLimit != lc.CpuLimit {
			drifts = append(drifts, driftDetection{
				ContainerName: name,
				DriftType:     "resource_changed",
				Field:         "cpuLimit",
				ExpectedValue: strconv.FormatFloat(bc.CpuLimit, 'f', -1, 64),
				ActualValue:   strconv.FormatFloat(lc.CpuLimit, 'f', -1, 64),
				Severity:      "medium",
			})
		}
		if !equalLabels(bc.Labels, lc.Labels) {
			drifts = append(drifts, driftDetection{
				ContainerName: name,
				DriftType:     "label_changed",
				ExpectedValue: formatLabels(bc.Labels),
				ActualValue:   formatLabels(lc.Labels),
				Severity:      "low",
			})
		}
	}

	for name, lc := range liveConfigs {
		if _, ok := baselineConfigs[name]; !ok {
			drifts = append(drifts, driftDetection{
				ContainerName: name,
				DriftType:     "container_added",
				ActualValue:   lc.Image,
				Severity:      "medium",
			})
		}
	}

	return drifts
}

func (s *DriftDetectionService) buildComplianceSnapshot(
	baselineID, envID string,
	baselineConfigs, liveConfigs map[string]models.ContainerConfig,
	drifts []driftDetection,
) *models.ComplianceSnapshot {
	snapshot := &models.ComplianceSnapshot{
		EnvironmentID: envID,
		BaselineID:    baselineID,
		TotalContainers: len(baselineConfigs),
	}

	driftedNames := make(map[string]struct{})
	missingNames := make(map[string]struct{})
	for name, bc := range baselineConfigs {
		if _, ok := liveConfigs[name]; !ok {
			missingNames[name] = struct{}{}
		}
	}
	for name := range liveConfigs {
		if _, ok := baselineConfigs[name]; !ok {
			snapshot.AddedContainers++
		}
	}

	for _, d := range drifts {
		if d.ContainerName == "" {
			continue
		}
		if _, isBaseline := baselineConfigs[d.ContainerName]; isBaseline {
			driftedNames[d.ContainerName] = struct{}{}
		}
		switch d.Severity {
		case "critical":
			snapshot.CriticalDrifts++
		case "high":
			snapshot.HighDrifts++
		case "medium":
			snapshot.MediumDrifts++
		case "low":
			snapshot.LowDrifts++
		}
	}

	snapshot.MissingContainers = len(missingNames)
	snapshot.DriftedContainers = len(driftedNames)
	snapshot.CompliantContainers = snapshot.TotalContainers - snapshot.DriftedContainers
	if snapshot.TotalContainers == 0 {
		snapshot.ComplianceScore = 100.0
	} else {
		snapshot.ComplianceScore = float64(snapshot.CompliantContainers) / float64(snapshot.TotalContainers) * 100.0
	}

	return snapshot
}

func equalStringSlices(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	ac := append([]string(nil), a...)
	bc := append([]string(nil), b...)
	sort.Strings(ac)
	sort.Strings(bc)
	return slices.Equal(ac, bc)
}

func joinSlice(items []string) string {
	sorted := append([]string(nil), items...)
	sort.Strings(sorted)
	return strings.Join(sorted, ",")
}

func equalLabels(a, b map[string]string) bool {
	if len(a) != len(b) {
		return false
	}
	for k, v := range a {
		bv, ok := b[k]
		if !ok || bv != v {
			return false
		}
	}
	return true
}

func formatLabels(labels map[string]string) string {
	keys := make([]string, 0, len(labels))
	for k := range labels {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	parts := make([]string, 0, len(keys))
	for _, k := range keys {
		parts = append(parts, k+"="+labels[k])
	}
	return strings.Join(parts, ",")
}

func (s *DriftDetectionService) liveConfigsFromSummaries(
	ctx context.Context,
	summaries []container.Summary,
) map[string]models.ContainerConfig {
	out := make(map[string]models.ContainerConfig, len(summaries))
	for _, c := range summaries {
		name := c.ID
		if len(c.Names) > 0 {
			name = strings.TrimPrefix(c.Names[0], "/")
		}

		cfg := models.ContainerConfig{
			Image:       c.Image,
			Labels:      c.Labels,
			NetworkMode: c.HostConfig.NetworkMode,
		}
		for _, p := range c.Ports {
			cfg.Ports = append(cfg.Ports, fmt.Sprintf("%d/%s", p.PrivatePort, p.Type))
		}
		for _, m := range c.Mounts {
			src := m.Source
			if src == "" {
				src = m.Name
			}
			if src != "" {
				cfg.Volumes = append(cfg.Volumes, src+":"+m.Destination)
			} else {
				cfg.Volumes = append(cfg.Volumes, m.Destination)
			}
		}

		if s.containerService != nil {
			if inspect, err := s.containerService.GetContainerByID(ctx, c.ID); err == nil && inspect != nil {
				cfg = inspectToContainerConfig(inspect)
			}
		}

		out[name] = cfg
	}
	return out
}

func inspectToContainerConfig(inspect *container.InspectResponse) models.ContainerConfig {
	cfg := models.ContainerConfig{}
	if inspect == nil {
		return cfg
	}
	if inspect.Config != nil {
		cfg.Image = inspect.Config.Image
		cfg.Env = append([]string(nil), inspect.Config.Env...)
		if len(inspect.Config.Labels) > 0 {
			cfg.Labels = make(map[string]string, len(inspect.Config.Labels))
			for k, v := range inspect.Config.Labels {
				cfg.Labels[k] = v
			}
		}
	}
	if inspect.HostConfig != nil {
		cfg.RestartPolicy = inspect.HostConfig.RestartPolicy.Name
		cfg.NetworkMode = string(inspect.HostConfig.NetworkMode)
		cfg.MemoryLimit = inspect.HostConfig.Memory
		if inspect.HostConfig.NanoCPUs > 0 {
			cfg.CpuLimit = float64(inspect.HostConfig.NanoCPUs) / float64(1_000_000_000)
		}

		portSet := make(map[string]struct{})
		for port := range inspect.HostConfig.PortBindings {
			portSet[port] = struct{}{}
		}
		if inspect.Config != nil {
			for port := range inspect.Config.ExposedPorts {
				portSet[string(port)] = struct{}{}
			}
		}
		for p := range portSet {
			cfg.Ports = append(cfg.Ports, p)
		}
	}
	for _, m := range inspect.Mounts {
		src := m.Source
		if src == "" {
			src = m.Name
		}
		if src != "" {
			cfg.Volumes = append(cfg.Volumes, src+":"+m.Destination)
		} else {
			cfg.Volumes = append(cfg.Volumes, m.Destination)
		}
	}
	return cfg
}
EOF
gofmt -w backend/internal/services/drift_detection_service.go && echo "gofmt OK" && go build ./internal/services/ 2>&1 | head -30