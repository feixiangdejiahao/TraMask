cd /app && cat > backend/pkg/scheduler/drift_detection_job_test.go <<'EOF'
package scheduler

import (
	"context"
	"testing"

	glsqlite "github.com/glebarez/sqlite"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"gorm.io/gorm"

	"github.com/getarcaneapp/arcane/backend/internal/database"
	"github.com/getarcaneapp/arcane/backend/internal/models"
	"github.com/getarcaneapp/arcane/backend/internal/services"
)

func TestDriftDetectionJob_Name(t *testing.T) {
	job := NewDriftDetectionJob(nil, nil)
	assert.Equal(t, "drift-detection", job.Name())
}

func TestDriftDetectionJob_Schedule_DefaultWhenNilSettings(t *testing.T) {
	job := NewDriftDetectionJob(nil, nil)
	assert.Equal(t, "0 0 * * * *", job.Schedule(context.Background()))
}

func TestDriftDetectionJob_Run_NoPanicWithNilServices(t *testing.T) {
	job := NewDriftDetectionJob(nil, nil)
	require.NotPanics(t, func() {
		job.Run(context.Background())
	})
}

func TestDriftDetectionJob_Run_SkipsWhenDisabled(t *testing.T) {
	db, err := gorm.Open(glsqlite.Open(":memory:"), &gorm.Config{})
	require.NoError(t, err)
	require.NoError(t, db.AutoMigrate(&models.SettingVariable{}))
	appDB := &database.DB{DB: db}

	settingsSvc, err := services.NewSettingsService(context.Background(), appDB)
	require.NoError(t, err)
	require.NoError(t, settingsSvc.SetBoolSetting(context.Background(), "driftDetectionEnabled", false))

	driftSvc := services.NewDriftDetectionService(nil, nil, nil, nil, settingsSvc, nil)
	job := NewDriftDetectionJob(driftSvc, settingsSvc)

	require.NotPanics(t, func() {
		job.Run(context.Background())
	})
}
EOF
cd /app/backend && gofmt -w pkg/scheduler/drift_detection_job_test.go && echo OK