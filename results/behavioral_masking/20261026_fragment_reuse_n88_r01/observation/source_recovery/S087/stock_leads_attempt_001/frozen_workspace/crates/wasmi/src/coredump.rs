//! Wasm coredump generation.
//!
//! This module implements generation of [Wasm coredumps] upon Wasm traps.
//! Coredumps are only generated if this feature is enabled via
//! [`Config::generate_coredump`](crate::Config::generate_coredump).
//!
//! [Wasm coredumps]: https://github.com/WebAssembly/tool-conventions/blob/main/Coredump.md

use crate::{
    Global, InstanceEntity, Memory, Mutability, ValType,
    core::{CoreGlobal, CoreMemory},
    engine::{CompiledCoredumpFunc, CoredumpFuncMeta, Stack, VmState},
    store::StoreInner,
};
use alloc::{format, string::String, vec::Vec};

/// A stack frame captured for a Wasm coredump.
pub(crate) struct CapturedFrame {
    /// The pointer of the [`InstanceEntity`] of the frame.
    pub instance_ptr: usize,
    /// The Wasm function index of the frame within its module.
    pub func_idx: u32,
    /// The local values of the frame.
    pub locals: Vec<CoredumpValue>,
    /// The operand stack values of the frame.
    pub stack: Vec<CoredumpValue>,
}

/// A single value captured for a Wasm coredump.
#[derive(Debug, Copy, Clone)]
pub(crate) enum CoredumpValue {
    /// A value that could not be recovered.
    Missing,
    /// An `i32` value.
    I32(i32),
    /// An `i64` value.
    I64(i64),
    /// An `f32` value encoded as its IEEE 754 bits.
    F32(u32),
    /// An `f64` value encoded as its IEEE 754 bits.
    F64(u64),
}

/// A guard registering a [`Stack`] as currently active.
///
/// # Note
///
/// This is required to correctly generate Wasm coredumps for re-entrant
/// Wasm executions where multiple [`Stack`]s may be active at the same time.
pub(crate) struct ActiveStackGuard {
    stack: *mut Stack,
    store: *mut StoreInner,
}

impl ActiveStackGuard {
    /// Creates a new [`ActiveStackGuard`] for the given [`Stack`] and [`StoreInner`].
    pub(crate) fn new(stack: &mut Stack, store: &mut StoreInner) -> Self {
        let stack = stack as *mut Stack;
        let store = store as *mut StoreInner;
        // Safety: the store is alive for the entire duration of the guard.
        unsafe { (&mut *store).push_active_stack(stack) };
        Self { stack, store }
    }
}

impl Drop for ActiveStackGuard {
    fn drop(&mut self) {
        // Safety: the store is alive for the entire duration of the guard.
        unsafe { (&mut *self.store).pop_active_stack(self.stack) };
    }
}

