use wasmi::{Caller, Config, Engine, Linker, Module, Store};
use wasmparser::{BinaryReader, CoreDumpStackSection, Parser, Payload};

#[test]
fn coredump_includes_outer_frames_on_reentrancy() {
    let mut config = Config::default();
    config.generate_coredump(true);
    let engine = Engine::new(&config);

    // Inner module: traps when called.
    let inner_module = Module::new(
        &engine,
        r#"
        (module
            (func (export "inner") (param i32)
                local.get 0
                unreachable
            )
        )
        "#,
    )
    .unwrap();
    let mut store = Store::new(&engine, ());
    let inner_linker = Linker::new(&engine);
    let inner_instance = inner_linker
        .instantiate_and_start(&mut store, &inner_module)
        .unwrap();
    let inner = inner_instance
        .get_typed_func::<i32, ()>(&store, "inner")
        .unwrap();

    // Outer module: calls a host function which re-enters Wasm.
    let outer_module = Module::new(
        &engine,
        r#"
        (module
            (import "host" "callback" (func $callback (param i32)))
            (func (export "outer") (param i32)
                local.get 0
                call $callback
            )
        )
        "#,
    )
    .unwrap();

    let mut linker = Linker::new(&engine);
    let inner = std::sync::Arc::new(inner);
    let inner2 = inner.clone();
    let _ = linker.func_wrap("host", "callback", move |caller: Caller<'_, ()>, value: i32| {
        let inner = inner2.clone();
        inner.call(caller, value).map(|_| ())
    });
    let outer_instance = linker
        .instantiate_and_start(&mut store, &outer_module)
        .unwrap();
    let outer = outer_instance
        .get_typed_func::<i32, ()>(&store, "outer")
        .unwrap();

    let error = outer.call(&mut store, 5).unwrap_err();
    let coredump = error.coredump().expect("coredump should be present");
    let mut stack = None;
    for payload in Parser::new(0).parse_all(coredump) {
        let payload = payload.unwrap();
        if let Payload::CustomSection(reader) = payload {
            if reader.name() == "corestack" {
                stack = Some(
                    CoreDumpStackSection::new(BinaryReader::new(reader.data(), 0)).unwrap(),
                );
            }
        }
    }
    let stack = stack.expect("corestack section");
    assert_eq!(stack.frames.len(), 2, "expected inner and outer frames");
    // Youngest (inner) frame first, then outer frame.
    assert_ne!(
        stack.frames[0].instanceidx, stack.frames[1].instanceidx,
        "inner and outer frames should belong to different instances"
    );
    assert_eq!(stack.frames[0].funcidx, 0);
    assert_eq!(stack.frames[1].funcidx, 1);
}
