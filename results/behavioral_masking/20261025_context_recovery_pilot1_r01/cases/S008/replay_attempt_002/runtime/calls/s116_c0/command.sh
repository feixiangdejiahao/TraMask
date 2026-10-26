cd /app/backend && nohup go test ./internal/database/ -run 'TestGetEmbeddedMigrationVersions_ProvidersMatch|TestMigrateDatabase' -count=1 -v > /tmp/test_db.log 2>&1 &
echo "started pid $!"