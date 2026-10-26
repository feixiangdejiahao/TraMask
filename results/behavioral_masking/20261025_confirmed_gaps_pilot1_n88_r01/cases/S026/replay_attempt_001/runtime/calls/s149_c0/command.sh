cd /app && git config user.email "dev@example.com" && git config user.name "Developer" && git commit -m "checkers: add brokenDocLink checker

Add a new diagnostic checker that validates doc comment symbol links.
It uses go/doc/comment to parse bracket-notation links and checks each
reference against package type information, reporting broken local,
qualified, and method/field references. Extend astwalk with a
DocLinkVisitor and corresponding walker." && git log --oneline -3