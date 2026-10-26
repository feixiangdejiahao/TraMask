package services

import (
	"context"
	"fmt"
	"strings"
	"testing"

	glsqlite "github.com/glebarez/sqlite"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"gorm.io/gorm"

	"github.com/getarcaneapp/arcane/backend/internal/database"
	"github.com/getarcaneapp/arcane/backend/internal/models"
)

func setupDriftDetectionTestDB(t *testing.T) *database.DB {
	t.Helper()

	dsn := fmt.Sprintf("file:%s?mode=memory&cache=shared", strings.NewReplacer("/", "_", " ", "_").Replace(t.Name()))
	db, err := gorm.Open(glsqlite.Open(dsn), &gorm.Config{})
	require.NoError(t, err)
	require.NoError(t, db.AutoMigrate(
		&models.EnvironmentBaseline{},
		&models.DriftRecord{},
		&models.ComplianceSnapshot{},
		&models.Environment{},
	))

	sqlDB, err := db.DB()
	require.NoError(t, err)
	sqlDB.SetMaxOpenConns(1)
	sqlDB.SetMaxIdleConns(1)

	return &database.DB{DB: db}
}

func newTestDriftService(t *testing.T) (*DriftDetectionService, *database.DB) {
	t.Helper()
	db := setupDriftDetectionTestDB(t)
	return NewDriftDetectionService(db, nil, nil, nil, nil, nil), db
}

func sampleContainerConfigs() map[string]models.ContainerConfig {
	return map[string]models.ContainerConfig{
		"web": {
			Image:         "nginx:latest",
			RestartPolicy: "always",
			NetworkMode:   "bridge",
			Env:           []string{"FOO=bar", "BAZ=qux"},
			Ports:         []string{"80/tcp", "443/tcp"},
			Volumes:       []string{"/data:/data"},
			Labels:        map[string]string{"app": "web", "tier": "frontend"},
			MemoryLimit:   536870912,
			CpuLimit:      0.5,
		},
	}
}

func TestCaptureBaselineFromConfigs_DeactivatesPriorActive(t *testing.T) {
	ctx := context.Background()
	svc, db := newTestDriftService(t)

	first, err := svc.CaptureBaselineFromConfigs(ctx, "env1", "first", "desc", "user1", sampleContainerConfigs())
	require.NoError(t, err)
	require.True(t, first.IsActive)
	require.Equal(t, 1, first.ContainerCount)
	require.Equal(t, "user1", first.CreatedBy)

	second, err := svc.CaptureBaselineFromConfigs(ctx, "env1", "second", "", "user2", sampleContainerConfigs())
	require.NoError(t, err)
	require.True(t, second.IsActive)

	var firstReload models.EnvironmentBaseline
	require.NoError(t, db.WithContext(ctx).First(&firstReload, "id = ?", first.ID).Error)
	assert.False(t, firstReload.IsActive)

	cfg, err := first.GetContainerConfigs()
	require.NoError(t, err)
	assert.Equal(t, "nginx:latest", cfg["web"].Image)
}

func TestGetBaseline_UnknownReturnsNil(t *testing.T) {
	ctx := context.Background()
	svc, _ := newTestDriftService(t)
	baseline, err := svc.GetBaseline(ctx, "missing")
	require.NoError(t, err)
	assert.Nil(t, baseline)
}

func TestListBaselines(t *testing.T) {
	ctx := context.Background()
	svc, _ := newTestDriftService(t)
	_, err := svc.CaptureBaselineFromConfigs(ctx, "env1", "b1", "", "u", sampleContainerConfigs())
	require.NoError(t, err)
	_, err = svc.CaptureBaselineFromConfigs(ctx, "env1", "b2", "", "u", sampleContainerConfigs())
	require.NoError(t, err)

	baselines, total, err := svc.ListBaselines(ctx, "env1", 10, 0)
	require.NoError(t, err)
	assert.Equal(t, int64(2), total)
	assert.Len(t, baselines, 2)
	assert.Equal(t, "b2", baselines[0].Name)
}

