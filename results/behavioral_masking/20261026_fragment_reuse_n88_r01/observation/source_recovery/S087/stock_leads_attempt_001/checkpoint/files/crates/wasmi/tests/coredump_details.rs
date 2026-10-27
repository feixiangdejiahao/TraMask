use wasmi::{Config, Engine, Linker, Module, Store};
use wasmparser::{BinaryReader, CoreDumpModulesSection, DataKind, GlobalType, Parser, Payload};

#[test]
fn coredump_module_name_memory_and_globals() {
    let mut config = Config::default();
    config.generate_coredump(true);
    let engine = Engine::new(&config);
    let module = Module::new(
        &engine,
        r#"
        (module $my_module
            (memory (export "mem") 1)
            (global (export "const_g") i32 (i32.const 7))
            (global (export "mut_g") (mut f64) (f64.const 1.5))
            (func (export "setup_and_trap")
                i32.const 0
                i32.const 1234
                i32.store
                f64.const 2.5
                global.set 1
                unreachable
            )
        )
        "#,
    )
    .unwrap();
    let mut store = Store::new(&engine, ());
    let linker = Linker::new(&engine);
    let instance = linker.instantiate_and_start(&mut store, &module).unwrap();
    let func = instance
        .get_typed_func::<(), ()>(&store, "setup_and_trap")
        .unwrap();
    let error = func.call(&mut store, ()).unwrap_err();
    let coredump = error.coredump().expect("coredump");

    let mut module_names = None;
    let mut global_section = None;
    let mut data_section = None;
    for payload in Parser::new(0).parse_all(coredump) {
        let payload = payload.unwrap();
        match payload {
            Payload::CustomSection(reader) if reader.name() == "coremodules" => {
                module_names =
                    Some(CoreDumpModulesSection::new(BinaryReader::new(reader.data(), 0)).unwrap());
            }
            Payload::GlobalSection(reader) => {
                global_section = Some(reader.into_iter().collect::<Result<Vec<_>, _>>().unwrap());
            }
            Payload::DataSection(reader) => {
                data_section = Some(reader.into_iter().collect::<Result<Vec<_>, _>>().unwrap());
            }
            _ => {}
        }
    }

    let module_names = module_names.expect("coremodules");
    assert_eq!(module_names.modules, vec!["my_module"]);

    let globals = global_section.expect("global section");
    assert_eq!(globals.len(), 2);
    assert_eq!(
        globals[0].ty,
        GlobalType {
            content_type: wasmparser::ValType::I32,
            mutable: false,
            shared: false
        }
    );
    assert_eq!(
        globals[1].ty,
        GlobalType {
            content_type: wasmparser::ValType::F64,
            mutable: true,
            shared: false
        }
    );
    // Verify the current values of the globals at trap time.
    let mut ops = globals[0].init_expr.get_operators_reader();
    match ops.read().unwrap() {
        wasmparser::Operator::I32Const { value } => assert_eq!(value, 7),
        _ => panic!("expected i32.const 7"),
    }
    let mut ops = globals[1].init_expr.get_operators_reader();
    match ops.read().unwrap() {
        wasmparser::Operator::F64Const { value } => assert_eq!(value.bits(), 2.5f64.to_bits()),
        _ => panic!("expected f64.const 2.5"),
    }

    let data = data_section.expect("data section");
    assert_eq!(data.len(), 1);
    match &data[0].kind {
        DataKind::Active {
            memory_index,
            offset_expr,
        } => {
            assert_eq!(*memory_index, 0);
            let mut ops = offset_expr.get_operators_reader();
            match ops.read().unwrap() {
                wasmparser::Operator::I32Const { value } => assert_eq!(value, 0),
                _ => panic!("expected i32.const"),
            }
        }
        _ => panic!("expected active data segment"),
    }
    // Check that the bytes 1234 (0xD2 0x04) were written to memory at offset 0.
    assert_eq!(data[0].data[0], 0xD2);
    assert_eq!(data[0].data[1], 0x04);
}
