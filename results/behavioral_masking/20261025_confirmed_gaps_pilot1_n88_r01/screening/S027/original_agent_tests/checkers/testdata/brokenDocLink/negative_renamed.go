package checker_test

import mymath "math"

var _ = mymath.Pi

// ValidRenamed references [mymath], [mymath.Sin] and [mymath.Pi].
type ValidRenamed struct{}
