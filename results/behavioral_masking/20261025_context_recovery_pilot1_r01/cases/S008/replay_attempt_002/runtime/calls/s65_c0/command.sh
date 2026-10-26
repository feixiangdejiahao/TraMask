cd /app && cat > backend/internal/huma/handlers/compliance.go <<'EOF'
package handlers

import (
	"net/http"
	"strconv"
	"strings"

	"github.com/getarcaneapp/arcane/backend/internal/models"
	"github.com/getarcaneapp/arcane/backend/internal/services"
	"github.com/gin-gonic/gin"
)

// ComplianceHandler exposes the drift detection engine via native Gin routes.
type ComplianceHandler struct {
	driftService *services.DriftDetectionService
}

// NewComplianceHandler creates a new ComplianceHandler.
func NewComplianceHandler(svc *services.DriftDetectionService) *ComplianceHandler {
	return &ComplianceHandler{driftService: svc}
}

// RegisterRoutes registers all compliance routes under /environments/:id/compliance.
func (h *ComplianceHandler) RegisterRoutes(group *gin.RouterGroup) {
	compliance := group.Group("/environments/:id/compliance")
	{
		compliance.POST("/baselines", h.CreateBaseline)
		compliance.GET("/baselines", h.ListBaselines)
		compliance.GET("/baselines/:baselineId", h.GetBaseline)
		compliance.POST("/baselines/:baselineId/activate", h.ActivateBaseline)
		compliance.DELETE("/baselines/:baselineId", h.DeleteBaseline)
		compliance.POST("/detect", h.Detect)
		compliance.GET("/drifts", h.ListDrifts)
		compliance.POST("/drifts/:driftId/acknowledge", h.AcknowledgeDrift)
		compliance.POST("/drifts/:driftId/ignore", h.IgnoreDrift)
		compliance.GET("/history", h.GetHistory)
	}
}

type createBaselineRequest struct {
	Name        string                            `json:"name"`
	Description string                            `json:"description"`
	Containers  map[string]models.ContainerConfig `json:"containers"`
}

type detectRequest struct {
	Containers map[string]models.ContainerConfig `json:"containers"`
}

func (h *ComplianceHandler) CreateBaseline(c *gin.Context) {
	var req createBaselineRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"success": false, "error": "invalid request body"})
		return
	}

	envID := c.Param("id")
	userID := c.GetHeader("X-User-ID")
	if userID == "" {
		userID = c.GetString("userID")
	}

	baseline, err := h.driftService.CaptureBaselineFromConfigs(
		c.Request.Context(),
		envID,
		req.Name,
		req.Description,
		userID,
		req.Containers,
	)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"success": false, "error": err.Error()})
		return
	}

	c.JSON(http.StatusCreated, gin.H{"success": true, "data": baseline})
}

func (h *ComplianceHandler) ListBaselines(c *gin.Context) {
	limit, offset := parseCompliancePagination(c)
	baselines, total, err := h.driftService.ListBaselines(c.Request.Context(), c.Param("id"), limit, offset)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"success": false, "error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": baselines, "total": total})
}

func (h *ComplianceHandler) GetBaseline(c *gin.Context) {
	baseline, err := h.driftService.GetBaseline(c.Request.Context(), c.Param("baselineId"))
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"success": false, "error": err.Error()})
		return
	}
	if baseline == nil {
		c.JSON(http.StatusNotFound, gin.H{"success": false, "error": "baseline not found"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": baseline})
}

func (h *ComplianceHandler) ActivateBaseline(c *gin.Context) {
	if err := h.driftService.SetActiveBaseline(c.Request.Context(), c.Param("baselineId")); err != nil {
		if strings.Contains(err.Error(), "not found") {
			c.JSON(http.StatusNotFound, gin.H{"success": false, "error": err.Error()})
			return
		}
		c.JSON(http.StatusBadRequest, gin.H{"success": false, "error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": gin.H{"message": "baseline activated"}})
}

func (h *ComplianceHandler) DeleteBaseline(c *gin.Context) {
	if err := h.driftService.DeleteBaseline(c.Request.Context(), c.Param("baselineId")); err != nil {
		if strings.Contains(err.Error(), "not found") {
			c.JSON(http.StatusNotFound, gin.H{"success": false, "error": err.Error()})
			return
		}
		c.JSON(http.StatusBadRequest, gin.H{"success": false, "error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": gin.H{"message": "baseline deleted"}})
}

func (h *ComplianceHandler) Detect(c *gin.Context) {
	var req detectRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"success": false, "error": "invalid request body"})
		return
	}

	snapshot, err := h.driftService.DetectDriftFromConfigs(c.Request.Context(), c.Param("id"), req.Containers)
	if err != nil {
		if strings.Contains(strings.ToLower(err.Error()), "no active baseline") {
			c.JSON(http.StatusBadRequest, gin.H{"success": false, "error": err.Error()})
			return
		}
		c.JSON(http.StatusInternalServerError, gin.H{"success": false, "error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": snapshot})
}

func (h *ComplianceHandler) ListDrifts(c *gin.Context) {
	limit, offset := parseCompliancePagination(c)
	records, total, err := h.driftService.GetDriftRecords(c.Request.Context(), c.Param("id"), limit, offset)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"success": false, "error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": records, "total": total})
}

func (h *ComplianceHandler) AcknowledgeDrift(c *gin.Context) {
	if err := h.driftService.AcknowledgeDrift(c.Request.Context(), c.Param("driftId")); err != nil {
		if strings.Contains(err.Error(), "not found") {
			c.JSON(http.StatusNotFound, gin.H{"success": false, "error": err.Error()})
			return
		}
		c.JSON(http.StatusBadRequest, gin.H{"success": false, "error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": gin.H{"message": "drift acknowledged"}})
}

func (h *ComplianceHandler) IgnoreDrift(c *gin.Context) {
	if err := h.driftService.IgnoreDrift(c.Request.Context(), c.Param("driftId")); err != nil {
		if strings.Contains(err.Error(), "not found") {
			c.JSON(http.StatusNotFound, gin.H{"success": false, "error": err.Error()})
			return
		}
		c.JSON(http.StatusBadRequest, gin.H{"success": false, "error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": gin.H{"message": "drift ignored"}})
}

func (h *ComplianceHandler) GetHistory(c *gin.Context) {
	limit, offset := parseCompliancePagination(c)
	snapshots, err := h.driftService.GetComplianceHistory(c.Request.Context(), c.Param("id"), limit, offset)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"success": false, "error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": snapshots})
}

func parseCompliancePagination(c *gin.Context) (int, int) {
	limit := 20
	offset := 0
	if raw := c.Query("limit"); raw != "" {
		if parsed, err := strconv.Atoi(raw); err == nil {
			limit = parsed
		}
	}
	if raw := c.Query("offset"); raw != "" {
		if parsed, err := strconv.Atoi(raw); err == nil {
			offset = parsed
		}
	}
	if limit < -1 {
		limit = 20
	}
	return limit, offset
}
EOF
gofmt -w backend/internal/huma/handlers/compliance.go && echo OK