/// Generates a Wasm coredump for the currently active execution.
///
/// Returns `None` if coredump generation is not possible.
pub(crate) fn generate(state: &mut VmState<'_>) -> Option<Vec<u8>> {
    let store = state.store.inner();
    let code = state.code;
    let executable_name = String::from(store.engine().config().get_coredump_executable_name());
    let funcs = code.collect_coredump_funcs();

    // Capture frames from all active stacks, innermost first.
    let stack_pointers = store.active_stacks();
    let mut frames = Vec::new();
    for &stack_addr in stack_pointers.iter().rev() {
        // Safety: the active stacks are alive for the entire duration of the
        // innermost execution and never mutated while we generate the coredump.
        let stack = unsafe { &*(stack_addr as *mut Stack) };
        let mut captured = capture_stack(stack, store, &funcs);
        frames.append(&mut captured);
    }

    // Collect modules, instances, memories and globals from the store.
    let mut modules: Vec<ModuleInfo> = Vec::new();
    let mut instances: Vec<&InstanceEntity> = Vec::new();
    let mut memories: Vec<*const CoreMemory> = Vec::new();
    let mut globals: Vec<*const CoreGlobal> = Vec::new();

    for instance in store.instances() {
        if !instance.is_initialized() {
            continue;
        }
        // Add module.
        if let Some(module) = instance.module() {
            let id = module.unique_id();
            if !modules.iter().any(|m| m.id == id) {
                let name = module
                    .name()
                    .unwrap_or_else(|| format!("module-{}", modules.len()));
                modules.push(ModuleInfo { id, name });
            }
        }
        // Add memories and globals.
        for memory in instance.memories() {
            let core = store.resolve_memory(memory);
            let ptr = core as *const CoreMemory;
            if !memories.contains(&ptr) {
                memories.push(ptr);
            }
        }
        for global in instance.globals() {
            let core = store.resolve_global(global);
            if !core.ty().content().is_num() {
                continue;
            }
            let ptr = core as *const CoreGlobal;
            if !globals.contains(&ptr) {
                globals.push(ptr);
            }
        }
        instances.push(instance);
    }

    // Build maps from entity pointer to coredump index.
    let module_index = |instance: &InstanceEntity| -> u32 {
        let Some(module) = instance.module() else {
            return 0;
        };
        let id = module.unique_id();
        modules.iter().position(|m| m.id == id).unwrap_or(0) as u32
    };
    let memory_index = |memory: &Memory| -> u32 {
        let core = store.resolve_memory(memory);
        let ptr = core as *const CoreMemory;
        memories
            .iter()
            .position(|m| *m == ptr)
            .unwrap_or(u32::MAX as usize) as u32
    };
    let global_index = |global: &Global| -> Option<u32> {
        let core = store.resolve_global(global);
        if !core.ty().content().is_num() {
            return None;
        }
        let ptr = core as *const CoreGlobal;
        Some(
            globals
                .iter()
                .position(|g| *g == ptr)
                .unwrap_or(u32::MAX as usize) as u32,
        )
    };
    let instance_index = |ptr: usize| -> u32 {
        instances
            .iter()
            .position(|i| (*i) as *const InstanceEntity as usize == ptr)
            .unwrap_or(u32::MAX as usize) as u32
    };

    let mut out = Vec::new();

    // 1. "core" custom section.
    let mut core_data = Vec::new();
    core_data.push(0x00);
    push_name(&mut core_data, &executable_name);
    write_custom_section(&mut out, "core", &core_data);

    // 2. Memory section.
    {
        let mut contents = Vec::new();
        push_uleb(&mut contents, memories.len() as u64);
        for &memory_ptr in &memories {
            // Safety: all memory pointers refer to live entities in the store.
            let memory = unsafe { &*memory_ptr };
            let ty = memory.dynamic_ty();
            let minimum = ty.minimum();
            let maximum = ty.maximum();
            let mut flags = 0u64;
            if maximum.is_some() {
                flags |= 0x01;
            }
            if ty.is_64() {
                flags |= 0x04;
            }
            push_uleb(&mut contents, flags);
            push_uleb(&mut contents, minimum);
            if let Some(maximum) = maximum {
                push_uleb(&mut contents, maximum);
            }
        }
        write_section(&mut out, 5, &contents);
    }

    // 3. Global section.
    {
        let mut contents = Vec::new();
        push_uleb(&mut contents, globals.len() as u64);
        for &global_ptr in &globals {
            // Safety: all global pointers refer to live entities in the store.
            let global = unsafe { &*global_ptr };
            let ty = global.ty();
            push_val_type(&mut contents, ty.content());
            contents.push(match ty.mutability() {
                Mutability::Const => 0x00,
                Mutability::Var => 0x01,
            });
            let value = global.get();
            write_const_expr(&mut contents, ty.content(), value.raw().to_bits64());
        }
        write_section(&mut out, 6, &contents);
    }

    // 4. Data section.
    {
        let mut contents = Vec::new();
        push_uleb(&mut contents, memories.len() as u64);
        for (idx, &memory_ptr) in memories.iter().enumerate() {
            // Safety: all memory pointers refer to live entities in the store.
            let memory = unsafe { &*memory_ptr };
            let data = memory.data();
            if idx == 0 {
                contents.push(0x00);
            } else {
                contents.push(0x02);
                push_uleb(&mut contents, idx as u64);
            }
            // i32.const offset 0, end
            contents.push(0x41);
            push_uleb(&mut contents, 0);
            contents.push(0x0B);
            push_uleb(&mut contents, data.len() as u64);
            contents.extend_from_slice(data);
        }
        write_section(&mut out, 11, &contents);
    }

    // 5. "coremodules" custom section.
    let mut modules_data = Vec::new();
    push_uleb(&mut modules_data, modules.len() as u64);
    for module in &modules {
        modules_data.push(0x00);
        push_name(&mut modules_data, &module.name);
    }
    write_custom_section(&mut out, "coremodules", &modules_data);

    // 6. "coreinstances" custom section.
    let mut instances_data = Vec::new();
    push_uleb(&mut instances_data, instances.len() as u64);
    for instance in &instances {
        instances_data.push(0x00);
        push_uleb(&mut instances_data, module_index(instance) as u64);
        let memories = instance
            .memories()
            .iter()
            .map(memory_index)
            .collect::<Vec<_>>();
        push_uleb(&mut instances_data, memories.len() as u64);
        for memory in memories {
            push_uleb(&mut instances_data, memory as u64);
        }
        let globals = instance
            .globals()
            .iter()
            .filter_map(global_index)
            .collect::<Vec<_>>();
        push_uleb(&mut instances_data, globals.len() as u64);
        for global in globals {
            push_uleb(&mut instances_data, global as u64);
        }
    }
    write_custom_section(&mut out, "coreinstances", &instances_data);

    // 7. "corestack" custom section.
    let mut stack_data = Vec::new();
    stack_data.push(0x00);
    push_name(&mut stack_data, "main");
    push_uleb(&mut stack_data, frames.len() as u64);
    for frame in &frames {
        stack_data.push(0x00);
        push_uleb(&mut stack_data, instance_index(frame.instance_ptr) as u64);
        push_uleb(&mut stack_data, frame.func_idx as u64);
        // Note: Wasmi does not retain enough information to recover the
        //       exact Wasm code offset of the frame.
        push_uleb(&mut stack_data, 0);
        push_uleb(&mut stack_data, frame.locals.len() as u64);
        for value in &frame.locals {
            write_value(&mut stack_data, *value);
        }
        push_uleb(&mut stack_data, frame.stack.len() as u64);
        for value in &frame.stack {
            write_value(&mut stack_data, *value);
        }
    }
    write_custom_section(&mut out, "corestack", &stack_data);

    // Prepend the Wasm header.
    let mut result = Vec::with_capacity(out.len() + 8);
    result.extend_from_slice(b"\0asm");
    result.extend_from_slice(&1u32.to_le_bytes());
    result.extend_from_slice(&out);
    Some(result)
}

