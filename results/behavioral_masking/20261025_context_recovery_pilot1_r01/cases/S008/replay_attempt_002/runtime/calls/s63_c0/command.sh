cd /app && cat > backend/pkg/scheduler/drift_detection_job.go <<'EOF'
package scheduler

import (
	"context"
	"log/slog"

	"github.com/getarcaneapp/arcane/backend/internal/services"
	"github.com/robfig/cron/v3"
)

const DriftDetectionJobName = "drift-detection"

// DriftDetectionJob periodically runs the drift detection engine against all
// environments. It is controlled by the "driftDetectionEnabled" and
// "driftDetectionInterval" settings.
type DriftDetectionJob struct {
	driftService   *services.DriftDetectionService
	settingsService *services.SettingsService
}

// NewDriftDetectionJob creates a new DriftDetectionJob. Dependencies may be nil;
// Run degrades gracefully when they are.
func NewDriftDetectionJob(driftSvc *services.DriftDetectionService, settingsSvc *services.SettingsService) *DriftDetectionJob {
	return &DriftDetectionJob{
		driftService:   driftSvc,
		settingsService: settingsSvc,
	}
}

func (j *DriftDetectionJob) Name() string {
	return DriftDetectionJobName
}

// Schedule returns the cron expression for the job. Defaults to hourly at the
// top of the hour.
func (j *DriftDetectionJob) Schedule(ctx context.Context) string {
	const defaultSchedule = "0 0 * * * *"
	if j.settingsService == nil {
		return defaultSchedule
	}

	schedule := j.settingsService.GetStringSetting(ctx, "driftDetectionInterval", defaultSchedule)
	if schedule == "" {
		return defaultSchedule
	}

	parser := cron.NewParser(cron.Second | cron.Minute | cron.Hour | cron.Dom | cron.Month | cron.Dow)
	if _, err := parser.Parse(schedule); err != nil {
		slog.WarnContext(ctx, "Invalid cron expression for drift-detection, using default",
			"invalid_schedule", schedule, "error", err)
		return defaultSchedule
	}

	return schedule
}

// Run executes drift detection for all environments. It never panics when the
// drift service is nil and skips the run when drift detection is disabled.
func (j *DriftDetectionJob) Run(ctx context.Context) {
	if j.driftService == nil {
		slog.DebugContext(ctx, "drift detection service not configured; skipping run")
		return
	}
	if j.settingsService != nil && !j.driftService.IsEnabled(ctx) {
		slog.DebugContext(ctx, "drift detection disabled; skipping run")
		return
	}

	slog.InfoContext(ctx, "scheduled drift detection started")
	if err := j.driftService.RunAllEnvironments(ctx); err != nil {
		slog.ErrorContext(ctx, "scheduled drift detection failed", "error", err)
		return
	}
	slog.InfoContext(ctx, "scheduled drift detection completed")
}
EOF
gofmt -w backend/pkg/scheduler/drift_detection_job.go && echo OK