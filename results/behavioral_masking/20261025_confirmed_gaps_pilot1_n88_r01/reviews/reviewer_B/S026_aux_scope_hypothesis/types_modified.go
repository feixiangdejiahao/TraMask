package checker_test

type Base struct{ X int }

func (Base) M() {}

type Embedded struct{ Base }

type PtrEmbed struct{ *Base }

type MissingContextA struct{ Missing int }
type MissingContextB struct{ Missing int }

type MyType struct {
	Embedded
	MissingContextA
	MissingContextB
	Y int
}

func (MyType) N() {}

type Box[T any] struct{}

func (b *Box[T]) Put(x T) {}

type AliasType = MyType
