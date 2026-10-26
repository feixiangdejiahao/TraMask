cd /app && python3 - <<'PY'
import re
p='checkers/internal/astwalk/visitor.go'
s=open(p).read()
s=s.replace('''// DocCommentVisitor visits every doc-comment.
// Does not visit doc-comments for function-local definitions (types, etc).
// Also does not visit package doc-comment (file-level doc-comments).
type DocCommentVisitor interface {
	VisitDocComment(*ast.CommentGroup)
}
''', '''// DocCommentVisitor visits every doc-comment.
// Does not visit doc-comments for function-local definitions (types, etc).
// Also does not visit package doc-comment (file-level doc-comments).
type DocCommentVisitor interface {
	VisitDocComment(*ast.CommentGroup)
}

// DocLinkVisitor visits every doc-comment along with the declaration
// that the comment documents.
type DocLinkVisitor interface {
	walkerEvents
	VisitDocLink(ast.Node, *ast.CommentGroup)
}
''')
open(p,'w').write(s)

p='checkers/internal/astwalk/walker.go'
s=open(p).read()
s=s.replace('''// WalkerForDocComment returns file walker implementation for DocCommentVisitor.
func WalkerForDocComment(v DocCommentVisitor) linter.FileWalker {
	return &docCommentWalker{visitor: v}
}
''', '''// WalkerForDocComment returns file walker implementation for DocCommentVisitor.
func WalkerForDocComment(v DocCommentVisitor) linter.FileWalker {
	return &docCommentWalker{visitor: v}
}

// WalkerForDocLink returns file walker implementation for DocLinkVisitor.
func WalkerForDocLink(v DocLinkVisitor) linter.FileWalker {
	return &docLinkWalker{visitor: v}
}
''')
open(p,'w').write(s)
PY
echo done && sed -n '1,40p' checkers/internal/astwalk/visitor.go && echo "---walker---" && grep -n "WalkerForDocLink" checkers/internal/astwalk/walker.go