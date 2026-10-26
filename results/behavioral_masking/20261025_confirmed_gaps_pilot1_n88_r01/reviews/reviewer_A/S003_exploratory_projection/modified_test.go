package bootstrap

import (
 "bytes"
 "context"
 "encoding/json"
 "fmt"
 "net/http"
 "net/http/httptest"
 "strings"
 "testing"
 glsqlite "github.com/glebarez/sqlite"
 "github.com/stretchr/testify/assert"
 "github.com/stretchr/testify/require"
 "gorm.io/gorm"
 "github.com/getarcaneapp/arcane/backend/internal/config"
 "github.com/getarcaneapp/arcane/backend/internal/database"
 "github.com/getarcaneapp/arcane/backend/internal/huma/handlers"
 "github.com/getarcaneapp/arcane/backend/internal/models"
 "github.com/getarcaneapp/arcane/backend/internal/services"
 "github.com/gin-gonic/gin"
)

var _ = handlers.NewComplianceHandler

func setupComplianceTestRouter(t *testing.T) *gin.Engine {
	t.Helper()
	gin.SetMode(gin.TestMode)

	dsn := fmt.Sprintf("file:%s?mode=memory&cache=shared", strings.NewReplacer("/", "_", " ", "_").Replace(t.Name()))
	db, err := gorm.Open(glsqlite.Open(dsn), &gorm.Config{})
	require.NoError(t, err)
	require.NoError(t, db.AutoMigrate(
		&models.EnvironmentBaseline{},
		&models.DriftRecord{},
		&models.ComplianceSnapshot{},
	))

	sqlDB, err := db.DB()
	require.NoError(t, err)
	sqlDB.SetMaxOpenConns(1)
	sqlDB.SetMaxIdleConns(1)

	svc := services.NewDriftDetectionService(&database.DB{DB: db}, nil, nil, nil, nil, nil)
	router := gin.New()
	// Obtain the compliance route topology from actual production bootstrap.
 // Replay terminal endpoint handlers into the original auth-free test harness.
 // Auth/env-proxy middleware is outside this localized routing operation.
 require.NoError(t, db.AutoMigrate(&models.SettingVariable{}))
 appDB := &database.DB{DB: db}
 settingsSvc, err := services.NewSettingsService(context.Background(), appDB)
 require.NoError(t, err)
 appServices := &Services{Settings: settingsSvc, DriftDetection: svc}
 assembled, _ := setupRouter(context.Background(), &config.Config{AgentMode: true}, appServices)
 for _, route := range assembled.Routes() {
  if strings.Contains(route.Path, "/compliance/") {
   router.Handle(route.Method, route.Path, route.HandlerFunc)
  }
 }
	return router
}

func doComplianceRequest(t *testing.T, router *gin.Engine, method, path, body string, userID string) *httptest.ResponseRecorder {
	t.Helper()
	var req *http.Request
	if body != "" {
		req = httptest.NewRequest(method, path, bytes.NewBufferString(body))
	} else {
		req = httptest.NewRequest(method, path, nil)
	}
	req.Header.Set("Content-Type", "application/json")
	if userID != "" {
		req.Header.Set("X-User-ID", userID)
	}
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)
	return w
}

func TestComplianceRoutes(t *testing.T) {
	router := setupComplianceTestRouter(t)
	// Create baseline
	body := `{
		"name":"prod",
		"description":"prod baseline",
		"containers":{"web":{"image":"nginx:latest","restartPolicy":"always","networkMode":"bridge","env":["A=1"],"ports":["80/tcp"],"volumes":["/data:/data"],"labels":{"app":"web"},"memoryLimit":536870912,"cpuLimit":0.5}}
	}`
	w := doComplianceRequest(t, router, http.MethodPost, "/api/environments/env1/compliance/baselines", body, "user-42")
	require.Equal(t, http.StatusCreated, w.Code, w.Body.String())

	var createResp struct {
		Success bool `json:"success"`
		Data    struct {
			ID             string `json:"id"`
			Name           string `json:"name"`
			CreatedBy      string `json:"createdBy"`
			IsActive       bool   `json:"isActive"`
			ContainerCount int    `json:"containerCount"`
		} `json:"data"`
	}
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &createResp))
	assert.True(t, createResp.Success)
	assert.Equal(t, "prod", createResp.Data.Name)
	assert.Equal(t, "user-42", createResp.Data.CreatedBy)
	assert.True(t, createResp.Data.IsActive)
	assert.Equal(t, 1, createResp.Data.ContainerCount)
}
