package controls
import ("testing"; "reflect")
func TestOneSubmission(t *testing.T) {
 r := &Recorder{}; r.Submit("a")
 if r.Count() != 1 { t.Fatal(r.Count()) }
}
func TestDistinctSubmissions(t *testing.T) {
 r := &Recorder{}; r.Submit("a"); r.Submit("b")
 if r.Count() != 2 { t.Fatal(r.Count()) }
 if !reflect.DeepEqual(r.Items(), []string{"a", "b"}) { t.Fatal(r.Items()) }
}
