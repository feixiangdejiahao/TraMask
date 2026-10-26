package checker_test

type Base struct{ X int }

func (Base) M() {}

type Embedded struct{ Base }

type PtrEmbed struct{ *Base }

type MyType struct {
	Embedded
	Y int
}

func (MyType) N() {}

type Box[T any] struct{}

func (b *Box[T]) Put(x T) {}

type AliasType = MyType