func TestSetActiveBaseline(t *testing.T) {
	ctx := context.Background()
	svc, db := newTestDriftService(t)
	first, err := svc.CaptureBaselineFromConfigs(ctx, "env1", "first", "", "u", sampleContainerConfigs())
	require.NoError(t, err)
	second, err := svc.CaptureBaselineFromConfigs(ctx, "env1", "second", "", "u", sampleContainerConfigs())
	require.NoError(t, err)

	require.NoError(t, svc.SetActiveBaseline(ctx, first.ID))

	var f, s models.EnvironmentBaseline
	require.NoError(t, db.WithContext(ctx).First(&f, "id = ?", first.ID).Error)
	require.NoError(t, db.WithContext(ctx).First(&s, "id = ?", second.ID).Error)
	assert.True(t, f.IsActive)
	assert.False(t, s.IsActive)

	assert.Error(t, svc.SetActiveBaseline(ctx, "missing"))
}

func TestDeleteBaseline_Cascades(t *testing.T) {
	ctx := context.Background()
	svc, db := newTestDriftService(t)
	baseline, err := svc.CaptureBaselineFromConfigs(ctx, "env1", "b", "", "u", sampleContainerConfigs())
	require.NoError(t, err)

	// create drift + snapshot records
	drift := models.DriftRecord{
		BaselineID:    baseline.ID,
		EnvironmentID: "env1",
		ContainerName: "web",
		DriftType:     "image_changed",
		Status:        models.DriftStatusDetected,
	}
	require.NoError(t, db.WithContext(ctx).Create(&drift).Error)
	snapshot := models.ComplianceSnapshot{
		BaselineID: baseline.ID, EnvironmentID: "env1", TotalContainers: 1, ComplianceScore: 100,
	}
	require.NoError(t, db.WithContext(ctx).Create(&snapshot).Error)

	require.NoError(t, svc.DeleteBaseline(ctx, baseline.ID))

	var count int64
	require.NoError(t, db.WithContext(ctx).Model(&models.DriftRecord{}).Where("baseline_id = ?", baseline.ID).Count(&count).Error)
	assert.Equal(t, int64(0), count)
	require.NoError(t, db.WithContext(ctx).Model(&models.ComplianceSnapshot{}).Where("baseline_id = ?", baseline.ID).Count(&count).Error)
	assert.Equal(t, int64(0), count)

	_, err = svc.GetBaseline(ctx, baseline.ID)
	require.NoError(t, err)

	require.Error(t, svc.DeleteBaseline(ctx, "missing"))
}

func TestDetectDriftFromConfigs_NoActiveBaseline(t *testing.T) {
	ctx := context.Background()
	svc, _ := newTestDriftService(t)
	_, err := svc.DetectDriftFromConfigs(ctx, "env1", sampleContainerConfigs())
	require.Error(t, err)
	assert.Contains(t, strings.ToLower(err.Error()), "no active baseline")
}

