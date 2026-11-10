//! Tests for opt-in coredump generation.

use wasmi::{Caller, Config, Engine, Error, Func, Linker, Module, Store, TrapCode};

/// A minimal Wasm binary reader sufficient for the coredump tests.
struct Reader<'a> {
    bytes: &'a [u8],
    pos: usize,
}

impl<'a> Reader<'a> {
    fn new(bytes: &'a [u8]) -> Self {
        Self { bytes, pos: 0 }
    }

    fn new_wasm(bytes: &'a [u8]) -> Self {
        Self { bytes, pos: 8 } // skip magic and version
    }

    fn u8(&mut self) -> u8 {
        let value = self.bytes[self.pos];
        self.pos += 1;
        value
    }

    fn u32(&mut self) -> u32 {
        let mut result = 0u32;
        let mut shift = 0;
        loop {
            let byte = self.u8();
            result |= u32::from(byte & 0x7f) << shift;
            if byte & 0x80 == 0 {
                return result;
            }
            shift += 7;
        }
    }

    fn bytes(&mut self, len: usize) -> &'a [u8] {
        let value = &self.bytes[self.pos..self.pos + len];
        self.pos += len;
        value
    }

    fn name(&mut self) -> &'a str {
        let len = self.u32() as usize;
        core::str::from_utf8(self.bytes(len)).unwrap()
    }

    fn custom_section(&mut self) -> (&'a str, &'a [u8]) {
        assert_eq!(self.u8(), 0);
        let size = self.u32() as usize;
        let start = self.pos;
        let name = self.name();
        let payload = self.bytes(size - (self.pos - start));
        (name, payload)
    }

    fn skip_section(&mut self) {
        let _id = self.u8();
        let size = self.u32() as usize;
        self.pos += size;
    }
}

/// Returns `(name, payload)` pairs of all custom sections.
fn custom_sections(wasm: &[u8]) -> Vec<(String, Vec<u8>)> {
    let mut reader = Reader::new_wasm(wasm);
    let mut sections = Vec::new();
    while reader.pos < wasm.len() {
        let id = wasm[reader.pos];
        if id == 0 {
            let (name, payload) = reader.custom_section();
            sections.push((name.to_string(), payload.to_vec()));
        } else {
            reader.skip_section();
        }
    }
    sections
}

/// Parses the number of frames in the `"corestack"` section.
fn corestack_frame_count(wasm: &[u8]) -> usize {
    let sections = custom_sections(wasm);
    let (_, payload) = sections
        .iter()
        .find(|(name, _)| name == "corestack")
        .expect("must have corestack section");
    let mut reader = Reader::new(payload);
    assert_eq!(reader.u8(), 0x00);
    let _thread_name = reader.name();
    let count = reader.u32() as usize;
    for _ in 0..count {
        assert_eq!(reader.u8(), 0x00);
        let _instance_index = reader.u32();
        let _func_index = reader.u32();
        let _code_offset = reader.u32();
        // locals
        let locals = reader.u32() as usize;
        for _ in 0..locals {
            let tag = reader.u8();
            match tag {
                0x7F => {
                    let _ = reader.u32(); // i32 LEB (u32 parse works for small negatives)
                }
                0x7E => {
                    let _ = reader.u32();
                }
                0x7D => {
                    let _ = reader.bytes(4);
                }
                0x7C => {
                    let _ = reader.bytes(8);
                }
                0x01 => {}
                _ => panic!("unexpected value tag: {tag:#x}"),
            }
        }
        // operands
        let operands = reader.u32() as usize;
        for _ in 0..operands {
            let tag = reader.u8();
            match tag {
                0x7F => {
                    let _ = reader.u32();
                }
                0x7E => {
                    let _ = reader.u32();
                }
                0x7D => {
                    let _ = reader.bytes(4);
                }
                0x7C => {
                    let _ = reader.bytes(8);
                }
                0x01 => {}
                _ => panic!("unexpected value tag: {tag:#x}"),
            }
        }
    }
    count
}

/// Parses the executable name from the `"core"` section.
fn core_executable_name(wasm: &[u8]) -> String {
    let sections = custom_sections(wasm);
    let (_, payload) = sections
        .iter()
        .find(|(name, _)| name == "core")
        .expect("must have core section");
    let mut reader = Reader::new(payload);
    assert_eq!(reader.u8(), 0x00);
    reader.name().to_string()
}

