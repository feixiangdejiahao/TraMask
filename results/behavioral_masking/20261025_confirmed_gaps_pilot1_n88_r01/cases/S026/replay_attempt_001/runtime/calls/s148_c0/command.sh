cd /app && git add checkers/brokenDocLink_checker.go checkers/internal/astwalk/doc_link_walker.go checkers/internal/astwalk/visitor.go checkers/internal/astwalk/walker.go checkers/testdata/brokenDocLink docs/overview.md && git status && git commit -m "checkers: add brokenDocLink checker

Add a new diagnostic checker that validates doc comment symbol links.
It uses go/doc/comment to parse bracket-notation links and checks each
reference against package type information, reporting broken local,
qualified, and method/field references. Extend astwalk with a
DocLinkVisitor and corresponding walker."