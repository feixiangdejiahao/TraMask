cat > /tmp/check_upstream.sh <<'EOF'
cd /tmp
curl -sL --max-time 20 https://raw.githubusercontent.com/bombshell-dev/clack/main/packages/core/src/prompts/autocomplete.ts -o upstream_autocomplete.ts && wc -l upstream_autocomplete.ts || echo "NO NETWORK"
EOF
bash /tmp/check_upstream.sh