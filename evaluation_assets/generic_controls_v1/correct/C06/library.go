package controls
import "errors"

// Quotient divides nonnegative integers using truncation; zero divisor is an error.
func Quotient(numerator, denominator int) (int, error) {
 if denominator == 0 { return 0, errors.New("zero divisor") }
 return numerator / denominator, nil
}
