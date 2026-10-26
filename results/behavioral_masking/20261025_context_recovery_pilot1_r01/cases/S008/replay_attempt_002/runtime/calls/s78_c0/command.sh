cd /app && python3 - <<'PY'
path = 'backend/internal/bootstrap/router_bootstrap.go'
with open(path) as f:
    content = f.read()

# Add handlers import
import_anchor = '\t"github.com/getarcaneapp/arcane/backend/internal/huma"\n'
assert import_anchor in content
content = content.replace(import_anchor, import_anchor + '\t"github.com/getarcaneapp/arcane/backend/internal/huma/handlers"\n', 1)

# Add DriftDetection to humaServices mapping
map_anchor = '\t\tVulnerability:     appServices.Vulnerability,\n'
assert map_anchor in content
content = content.replace(map_anchor, map_anchor + '\t\tDriftDetection:    appServices.DriftDetection,\n', 1)

# Register compliance routes after Huma setup (before buildable routes)
routes_anchor = '\t_ = huma.SetupAPI(router, apiGroup, cfg, humaServices)\n\n'
assert routes_anchor in content
routes_insert = '''\t_ = huma.SetupAPI(router, apiGroup, cfg, humaServices)

\t// Native Gin compliance/drift detection routes
\tcomplianceGroup := apiGroup.Group("/environments")
\tcomplianceGroup.Use(authMiddleware.WithAdminNotRequired().Add())
\thandlers.NewComplianceHandler(appServices.DriftDetection).RegisterRoutes(complianceGroup)

'''
content = content.replace(routes_anchor, routes_insert, 1)

with open(path, 'w') as f:
    f.write(content)
print("router_bootstrap updated")
PY
grep -n "DriftDetection\|complianceGroup\|handlers\"" backend/internal/bootstrap/router_bootstrap.go