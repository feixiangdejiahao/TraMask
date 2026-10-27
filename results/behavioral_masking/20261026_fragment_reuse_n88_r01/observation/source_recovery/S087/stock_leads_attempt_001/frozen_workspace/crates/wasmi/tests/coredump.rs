use wasmi::{Config, Engine, Linker, Module, Store};

#[test]
fn coredump_generated_on_trap() {
    let mut config = Config::default();
    config.generate_coredump(true);
    config.coredump_executable_name("myexe");
    let engine = Engine::new(&config);
    let module = Module::new(
        &engine,
        r#"
        (module
            (func (export "trap") (param i32) (result i32)
                local.get 0
                local.get 0
                i32.add
                unreachable
            )
        )
        "#,
    )
    .unwrap();
    let mut store = Store::new(&engine, ());
    let linker = Linker::new(&engine);
    let instance = linker.instantiate_and_start(&mut store, &module).unwrap();
    let func = instance.get_typed_func::<i32, i32>(&store, "trap").unwrap();
    let error = func.call(&mut store, 5).unwrap_err();
    let coredump = error.coredump().expect("coredump should be present");
    assert_eq!(&coredump[..4], b"\0asm");
    assert_eq!(&coredump[4..8], &1u32.to_le_bytes());
}

#[test]
fn no_coredump_without_enabling() {
    let engine = Engine::default();
    let module = Module::new(&engine, r#"(module (func (export "trap") unreachable))"#).unwrap();
    let mut store = Store::new(&engine, ());
    let linker = Linker::new(&engine);
    let instance = linker.instantiate_and_start(&mut store, &module).unwrap();
    let func = instance.get_typed_func::<(), ()>(&store, "trap").unwrap();
    let error = func.call(&mut store, ()).unwrap_err();
    assert!(error.coredump().is_none());
}
