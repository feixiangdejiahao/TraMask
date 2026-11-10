(module
    (func (export "preserve-local") (param i32) (result i32)
        (local.get 0)
        (local.set 0 (i32.const 0))
    )
)

(assert_return (invoke "preserve-local" (i32.const 0)) (i32.const 0))
(assert_return (invoke "preserve-local" (i32.const 1)) (i32.const 1))
(assert_return (invoke "preserve-local" (i32.const -1)) (i32.const -1))
(assert_return (invoke "preserve-local" (i32.const 42)) (i32.const 42))
(assert_return (invoke "preserve-local" (i32.const 9999)) (i32.const 9999))

(module
    ;; Regression tests for PR #831.

    (func (export "preserve-local.reinterpret.i32") (param f32) (result i32)
        (local.get 0)
        (local.set 0 (f32.const 0))
        (i32.reinterpret_f32)
    )

    (func (export "preserve-local.reinterpret.i64") (param f64) (result i64)
        (local.get 0)
        (local.set 0 (f64.const 0))
        (i64.reinterpret_f64)
    )
)

(assert_return (invoke "preserve-local.reinterpret.i32" (f32.const 0)) (i32.const 0))
(assert_return (invoke "preserve-local.reinterpret.i32" (f32.const 1)) (i32.const 1065353216))
(assert_return (invoke "preserve-local.reinterpret.i32" (f32.const -1)) (i32.const -1082130432))
(assert_return (invoke "preserve-local.reinterpret.i32" (f32.const 42)) (i32.const 1109917696))
(assert_return (invoke "preserve-local.reinterpret.i32" (f32.const 9999)) (i32.const 1176255488))

(assert_return (invoke "preserve-local.reinterpret.i64" (f64.const 0)) (i64.const 0))
(assert_return (invoke "preserve-local.reinterpret.i64" (f64.const 1)) (i64.const 4607182418800017408))
(assert_return (invoke "preserve-local.reinterpret.i64" (f64.const -1)) (i64.const -4616189618054758400))
(assert_return (invoke "preserve-local.reinterpret.i64" (f64.const 42)) (i64.const 4631107791820423168))
(assert_return (invoke "preserve-local.reinterpret.i64" (f64.const 9999)) (i64.const 4666722622711529472))

(module
    ;; Regression tests for PR #834.

    (func (export "local-tee.ignored-and-dropped") (param i32) (result i32)
        (local.get 0)
        (drop (local.tee 0 (local.get 0)))
    )
)

(assert_return (invoke "local-tee.ignored-and-dropped" (i32.const 0)) (i32.const 0))
(assert_return (invoke "local-tee.ignored-and-dropped" (i32.const 1)) (i32.const 1))
(assert_return (invoke "local-tee.ignored-and-dropped" (i32.const -1)) (i32.const -1))
(assert_return (invoke "local-tee.ignored-and-dropped" (i32.const 42)) (i32.const 42))
(assert_return (invoke "local-tee.ignored-and-dropped" (i32.const 999)) (i32.const 999))

(module
    ;; Regression tests for PR #838.

    (func (export "preserve-local.apply-noop") (param i32) (result i32)
        (local.get 0)
        (local.set 0 (i32.const 1))
        (i32.const 0)
        (i32.add)
    )
)

(assert_return (invoke "preserve-local.apply-noop" (i32.const 0)) (i32.const 0))
(assert_return (invoke "preserve-local.apply-noop" (i32.const 1)) (i32.const 1))
(assert_return (invoke "preserve-local.apply-noop" (i32.const -1)) (i32.const -1))
(assert_return (invoke "preserve-local.apply-noop" (i32.const 42)) (i32.const 42))
(assert_return (invoke "preserve-local.apply-noop" (i32.const 9999)) (i32.const 9999))

(module
    (func (export "block.preserve-locals") (param $cond i32) (param $x i32) (result i32)
        (local.get $x)
        (block
            (local.get $cond)
            (br_if 0)
            (local.set $x (i32.const 1))
        )
    )

    (func (export "if.preserve-locals") (param $cond i32) (param $x i32) (result i32)
        (local.get $x)
        (if
            (i32.eqz (local.get $cond))
            (then
                (local.set $x (i32.const 1))
            )
        )
    )
)

;; block

(assert_return (invoke "block.preserve-locals" (i32.const 0) (i32.const 0)) (i32.const 0))
(assert_return (invoke "block.preserve-locals" (i32.const 0) (i32.const 1)) (i32.const 1))
(assert_return (invoke "block.preserve-locals" (i32.const 0) (i32.const -1)) (i32.const -1))
(assert_return (invoke "block.preserve-locals" (i32.const 0) (i32.const 42)) (i32.const 042))
(assert_return (invoke "block.preserve-locals" (i32.const 0) (i32.const 999)) (i32.const 999))
(assert_return (invoke "block.preserve-locals" (i32.const 1) (i32.const 0)) (i32.const 0))
(assert_return (invoke "block.preserve-locals" (i32.const 1) (i32.const 1)) (i32.const 1))
(assert_return (invoke "block.preserve-locals" (i32.const 1) (i32.const -1)) (i32.const -1))
(assert_return (invoke "block.preserve-locals" (i32.const 1) (i32.const 42)) (i32.const 042))
(assert_return (invoke "block.preserve-locals" (i32.const 1) (i32.const 999)) (i32.const 999))

;; if

