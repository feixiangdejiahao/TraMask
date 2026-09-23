package controls
import "testing"
func TestFirstQuotient(t *testing.T) {
 got, err := Quotient(12, 3)
 if err != nil || got != 4 { t.Fatal(got, err) }
}
func TestSecondQuotient(t *testing.T) {
 got, err := Quotient(8, 2)
 if err != nil || got != 4 { t.Fatal(got, err) }
}
func TestZeroDivisor(t *testing.T) {
 _, err := Quotient(12, 0)
 if err == nil { t.Fatal("expected error") }
}
