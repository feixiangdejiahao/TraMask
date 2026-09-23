package controls
import "testing"
func TestAdd(t *testing.T) {
 c := &Counter{Value: 2}; c.Add(3)
 if c.Value != 5 { t.Fatal(c.Value) }
}
func TestDouble(t *testing.T) {
 c := &Counter{Value: 2}; c.Double()
 if c.Value != 4 { t.Fatal(c.Value) }
}
func TestZeroAdd(t *testing.T) {
 c := &Counter{Value: 2}; c.Add(0)
 if c.Value != 2 { t.Fatal(c.Value) }
}