(assert_return (invoke "if.preserve-locals" (i32.const 0) (i32.const 0)) (i32.const 0))
(assert_return (invoke "if.preserve-locals" (i32.const 0) (i32.const 1)) (i32.const 1))
(assert_return (invoke "if.preserve-locals" (i32.const 0) (i32.const -1)) (i32.const -1))
(assert_return (invoke "if.preserve-locals" (i32.const 0) (i32.const 42)) (i32.const 042))
(assert_return (invoke "if.preserve-locals" (i32.const 0) (i32.const 999)) (i32.const 999))
(assert_return (invoke "if.preserve-locals" (i32.const 1) (i32.const 0)) (i32.const 0))
(assert_return (invoke "if.preserve-locals" (i32.const 1) (i32.const 1)) (i32.const 1))
(assert_return (invoke "if.preserve-locals" (i32.const 1) (i32.const -1)) (i32.const -1))
(assert_return (invoke "if.preserve-locals" (i32.const 1) (i32.const 42)) (i32.const 042))
(assert_return (invoke "if.preserve-locals" (i32.const 1) (i32.const 999)) (i32.const 999))

(module
    (func (export "block.nested") (param i32 i32) (param $c0 i32) (param $c1 i32) (result i32 i32)
        (local.get 0) ;; 1st return value
        (local.get 1) ;; 2nd return value
        (block
            (br_if 0 (local.get $c0))
            (local.set 0 (i32.const 10)) ;; conditionally overwrites (local 0) on stack
            (block
                (br_if 1 (local.get $c1))
                (local.set 1 (i32.const 20)) ;; conditionally overwrites (local 1) on stack
            )
        )
    )
)
(assert_return
    (invoke "block.nested" (i32.const 10) (i32.const 20) (i32.const 0) (i32.const 0))
    (i32.const 10) (i32.const 20)
)
(assert_return
    (invoke "block.nested" (i32.const 10) (i32.const 20) (i32.const 0) (i32.const 1))
    (i32.const 10) (i32.const 20)
)
(assert_return
    (invoke "block.nested" (i32.const 10) (i32.const 20) (i32.const 1) (i32.const 0))
    (i32.const 10) (i32.const 20)
)
(assert_return
    (invoke "block.nested" (i32.const 10) (i32.const 20) (i32.const 1) (i32.const 1))
    (i32.const 10) (i32.const 20)
)

(module
    (func (export "if.nested") (param i32 i32) (param $c0 i32) (param $c1 i32) (result i32 i32)
        local.get 0 ;; 1st return value
        local.get 1 ;; 2nd return value
        (if (local.get $c0)
            (then
                (local.set 0 (i32.const 10)) ;; overwrites (local 0) conditionally
                (if (local.get $c1)
                    (then
                        (local.set 1 (i32.const 20)) ;; overwrites (local 1) conditionally
                    )
                )
            )
        )
    )
)
(assert_return
    (invoke "if.nested" (i32.const 10) (i32.const 20) (i32.const 0) (i32.const 0))
    (i32.const 10) (i32.const 20)
)
(assert_return
    (invoke "if.nested" (i32.const 10) (i32.const 20) (i32.const 0) (i32.const 1))
    (i32.const 10) (i32.const 20)
)
(assert_return
    (invoke "if.nested" (i32.const 10) (i32.const 20) (i32.const 1) (i32.const 0))
    (i32.const 10) (i32.const 20)
)
(assert_return
    (invoke "if.nested" (i32.const 10) (i32.const 20) (i32.const 1) (i32.const 1))
    (i32.const 10) (i32.const 20)
)

(module
    (func (export "expr.block.rhs") (param $cond i32) (param $x i32) (param $y0 i32) (param $y1 i32) (result i32)
        (i32.add
            (local.get $x)
            (block $exit (result i32)
                (drop
                    (br_if $exit
                        (local.get $y0) ;; br_if return value
                        (i32.eqz (local.get $cond)) ;; br_if condition
                    )
                )
                (local.set $x (i32.const 0x7FFF_FFFF)) ;; x = i32::MAX
                (local.get $y1)
            )
        )
    )
)
(assert_return
    (invoke "expr.block.rhs" (i32.const 0) (i32.const 3) (i32.const 5) (i32.const 7))
    (i32.const 8)
)
(assert_return
    (invoke "expr.block.rhs" (i32.const 0) (i32.const 5) (i32.const 7) (i32.const 11))
    (i32.const 12)
)
(assert_return
    (invoke "expr.block.rhs" (i32.const 1) (i32.const 3) (i32.const 5) (i32.const 7))
    (i32.const 10)
)
(assert_return
    (invoke "expr.block.rhs" (i32.const 1) (i32.const 5) (i32.const 7) (i32.const 11))
    (i32.const 16)
)

(module
    (func (export "expr.if.rhs") (param $cond i32) (param $x i32) (param $y0 i32) (param $y1 i32) (result i32)
        (i32.add
            (local.get $x)
            (if (result i32) (i32.eqz (local.get $cond))
                (then
                    (local.set $x (i32.const 0x7FFF_FFFF)) ;; x = i32::MAX
                    (local.get $y0)
                )
                (else
                    (local.get $y1)
                )
            )
        )
    )
)
(assert_return
    (invoke "expr.if.rhs" (i32.const 0) (i32.const 3) (i32.const 5) (i32.const 7))
    (i32.const 8)
)
(assert_return
    (invoke "expr.if.rhs" (i32.const 0) (i32.const 5) (i32.const 7) (i32.const 11))
    (i32.const 12)
)
(assert_return
    (invoke "expr.if.rhs" (i32.const 1) (i32.const 3) (i32.const 5) (i32.const 7))
    (i32.const 10)
)
(assert_return
    (invoke "expr.if.rhs" (i32.const 1) (i32.const 5) (i32.const 7) (i32.const 11))
    (i32.const 16)
)
