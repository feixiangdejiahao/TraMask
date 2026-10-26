cd /app && python3 - <<'PY'
path = 'backend/internal/services/drift_detection_service.go'
with open(path) as f:
    content = f.read()

# Fix GetAllContainers 5 values
content = content.replace(
    "summaries, err := s.dockerService.GetAllContainers(ctx)",
    "summaries, _, _, _, err := s.dockerService.GetAllContainers(ctx)",
)

# Fix unused bc
content = content.replace(
    "\tfor name, bc := range baselineConfigs {\n\t\tif _, ok := liveConfigs[name]; !ok {\n\t\t\tmissingNames[name] = struct{}{}\n\t\t}\n\t}",
    "\tfor name := range baselineConfigs {\n\t\tif _, ok := liveConfigs[name]; !ok {\n\t\t\tmissingNames[name] = struct{}{}\n\t\t}\n\t}",
)

# Fix RestartPolicy conversion
content = content.replace(
    "cfg.RestartPolicy = inspect.HostConfig.RestartPolicy.Name",
    "cfg.RestartPolicy = string(inspect.HostConfig.RestartPolicy.Name)",
)

# Fix port map usage
content = content.replace(
    "\t\tportSet := make(map[string]struct{})\n\t\tfor port := range inspect.HostConfig.PortBindings {\n\t\t\tportSet[port] = struct{}{}\n\t\t}\n\t\tif inspect.Config != nil {\n\t\t\tfor port := range inspect.Config.ExposedPorts {\n\t\t\t\tportSet[string(port)] = struct{}{}\n\t\t\t}\n\t\t}\n\t\tfor p := range portSet {\n\t\t\tcfg.Ports = append(cfg.Ports, p)\n\t\t}",
    "\t\tportSet := make(map[string]struct{})\n\t\tfor port := range inspect.HostConfig.PortBindings {\n\t\t\tportSet[port.String()] = struct{}{}\n\t\t}\n\t\tif inspect.Config != nil {\n\t\t\tfor port := range inspect.Config.ExposedPorts {\n\t\t\t\tportSet[port.String()] = struct{}{}\n\t\t\t}\n\t\t}\n\t\tfor p := range portSet {\n\t\t\tcfg.Ports = append(cfg.Ports, p)\n\t\t}",
)

with open(path, 'w') as f:
    f.write(content)
print("fixed")
PY
gofmt -w backend/internal/services/drift_detection_service.go
cd /app/backend && gofmt -l internal/services/drift_detection_service.go