func TestDetectDriftFromConfigs_CreatesRecordsAndSnapshot(t *testing.T) {
	ctx := context.Background()
	svc, db := newTestDriftService(t)
	baseline, err := svc.CaptureBaselineFromConfigs(ctx, "env1", "b", "", "u", sampleContainerConfigs())
	require.NoError(t, err)

	live := sampleContainerConfigs()
	live["web"] = models.ContainerConfig{
		Image:         "nginx:1.27",                            // changed
		RestartPolicy: "on-failure",                            // changed
		NetworkMode:   "host",                                  // changed
		Env:           []string{"BAZ=qux", "FOO=bar", "NEW=1"}, // changed (order-indep same first two, extra)
		Ports:         []string{"8080/tcp"},                    // changed
		Volumes:       []string{"/other:/other"},               // changed
		Labels:        map[string]string{"app": "web"},         // changed (removed tier)
		MemoryLimit:   1073741824,                              // changed
		CpuLimit:      1.0,                                     // changed
	}
	live["db"] = models.ContainerConfig{Image: "postgres:16"} // added

	snapshot, err := svc.DetectDriftFromConfigs(ctx, "env1", live)
	require.NoError(t, err)
	require.NotNil(t, snapshot)
	assert.Equal(t, baseline.ID, snapshot.BaselineID)
	assert.Equal(t, 1, snapshot.TotalContainers)
	assert.Equal(t, 0, snapshot.CompliantContainers)
	assert.Equal(t, 1, snapshot.DriftedContainers)
	assert.Equal(t, 0, snapshot.MissingContainers)
	assert.Equal(t, 1, snapshot.AddedContainers)
	assert.Equal(t, 1, snapshot.CriticalDrifts)
	assert.Equal(t, 4, snapshot.HighDrifts)   // env, network, config(ports), config(volumes)
	assert.Equal(t, 4, snapshot.MediumDrifts) // restart, memory, cpu, added
	assert.Equal(t, 1, snapshot.LowDrifts)    // labels
	assert.Equal(t, 0.0, snapshot.ComplianceScore)

	var records []models.DriftRecord
	require.NoError(t, db.WithContext(ctx).Where("baseline_id = ?", baseline.ID).Find(&records).Error)
	require.Len(t, records, 10)

	byKey := map[string]models.DriftRecord{}
	for _, r := range records {
		byKey[r.DriftType+"|"+r.Field] = r
	}
	assert.Equal(t, "nginx:latest", byKey["image_changed|"].ExpectedValue)
	assert.Equal(t, "nginx:1.27", byKey["image_changed|"].ActualValue)
	assert.Equal(t, "ports", byKey["config_changed|ports"].Field)
	assert.Equal(t, "volumes", byKey["config_changed|volumes"].Field)
	assert.Equal(t, "memoryLimit", byKey["resource_changed|memoryLimit"].Field)
	assert.Equal(t, "cpuLimit", byKey["resource_changed|cpuLimit"].Field)
	assert.Equal(t, "", byKey["container_added|"].Field)

	active, err := svc.GetActiveDrifts(ctx, "env1")
	require.NoError(t, err)
	assert.Len(t, active, 10)
}

func TestDetectDrift_OrderIndependentSliceComparison(t *testing.T) {
	ctx := context.Background()
	svc, db := newTestDriftService(t)
	baselineConfigs := sampleContainerConfigs()
	baselineConfigs["web"] = models.ContainerConfig{
		Image: "nginx:latest",
		Env:   []string{"A=1", "B=2"},
		Ports: []string{"80/tcp", "443/tcp"},
	}
	baseline, err := svc.CaptureBaselineFromConfigs(ctx, "env1", "b", "", "u", baselineConfigs)
	require.NoError(t, err)

	live := sampleContainerConfigs()
	live["web"] = models.ContainerConfig{
		Image: "nginx:latest",
		Env:   []string{"B=2", "A=1"},
		Ports: []string{"443/tcp", "80/tcp"},
	}

	snapshot, err := svc.DetectDriftFromConfigs(ctx, "env1", live)
	require.NoError(t, err)
	assert.Equal(t, 1, snapshot.CompliantContainers)
	assert.Equal(t, 100.0, snapshot.ComplianceScore)

	var count int64
	require.NoError(t, db.WithContext(ctx).Model(&models.DriftRecord{}).Where("baseline_id = ?", baseline.ID).Count(&count).Error)
	assert.Zero(t, count)
}

