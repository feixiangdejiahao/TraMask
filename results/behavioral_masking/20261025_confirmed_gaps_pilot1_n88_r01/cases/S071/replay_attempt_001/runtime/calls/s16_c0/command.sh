cd /app && cat > src/error-sanitizer.ts <<'EOF'
const URL_REGEX = /https?:\/\/\S+/g;
const EMAIL_REGEX = /\b[\w.+-]+@[\w-]+\.[\w.-]+\b/g;
const IPV4_REGEX = /\b\d{1,3}(?:\.\d{1,3}){3}\b/g;

export function sanitizeMessage(message: string): string {
  return message
    .replace(URL_REGEX, '[redacted]')
    .replace(EMAIL_REGEX, '[redacted]')
    .replace(IPV4_REGEX, '[redacted]');
}
EOF
cat src/error-sanitizer.ts