#[test]
fn coredump_generated_on_trap() {
    let mut config = Config::default();
    config
        .generate_coredump(true)
        .coredump_executable_name("myexe");
    let engine = Engine::new(&config);
    let mut store = Store::new(&engine, ());
    let module = Module::new(&engine, r#"(module (func (export "boom") unreachable))"#).unwrap();
    let instance = Linker::new(&engine)
        .instantiate_and_start(&mut store, &module)
        .unwrap();
    let func = instance.get_typed_func::<(), ()>(&store, "boom").unwrap();
    let error = func.call(&mut store, ()).unwrap_err();
    assert_eq!(error.as_trap_code(), Some(TrapCode::UnreachableCodeReached));
    let coredump = error.coredump().expect("must have coredump");
    assert_eq!(&coredump[..4], &[0x00, 0x61, 0x73, 0x6d]);
    assert_eq!(&coredump[4..8], &[0x01, 0x00, 0x00, 0x00]);
    let names: Vec<String> = custom_sections(coredump)
        .into_iter()
        .map(|(name, _)| name)
        .collect();
    assert!(names.contains(&"core".to_string()));
    assert!(names.contains(&"coremodules".to_string()));
    assert!(names.contains(&"coreinstances".to_string()));
    assert!(names.contains(&"corestack".to_string()));
    assert_eq!(core_executable_name(coredump), "myexe");
    assert_eq!(corestack_frame_count(coredump), 1);
}

#[test]
fn no_coredump_when_disabled() {
    let engine = Engine::default();
    let mut store = Store::new(&engine, ());
    let module = Module::new(&engine, r#"(module (func (export "boom") unreachable))"#).unwrap();
    let instance = Linker::new(&engine)
        .instantiate_and_start(&mut store, &module)
        .unwrap();
    let func = instance.get_typed_func::<(), ()>(&store, "boom").unwrap();
    let error = func.call(&mut store, ()).unwrap_err();
    assert!(error.coredump().is_none());
}

#[test]
fn coredump_has_frames_across_reenrant_host_call() {
    let mut config = Config::default();
    config.generate_coredump(true);
    let engine = Engine::new(&config);
    let mut store = Store::new(&engine, ());
    let host_fn = Func::wrap(
        &mut store,
        |mut caller: Caller<()>, _: i32| -> Result<i32, Error> {
            let wasm_fn = caller
                .get_export("inner")
                .and_then(wasmi::Extern::into_func)
                .unwrap()
                .typed::<i32, i32>(&caller)
                .unwrap();
            wasm_fn.call(&mut caller, 42)
        },
    );
    let mut linker = Linker::new(&engine);
    linker.define("env", "host_fn", host_fn).unwrap();
    let module = Module::new(
        &engine,
        r#"
        (module
            (import "env" "host_fn" (func $host_fn (param i32) (result i32)))
            (func (export "outer") (param i32) (result i32)
                (call $host_fn (local.get 0))
            )
            (func (export "inner") (param i32) (result i32)
                unreachable
            )
        )
        "#,
    )
    .unwrap();
    let instance = linker.instantiate_and_start(&mut store, &module).unwrap();
    let func = instance
        .get_typed_func::<i32, i32>(&store, "outer")
        .unwrap();
    let error = func.call(&mut store, 1).unwrap_err();
    let coredump = error.coredump().expect("must have coredump");
    // The corestack must contain both the inner (trap site) and outer frames.
    assert_eq!(corestack_frame_count(coredump), 2);
    // Frames are ordered youngest (trap site) to oldest (entry point).
    // Module funcs: host_fn=0, outer=1, inner=2.
    assert_eq!(corestack_func_indices(coredump), vec![2, 1]);
    // Both execution levels use the same module instance.
    assert_eq!(coreinstances_count(coredump), 1);
    // The executable name defaults to an empty string.
    assert_eq!(core_executable_name(coredump), "");
}

/// Parses the locals of the first frame in the `"corestack"` section.
fn corestack_first_frame_locals(wasm: &[u8]) -> Vec<i64> {
    let sections = custom_sections(wasm);
    let (_, payload) = sections
        .iter()
        .find(|(name, _)| name == "corestack")
        .expect("must have corestack section");
    let mut reader = Reader::new(payload);
    assert_eq!(reader.u8(), 0x00);
    let _thread_name = reader.name();
    let count = reader.u32() as usize;
    assert!(count >= 1);
    assert_eq!(reader.u8(), 0x00);
    let _instance_index = reader.u32();
    let _func_index = reader.u32();
    let _code_offset = reader.u32();
    let locals = reader.u32() as usize;
    let mut values = Vec::new();
    for _ in 0..locals {
        let tag = reader.u8();
        match tag {
            0x7F => values.push(i64::from(reader.u32() as i32)),
            0x7E => values.push(reader.u32() as i64),
            0x7D => {
                let _ = reader.bytes(4);
                values.push(0);
            }
            0x7C => {
                let _ = reader.bytes(8);
                values.push(0);
            }
            0x01 => values.push(i64::MIN),
            _ => panic!("unexpected value tag: {tag:#x}"),
        }
    }
    values
}

#[test]
fn coredump_includes_memory_global_and_locals() {
    let mut config = Config::default();
    config.generate_coredump(true);
    let engine = Engine::new(&config);
    let mut store = Store::new(&engine, ());
    let module = Module::new(
        &engine,
        r#"
        (module
            (memory (export "memory") 1)
            (global (export "g") (mut i32) (i32.const 7))
            (func (export "boom") (param i32 i64)
                (local i32)
                i32.const 5
                local.set 2
                local.get 0
                local.get 1
                local.get 2
                unreachable
            )
        )
        "#,
    )
    .unwrap();
    let instance = Linker::new(&engine)
        .instantiate_and_start(&mut store, &module)
        .unwrap();
    let func = instance
        .get_typed_func::<(i32, i64), ()>(&store, "boom")
        .unwrap();
    let error = func.call(&mut store, (3, 4)).unwrap_err();
    let coredump = error.coredump().expect("must have coredump");

    // The coredump must be parseable as a Wasm binary.
    let parser = wasmparser::Parser::new(0);
    let mut saw_memory = false;
    let mut saw_global = false;
    let mut saw_data = false;
    for payload in parser.parse_all(coredump) {
        let payload = payload.unwrap();
        match payload {
            wasmparser::Payload::CustomSection(section) => {
                let name = section.name();
                assert!(
                    ["core", "coremodules", "coreinstances", "corestack"].contains(&name),
                    "unexpected custom section {name}"
                );
            }
            wasmparser::Payload::MemorySection(_) => saw_memory = true,
            wasmparser::Payload::GlobalSection(_) => saw_global = true,
            wasmparser::Payload::DataSection(_) => saw_data = true,
            _ => {}
        }
    }
    assert!(saw_memory, "must have memory section");
    assert!(saw_global, "must have global section");
    assert!(saw_data, "must have data section");
    assert_eq!(corestack_frame_count(coredump), 1);
    // Locals are: param i32 = 3, param i64 = 4, local i32 = 5
    assert_eq!(corestack_first_frame_locals(coredump), vec![3, 4, 5]);
    // The coredump must be a valid Wasm module that can be parsed by Wasmi itself.
    let reparsed = Module::new(&engine, coredump);
    assert!(
        reparsed.is_ok(),
        "coredump must be valid Wasm: {reparsed:?}"
    );
}

/// Parses the function indices of the frames in the `"corestack"` section in order.
fn corestack_func_indices(wasm: &[u8]) -> Vec<u32> {
    let sections = custom_sections(wasm);
    let (_, payload) = sections
        .iter()
        .find(|(name, _)| name == "corestack")
        .expect("must have corestack section");
    let mut reader = Reader::new(payload);
    assert_eq!(reader.u8(), 0x00);
    let _thread_name = reader.name();
    let count = reader.u32() as usize;
    let mut funcs = Vec::new();
    for _ in 0..count {
        assert_eq!(reader.u8(), 0x00);
        let _instance_index = reader.u32();
        funcs.push(reader.u32());
        let _code_offset = reader.u32();
        let locals = reader.u32() as usize;
        for _ in 0..locals {
            let tag = reader.u8();
            match tag {
                0x7F => {
                    let _ = reader.u32();
                }
                0x7E => {
                    let _ = reader.u32();
                }
                0x7D => {
                    let _ = reader.bytes(4);
                }
                0x7C => {
                    let _ = reader.bytes(8);
                }
                0x01 => {}
                _ => panic!("unexpected value tag: {tag:#x}"),
            }
        }
        let operands = reader.u32() as usize;
        for _ in 0..operands {
            let tag = reader.u8();
            match tag {
                0x7F => {
                    let _ = reader.u32();
                }
                0x7E => {
                    let _ = reader.u32();
                }
                0x7D => {
                    let _ = reader.bytes(4);
                }
                0x7C => {
                    let _ = reader.bytes(8);
                }
                0x01 => {}
                _ => panic!("unexpected value tag: {tag:#x}"),
            }
        }
    }
    funcs
}

/// Parses the number of instances in the `"coreinstances"` section.
fn coreinstances_count(wasm: &[u8]) -> usize {
    let sections = custom_sections(wasm);
    let (_, payload) = sections
        .iter()
        .find(|(name, _)| name == "coreinstances")
        .expect("must have coreinstances section");
    let mut reader = Reader::new(payload);
    let count = reader.u32() as usize;
    for _ in 0..count {
        assert_eq!(reader.u8(), 0x00);
        let _module_index = reader.u32();
        let memories = reader.u32() as usize;
        for _ in 0..memories {
            let _ = reader.u32();
        }
        let globals = reader.u32() as usize;
        for _ in 0..globals {
            let _ = reader.u32();
        }
    }
    count
}

#[test]
fn coredump_from_root_host_calling_wasm() {
    let mut config = Config::default();
    config.generate_coredump(true);
    let engine = Engine::new(&config);
    let mut store = Store::new(&engine, ());
    let module = Module::new(&engine, r#"(module (func (export "inner") unreachable))"#).unwrap();
    let instance = Linker::new(&engine)
        .instantiate_and_start(&mut store, &module)
        .unwrap();
    let inner = instance.get_typed_func::<(), ()>(&store, "inner").unwrap();
    let host_fn = Func::wrap(
        &mut store,
        move |mut caller: Caller<()>| -> Result<(), Error> { inner.call(&mut caller, ()) },
    );
    let host_fn = host_fn.typed::<(), ()>(&store).unwrap();
    let error = host_fn.call(&mut store, ()).unwrap_err();
    assert!(!error.coredump().expect("must have coredump").is_empty());
    assert_eq!(corestack_frame_count(error.coredump().unwrap()), 1);
}

#[test]
fn coredump_has_frames_from_all_nested_levels() {
    let mut config = Config::default();
    config.generate_coredump(true);
    let engine = Engine::new(&config);
    let mut store = Store::new(&engine, ());
    // innermost traps
    let module_inner = Module::new(
        &engine,
        r#"(module (func (export "innermost") unreachable))"#,
    )
    .unwrap();
    let instance_inner = Linker::new(&engine)
        .instantiate_and_start(&mut store, &module_inner)
        .unwrap();
    let innermost = instance_inner
        .get_typed_func::<(), ()>(&store, "innermost")
        .unwrap();
    // level 1: Wasm calls host1; host1 calls Wasm (level 2); level 2 calls host2; host2 calls innermost Wasm
    let host2 = Func::wrap(
        &mut store,
        move |mut caller: Caller<()>| -> Result<(), Error> { innermost.call(&mut caller, ()) },
    );
    let mut linker = Linker::new(&engine);
    linker.define("env", "host2", host2).unwrap();
    let module_mid = Module::new(
        &engine,
        r#"
        (module
            (import "env" "host2" (func $host2))
            (func (export "middle") (call $host2))
        )
        "#,
    )
    .unwrap();
    let instance_mid = linker
        .instantiate_and_start(&mut store, &module_mid)
        .unwrap();
    let middle = instance_mid
        .get_typed_func::<(), ()>(&store, "middle")
        .unwrap();
    let host1 = Func::wrap(
        &mut store,
        move |mut caller: Caller<()>| -> Result<(), Error> { middle.call(&mut caller, ()) },
    );
    let mut linker = Linker::new(&engine);
    linker.define("env", "host1", host1).unwrap();
    let module_outer = Module::new(
        &engine,
        r#"
        (module
            (import "env" "host1" (func $host1))
            (func (export "outer") (call $host1))
        )
        "#,
    )
    .unwrap();
    let instance_outer = linker
        .instantiate_and_start(&mut store, &module_outer)
        .unwrap();
    let outer = instance_outer
        .get_typed_func::<(), ()>(&store, "outer")
        .unwrap();
    let error = outer.call(&mut store, ()).unwrap_err();
    let coredump = error.coredump().expect("must have coredump");
    // Three Wasm execution levels: innermost, middle, outer.
    assert_eq!(corestack_frame_count(coredump), 3);
}

#[test]
fn coredump_internal_call_chain_no_args() {
    let mut config = Config::default();
    config.generate_coredump(true);
    let engine = Engine::new(&config);
    let mut store = Store::new(&engine, ());
    let module = Module::new(
        &engine,
        r#"
        (module
            (func $inner unreachable)
            (func (export "outer") (call $inner))
        )
        "#,
    )
    .unwrap();
    let instance = Linker::new(&engine)
        .instantiate_and_start(&mut store, &module)
        .unwrap();
    let func = instance.get_typed_func::<(), ()>(&store, "outer").unwrap();
    let error = func.call(&mut store, ()).unwrap_err();
    let coredump = error.coredump().expect("must have coredump");
    assert_eq!(corestack_frame_count(coredump), 2);
    // module funcs: inner=0, outer=1. Youngest->oldest = [0,1].
    assert_eq!(corestack_func_indices(coredump), vec![0, 1]);
}


/// Reads a signed LEB128 encoded `i64` from the reader.
fn read_signed_i64(reader: &mut Reader) -> i64 {
    let mut result: i64 = 0;
    let mut shift = 0;
    let mut byte;
    loop {
        byte = reader.u8();
        result |= i64::from(byte & 0x7f) << shift;
        shift += 7;
        if byte & 0x80 == 0 {
            break;
        }
    }
    if shift < 64 && byte & 0x40 != 0 {
        result |= -1i64 << shift;
    }
    result
}

/// Parses the locals of the first frame as raw encoded values.
fn corestack_first_frame_local_values(wasm: &[u8]) -> Vec<(u8, Vec<u8>)> {
    let sections = custom_sections(wasm);
    let (_, payload) = sections
        .iter()
        .find(|(name, _)| name == "corestack")
        .expect("must have corestack section");
    let mut reader = Reader::new(payload);
    assert_eq!(reader.u8(), 0x00);
    let _thread_name = reader.name();
    let count = reader.u32() as usize;
    assert!(count >= 1);
    assert_eq!(reader.u8(), 0x00);
    let _instance_index = reader.u32();
    let _func_index = reader.u32();
    let _code_offset = reader.u32();
    let locals = reader.u32() as usize;
    let mut values = Vec::new();
    for _ in 0..locals {
        let tag = reader.u8();
        match tag {
            0x7F => {
                let _ = read_signed_i64(&mut reader);
                values.push((tag, Vec::new()));
            }
            0x7E => {
                let _ = read_signed_i64(&mut reader);
                values.push((tag, Vec::new()));
            }
            0x7D => {
                let bytes = reader.bytes(4).to_vec();
                values.push((tag, bytes));
            }
            0x7C => {
                let bytes = reader.bytes(8).to_vec();
                values.push((tag, bytes));
            }
            0x01 => values.push((tag, Vec::new())),
            _ => panic!("unexpected value tag: {tag:#x}"),
        }
    }
    values
}

#[test]
fn coredump_encodes_negative_and_float_locals() {
    let mut config = Config::default();
    config.generate_coredump(true);
    let engine = Engine::new(&config);
    let mut store = Store::new(&engine, ());
    let module = Module::new(
        &engine,
        r#"
        (module
            (func (export "boom") (param i32 i64 f32 f64)
                unreachable
            )
        )
        "#,
    )
    .unwrap();
    let instance = Linker::new(&engine)
        .instantiate_and_start(&mut store, &module)
        .unwrap();
    let func = instance
        .get_typed_func::<(i32, i64, f32, f64), ()>(&store, "boom")
        .unwrap();
    let error = func.call(&mut store, (-5, -6, 1.5f32, 2.5f64)).unwrap_err();
    let coredump = error.coredump().expect("must have coredump");
    let values = corestack_first_frame_local_values(coredump);
    assert_eq!(values.len(), 4);
    // i32, i64, f32, f64 tags
    assert_eq!(values[0].0, 0x7F);
    assert_eq!(values[1].0, 0x7E);
    assert_eq!(values[2].0, 0x7D);
    assert_eq!(values[3].0, 0x7C);
    // f32 1.5 -> bytes 00 00 c0 3f
    assert_eq!(values[2].1, 1.5f32.to_bits().to_le_bytes());
    // f64 2.5 -> bytes 00 00 00 00 00 00 04 40
    assert_eq!(values[3].1, 2.5f64.to_bits().to_le_bytes());
}

#[test]
fn coredump_from_start_function_trap() {
    let mut config = Config::default();
    config.generate_coredump(true);
    let engine = Engine::new(&config);
    let module = Module::new(
        &engine,
        r#"(module (func $start unreachable) (start $start))"#,
    )
    .unwrap();
    let mut store = Store::new(&engine, ());
    let error = Linker::new(&engine)
        .instantiate_and_start(&mut store, &module)
        .unwrap_err();
    assert!(!error.coredump().expect("must have coredump").is_empty());
    assert_eq!(corestack_frame_count(error.coredump().unwrap()), 1);
}