func TestDetectDrift_AutoResolve(t *testing.T) {
	ctx := context.Background()
	svc, db := newTestDriftService(t)
	baseline, err := svc.CaptureBaselineFromConfigs(ctx, "env1", "b", "", "u", sampleContainerConfigs())
	require.NoError(t, err)

	live := sampleContainerConfigs()
	live["web"] = models.ContainerConfig{
		Image:         "nginx:1.27",
		RestartPolicy: "always",
		NetworkMode:   "bridge",
		Env:           []string{"FOO=bar", "BAZ=qux"},
		Ports:         []string{"80/tcp", "443/tcp"},
		Volumes:       []string{"/data:/data"},
		Labels:        map[string]string{"app": "web", "tier": "frontend"},
		MemoryLimit:   536870912,
		CpuLimit:      0.5,
	}
	_, err = svc.DetectDriftFromConfigs(ctx, "env1", live)
	require.NoError(t, err)

	var rec models.DriftRecord
	require.NoError(t, db.WithContext(ctx).Where("baseline_id = ?", baseline.ID).First(&rec).Error)
	assert.Equal(t, models.DriftStatusDetected, rec.Status)

	// Now clear the drift
	_, err = svc.DetectDriftFromConfigs(ctx, "env1", sampleContainerConfigs())
	require.NoError(t, err)

	require.NoError(t, db.WithContext(ctx).First(&rec, "id = ?", rec.ID).Error)
	assert.Equal(t, models.DriftStatusResolved, rec.Status)
	require.NotNil(t, rec.ResolvedAt)

	active, err := svc.GetActiveDrifts(ctx, "env1")
	require.NoError(t, err)
	assert.Empty(t, active)
}

func TestAcknowledgeAndIgnoreDrift(t *testing.T) {
	ctx := context.Background()
	svc, db := newTestDriftService(t)
	baseline, err := svc.CaptureBaselineFromConfigs(ctx, "env1", "b", "", "u", sampleContainerConfigs())
	require.NoError(t, err)

	live := sampleContainerConfigs()
	live["web"] = models.ContainerConfig{Image: "nginx:1.27"}
	_, err = svc.DetectDriftFromConfigs(ctx, "env1", live)
	require.NoError(t, err)

	var rec models.DriftRecord
	require.NoError(t, db.WithContext(ctx).Where("baseline_id = ?", baseline.ID).First(&rec).Error)

	require.NoError(t, svc.AcknowledgeDrift(ctx, rec.ID))
	require.NoError(t, db.WithContext(ctx).First(&rec, "id = ?", rec.ID).Error)
	assert.Equal(t, models.DriftStatusAcknowledged, rec.Status)

	// acknowledged drift must not auto-resolve when condition clears
	_, err = svc.DetectDriftFromConfigs(ctx, "env1", sampleContainerConfigs())
	require.NoError(t, err)
	require.NoError(t, db.WithContext(ctx).First(&rec, "id = ?", rec.ID).Error)
	assert.Equal(t, models.DriftStatusAcknowledged, rec.Status)

	require.NoError(t, svc.IgnoreDrift(ctx, rec.ID))
	require.NoError(t, db.WithContext(ctx).First(&rec, "id = ?", rec.ID).Error)
	assert.Equal(t, models.DriftStatusIgnored, rec.Status)
}

func TestGetDriftRecordsAndHistory(t *testing.T) {
	ctx := context.Background()
	svc, _ := newTestDriftService(t)
	_, err := svc.CaptureBaselineFromConfigs(ctx, "env1", "b", "", "u", sampleContainerConfigs())
	require.NoError(t, err)

	_, err = svc.DetectDriftFromConfigs(ctx, "env1", sampleContainerConfigs())
	require.NoError(t, err)

	records, total, err := svc.GetDriftRecords(ctx, "env1", 10, 0)
	require.NoError(t, err)
	assert.Len(t, records, 0)
	assert.Equal(t, int64(0), total)

	snapshots, err := svc.GetComplianceHistory(ctx, "env1", 10, 0)
	require.NoError(t, err)
	require.Len(t, snapshots, 1)
	assert.Equal(t, 100.0, snapshots[0].ComplianceScore)
}

func TestIsEnabled_NilSettings(t *testing.T) {
	ctx := context.Background()
	svc, _ := newTestDriftService(t)
	assert.True(t, svc.IsEnabled(ctx))
}

func TestRunAllEnvironments_NilDeps(t *testing.T) {
	ctx := context.Background()
	svc, _ := newTestDriftService(t)
	assert.NoError(t, svc.RunAllEnvironments(ctx))
}
