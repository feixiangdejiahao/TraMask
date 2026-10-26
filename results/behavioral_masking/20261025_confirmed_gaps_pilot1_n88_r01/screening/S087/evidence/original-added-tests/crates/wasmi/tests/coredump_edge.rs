use wasmi::{Config, Engine, Linker, Module, Store};
use wasmparser::{BinaryReader, CoreDumpStackSection, Parser, Payload};

fn parse_frames(coredump: &[u8]) -> Vec<(u32, u32)> {
    let mut frames = Vec::new();
    for payload in Parser::new(0).parse_all(coredump) {
        let payload = payload.unwrap();
        if let Payload::CustomSection(reader) = payload {
            if reader.name() == "corestack" {
                let sec = CoreDumpStackSection::new(BinaryReader::new(reader.data(), 0)).unwrap();
                frames = sec
                    .frames
                    .iter()
                    .map(|f| (f.instanceidx, f.funcidx))
                    .collect();
            }
        }
    }
    frames
}

#[test]
fn coredump_on_start_function_trap() {
    let mut config = Config::default();
    config.generate_coredump(true);
    let engine = Engine::new(&config);
    let module = Module::new(
        &engine,
        r#"
        (module
            (func $start
                unreachable
            )
            (start $start)
        )
        "#,
    )
    .unwrap();
    let mut store = Store::new(&engine, ());
    let linker = Linker::new(&engine);
    let error = linker
        .instantiate_and_start(&mut store, &module)
        .unwrap_err();
    let coredump = error.coredump().expect("coredump should be present");
    let frames = parse_frames(coredump);
    assert_eq!(frames.len(), 1);
    assert_eq!(frames[0].1, 0);
}

#[test]
fn coredump_recursion_has_all_frames() {
    let mut config = Config::default();
    config.generate_coredump(true);
    let engine = Engine::new(&config);
    let module = Module::new(
        &engine,
        r#"
        (module
            (func $rec (export "rec") (param i32) (result i32)
                local.get 0
                i32.const 1
                i32.sub
                local.tee 0
                if (result i32)
                    local.get 0
                    call $rec
                    i32.const 1
                    i32.add
                else
                    unreachable
                end
            )
        )
        "#,
    )
    .unwrap();
    let mut store = Store::new(&engine, ());
    let linker = Linker::new(&engine);
    let instance = linker.instantiate_and_start(&mut store, &module).unwrap();
    let func = instance.get_typed_func::<i32, i32>(&store, "rec").unwrap();
    let error = func.call(&mut store, 3).unwrap_err();
    let coredump = error.coredump().expect("coredump should be present");
    let frames = parse_frames(coredump);
    // Recurses 3 -> 2 -> 1, then 1 becomes 0 and traps, so 3 frames.
    assert_eq!(frames.len(), 3);
    // All frames belong to the same instance and function.
    assert!(frames.iter().all(|(i, f)| *i == frames[0].0 && *f == 0));
}
