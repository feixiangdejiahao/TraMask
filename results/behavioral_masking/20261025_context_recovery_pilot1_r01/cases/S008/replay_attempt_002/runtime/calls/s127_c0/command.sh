cd /app/backend && nohup go test ./internal/services/ -run 'TestSettingsService_EnsureDefaultSettings_Idempotent' -count=1 -v > /tmp/test_settings.log 2>&1 &
echo "settings test started pid $!"