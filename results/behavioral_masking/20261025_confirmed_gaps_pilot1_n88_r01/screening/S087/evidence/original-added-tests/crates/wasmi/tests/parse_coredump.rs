use wasmi::{Config, Engine, Linker, Module, Store};
use wasmparser::{
    BinaryReader, CoreDumpInstancesSection, CoreDumpModulesSection, CoreDumpSection,
    CoreDumpStackSection, DataKind, GlobalType, Parser, Payload,
};

#[test]
fn coredump_sections_and_frames() {
    let mut config = Config::default();
    config.generate_coredump(true);
    config.coredump_executable_name("myexe");
    let engine = Engine::new(&config);
    let module = Module::new(
        &engine,
        r#"
        (module
            (memory (export "mem") 1)
            (global (export "g") i32 (i32.const 7))
            (func (export "trap") (param i32) (param i64) (param f32) (param f64) (local i32)
                local.get 0
                drop
                local.get 1
                drop
                local.get 2
                drop
                local.get 3
                drop
                i32.const 99
                local.set 4
                unreachable
            )
        )
        "#,
    )
    .unwrap();
    let mut store = Store::new(&engine, ());
    let linker = Linker::new(&engine);
    let instance = linker.instantiate_and_start(&mut store, &module).unwrap();
    let func = instance.get_typed_func::<(i32, i64, f32, f64), ()>(&store, "trap").unwrap();
    let error = func.call(&mut store, (42, -7, 1.5f32, -2.25f64)).unwrap_err();
    let coredump = error.coredump().expect("coredump should be present");

    let mut saw_core = false;
    let mut saw_modules = false;
    let mut saw_instances = false;
    let mut saw_stack = false;
    let mut saw_memory = false;
    let mut saw_global = false;
    let mut saw_data = false;

    for payload in Parser::new(0).parse_all(coredump) {
        let payload = payload.unwrap();
        match payload {
            Payload::CustomSection(reader) => match reader.name() {
                "core" => {
                    saw_core = true;
                    let data = reader.data();
                    let sec = CoreDumpSection::new(BinaryReader::new(data, 0)).unwrap();
                    assert_eq!(sec.name, "myexe");
                }
                "coremodules" => {
                    saw_modules = true;
                    let data = reader.data();
                    let sec = CoreDumpModulesSection::new(BinaryReader::new(data, 0)).unwrap();
                    assert_eq!(sec.modules.len(), 1);
                }
                "coreinstances" => {
                    saw_instances = true;
                    let data = reader.data();
                    let sec = CoreDumpInstancesSection::new(BinaryReader::new(data, 0)).unwrap();
                    assert_eq!(sec.instances.len(), 1);
                    let instance = &sec.instances[0];
                    assert_eq!(instance.module_index, 0);
                    assert_eq!(instance.memories, vec![0]);
                    assert_eq!(instance.globals, vec![0]);
                }
                "corestack" => {
                    saw_stack = true;
                    let data = reader.data();
                    let sec = CoreDumpStackSection::new(BinaryReader::new(data, 0)).unwrap();
                    assert_eq!(sec.name, "main");
                    assert_eq!(sec.frames.len(), 1);
                    let frame = &sec.frames[0];
                    assert_eq!(frame.instanceidx, 0);
                    assert_eq!(frame.funcidx, 0);
                    assert_eq!(frame.codeoffset, 0);
                    assert_eq!(frame.locals.len(), 5);
                    match frame.locals[0] {
                        wasmparser::CoreDumpValue::I32(v) => assert_eq!(v, 42),
                        _ => panic!("expected i32 local"),
                    }
                    match frame.locals[1] {
                        wasmparser::CoreDumpValue::I64(v) => assert_eq!(v, -7),
                        _ => panic!("expected i64 local"),
                    }
                    match frame.locals[2] {
                        wasmparser::CoreDumpValue::F32(v) => assert_eq!(v, 1.5),
                        _ => panic!("expected f32 local"),
                    }
                    match frame.locals[3] {
                        wasmparser::CoreDumpValue::F64(v) => assert_eq!(v, -2.25),
                        _ => panic!("expected f64 local"),
                    }
                    match frame.locals[4] {
                        wasmparser::CoreDumpValue::I32(v) => assert_eq!(v, 99),
                        _ => panic!("expected local i32"),
                    }
                }
                _ => {}
            },
            Payload::MemorySection(reader) => {
                saw_memory = true;
                let mems: Vec<_> = reader.into_iter().collect::<Result<_, _>>().unwrap();
                assert_eq!(mems.len(), 1);
                let ty = mems[0];
                assert_eq!(ty.initial, 1);
                assert_eq!(ty.maximum, None);
                assert!(!ty.memory64);
            }
            Payload::GlobalSection(reader) => {
                saw_global = true;
                let globals: Vec<_> = reader
                    .into_iter()
                    .collect::<Result<Vec<_>, _>>()
                    .unwrap();
                assert_eq!(globals.len(), 1);
                let global = &globals[0];
                assert_eq!(global.ty, GlobalType {
                    content_type: wasmparser::ValType::I32,
                    mutable: false,
                    shared: false,
                });
            }
            Payload::DataSection(reader) => {
                saw_data = true;
                let data: Vec<_> = reader.into_iter().collect::<Result<_, _>>().unwrap();
                assert_eq!(data.len(), 1);
                match &data[0].kind {
                    DataKind::Active {
                        memory_index,
                        offset_expr,
                    } => {
                        assert_eq!(*memory_index, 0);
                        let mut ops = offset_expr.get_operators_reader();
                        let op = ops.read().unwrap();
                        match op {
                            wasmparser::Operator::I32Const { value } => assert_eq!(value, 0),
                            _ => panic!("expected i32.const 0 offset"),
                        }
                        assert_eq!(data[0].data.len(), 65536);
                    }
                    _ => panic!("expected active data segment"),
                }
            }
            _ => {}
        }
    }
    assert!(saw_core);
    assert!(saw_modules);
    assert!(saw_instances);
    assert!(saw_stack);
    assert!(saw_memory);
    assert!(saw_global);
    assert!(saw_data);
}