/// Information about a module in the coredump.
struct ModuleInfo {
    /// A unique identifier of the module.
    id: *const (),
    /// The name of the module.
    name: String,
}

/// Captures the stack frames of the given [`Stack`].
fn capture_stack(
    stack: &Stack,
    _store: &StoreInner,
    funcs: &[CompiledCoredumpFunc],
) -> Vec<CapturedFrame> {
    let cells = stack.cells();
    let frames = stack.frames();
    let mut result = Vec::new();
    let mut next_start = cells.len();
    let mut cur_instance = stack.current_instance();

    for frame in frames.iter().rev() {
        let start = frame.start_offset();
        let meta = find_func(funcs, frame.ip_ptr());
        let (locals, locals_cells) = match meta {
            Some(meta) => (
                read_locals(cells, start, &meta.locals),
                locals_cells(&meta.locals),
            ),
            None => (Vec::new(), 0),
        };
        let locals_end = start.saturating_add(locals_cells);
        let stack_end = next_start.min(cells.len());
        let stack_len = stack_end.saturating_sub(locals_end);
        let stack = (0..stack_len)
            .map(|_| CoredumpValue::Missing)
            .collect::<Vec<_>>();
        let instance_ptr = cur_instance.map(|inst| inst.as_ptr() as usize).unwrap_or(0);
        result.push(CapturedFrame {
            instance_ptr,
            func_idx: meta.map(|m| m.func_idx).unwrap_or(0),
            locals,
            stack,
        });
        next_start = start;
        // Move to the caller instance.
        if let Some(prev) = frame.instance_opt() {
            cur_instance = Some(prev);
        }
    }
    result
}

/// Finds the coredump metadata of the compiled function containing `ip`.
fn find_func(funcs: &[CompiledCoredumpFunc], ip: *const u8) -> Option<&CoredumpFuncMeta> {
    let addr = ip as usize;
    funcs
        .iter()
        .find(|func| func.start <= addr && addr < func.end)
        .map(|func| &func.meta)
}

/// Returns the number of cells required to store a value of the given type.
fn cells_for_ty(ty: ValType) -> usize {
    if ty == ValType::V128 { 2 } else { 1 }
}

/// Returns the total number of cells required to store the given local types.
fn locals_cells(locals: &[ValType]) -> usize {
    locals.iter().copied().map(cells_for_ty).sum()
}

