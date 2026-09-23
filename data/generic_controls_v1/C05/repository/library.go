package controls

// Counter applies integer operations in invocation order.
type Counter struct { Value int }
func (c *Counter) Add(amount int) { c.Value += amount }
func (c *Counter) Double() { c.Value *= 2 }
