package controls

// Recorder retains every submitted item, including duplicates, in submission order.
type Recorder struct { items []string }
func (r *Recorder) Submit(value string) { r.items = append(r.items, value) }
func (r *Recorder) Count() int { return len(r.items) }
func (r *Recorder) Items() []string { return append([]string{}, r.items...) }