/// Reads the local values of a frame from the value stack.
fn read_locals(
    cells: &[crate::engine::Cell],
    start: usize,
    locals: &[ValType],
) -> Vec<CoredumpValue> {
    let mut offset = start;
    let mut values = Vec::with_capacity(locals.len());
    for ty in locals {
        let value = match ty {
            ValType::I32 => cells
                .get(offset)
                .map(|cell| CoredumpValue::I32(cell.to_bits() as i32))
                .unwrap_or(CoredumpValue::Missing),
            ValType::I64 => cells
                .get(offset)
                .map(|cell| CoredumpValue::I64(cell.to_bits() as i64))
                .unwrap_or(CoredumpValue::Missing),
            ValType::F32 => cells
                .get(offset)
                .map(|cell| CoredumpValue::F32(cell.to_bits() as u32))
                .unwrap_or(CoredumpValue::Missing),
            ValType::F64 => cells
                .get(offset)
                .map(|cell| CoredumpValue::F64(cell.to_bits()))
                .unwrap_or(CoredumpValue::Missing),
            _ => CoredumpValue::Missing,
        };
        values.push(value);
        offset = offset.saturating_add(cells_for_ty(*ty));
    }
    values
}

/// Writes an unsigned LEB128 encoded `u64` to `out`.
fn push_uleb(out: &mut Vec<u8>, mut value: u64) {
    loop {
        let mut byte = (value & 0x7f) as u8;
        value >>= 7;
        if value != 0 {
            byte |= 0x80;
        }
        out.push(byte);
        if value == 0 {
            break;
        }
    }
}

/// Writes a signed LEB128 encoded `i64` to `out`.
fn push_sleb(out: &mut Vec<u8>, value: i64) {
    let mut value = value;
    loop {
        let mut byte = (value & 0x7f) as u8;
        value >>= 7;
        let sign_bit_set = byte & 0x40 != 0;
        let done = (value == 0 && !sign_bit_set) || (value == -1 && sign_bit_set);
        if !done {
            byte |= 0x80;
        }
        out.push(byte);
        if done {
            break;
        }
    }
}

/// Writes a name (LEB128 length-prefixed UTF-8 string) to `out`.
fn push_name(out: &mut Vec<u8>, name: &str) {
    push_uleb(out, name.len() as u64);
    out.extend_from_slice(name.as_bytes());
}

/// Writes a Wasm value type byte to `out`.
fn push_val_type(out: &mut Vec<u8>, ty: ValType) {
    let byte = match ty {
        ValType::I32 => 0x7F,
        ValType::I64 => 0x7E,
        ValType::F32 => 0x7D,
        ValType::F64 => 0x7C,
        ValType::V128 => 0x7B,
        ValType::FuncRef => 0x70,
        ValType::ExternRef => 0x6F,
    };
    out.push(byte);
}

/// Writes a constant expression for the given numeric `value` of type `ty`.
fn write_const_expr(out: &mut Vec<u8>, ty: ValType, bits: u64) {
    match ty {
        ValType::I32 => {
            out.push(0x41);
            push_sleb(out, bits as u32 as i32 as i64);
        }
        ValType::I64 => {
            out.push(0x42);
            push_sleb(out, bits as i64);
        }
        ValType::F32 => {
            out.push(0x43);
            out.extend_from_slice(&(bits as u32).to_le_bytes());
        }
        ValType::F64 => {
            out.push(0x44);
            out.extend_from_slice(&bits.to_le_bytes());
        }
        // Note: non-numeric globals are not included in coredumps.
        _ => unreachable!("non-numeric global value in coredump"),
    }
    out.push(0x0B);
}

/// Writes a [`CoredumpValue`] to `out`.
fn write_value(out: &mut Vec<u8>, value: CoredumpValue) {
    match value {
        CoredumpValue::Missing => out.push(0x01),
        CoredumpValue::I32(value) => {
            out.push(0x7F);
            push_sleb(out, value as i64);
        }
        CoredumpValue::I64(value) => {
            out.push(0x7E);
            push_sleb(out, value);
        }
        CoredumpValue::F32(bits) => {
            out.push(0x7D);
            out.extend_from_slice(&bits.to_le_bytes());
        }
        CoredumpValue::F64(bits) => {
            out.push(0x7C);
            out.extend_from_slice(&bits.to_le_bytes());
        }
    }
}

/// Writes a custom section with the given `name` and `data` to `out`.
fn write_custom_section(out: &mut Vec<u8>, name: &str, data: &[u8]) {
    let mut payload = Vec::new();
    push_name(&mut payload, name);
    payload.extend_from_slice(data);
    out.push(0x00);
    push_uleb(out, payload.len() as u64);
    out.extend_from_slice(&payload);
}

/// Writes a standard Wasm section with the given `id` and `contents` to `out`.
fn write_section(out: &mut Vec<u8>, id: u8, contents: &[u8]) {
    out.push(id);
    push_uleb(out, contents.len() as u64);
    out.extend_from_slice(contents);
}
