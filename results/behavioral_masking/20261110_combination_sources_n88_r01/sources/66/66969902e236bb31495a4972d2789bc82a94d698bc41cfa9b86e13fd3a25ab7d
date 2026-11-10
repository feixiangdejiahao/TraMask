//! Coredump generation for Wasmi.
//!
//! When coredump generation is enabled via
//! [`Config::generate_coredump`](crate::Config::generate_coredump) and a Wasm
//! trap occurs, the returned [`Error`](crate::Error) carries a serialized
//! coredump that post-mortem debugging tools can load.
//!
//! The coredump is a valid Wasm binary with the following custom sections:
//!
//! - `"core"`: executable name.
//! - `"coremodules"`: module names.
//! - `"coreinstances"`: instances with their memories and globals.
//! - `"corestack"`: stack frames with locals and operand stacks.
//!
//! The binary also contains regular Wasm memory, global and data sections
//! capturing the state of linear memories and globals at trap time.

use super::{
    CodeMap,
    executor::{Inst, Stack},
};
use crate::{
    GlobalType, ValType,
    collections::Map,
    core::{CoreMemoryType, RawVal, ReadAs},
    store::PrunedStore,
};
use alloc::{string::String, vec, vec::Vec};
use core::fmt;

/// A value captured for coredump generation.
#[derive(Debug, Clone, Copy)]
pub(crate) enum CoredumpValue {
    /// A 32-bit integer value.
    I32(i32),
    /// A 64-bit integer value.
    I64(i64),
    /// A 32-bit float value stored as its raw IEEE 754 bits.
    F32(u32),
    /// A 64-bit float value stored as its raw IEEE 754 bits.
    F64(u64),
    /// A value that could not be recovered.
    Unknown,
}

/// A module instance captured for coredump generation.
#[derive(Debug)]
pub(crate) struct CoredumpInstance {
    /// The stable arena index of the Wasm instance used for deduplication.
    key: usize,
    /// The index of the module within the `"coremodules"` section.
    module_index: u32,
    /// Indices into the coredump's memory index space.
    memory_indices: Vec<u32>,
    /// Indices into the coredump's global index space.
    global_indices: Vec<u32>,
}

/// A linear memory captured for coredump generation.
#[derive(Clone)]
pub(crate) struct CoredumpMemory {
    /// The stable arena index of the memory used for deduplication.
    key: usize,
    /// The type of the linear memory.
    ty: CoreMemoryType,
    /// The bytes of the linear memory at trap time.
    data: Vec<u8>,
}

impl fmt::Debug for CoredumpMemory {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        f.debug_struct("CoredumpMemory")
            .field("key", &self.key)
            .field("ty", &self.ty)
            .field("data_len", &self.data.len())
            .finish()
    }
}

/// A global variable captured for coredump generation.
#[derive(Debug, Clone)]
pub(crate) struct CoredumpGlobal {
    /// The stable arena index of the global used for deduplication.
    key: usize,
    /// The type of the global variable.
    ty: GlobalType,
    /// The value of the global variable at trap time.
    value: RawVal,
}

/// A stack frame captured for coredump generation.
#[derive(Debug, Clone)]
pub(crate) struct CoredumpFrame {
    /// The index of the instance within the `"coreinstances"` section.
    instance_index: u32,
    /// The Wasm function index of the function within its module.
    func_index: u32,
    /// The code offset into the function or `0` if not available.
    code_offset: u32,
    /// The values of the function parameters and local variables.
    locals: Vec<CoredumpValue>,
    /// The values on the operand stack of the function.
    operands: Vec<CoredumpValue>,
}

/// A Wasm coredump.
///
/// # Note
///
/// This is the structured representation used while constructing a coredump.
/// The final serialized bytes are stored in [`Coredump::bytes`].
#[derive(Default)]
pub(crate) struct Coredump {
    /// The executable name of the coredump.
    executable_name: String,
    /// The names of all modules in the coredump.
    modules: Vec<String>,
    /// All instances in the coredump.
    instances: Vec<CoredumpInstance>,
    /// All stack frames in the coredump ordered oldest to newest.
    frames: Vec<CoredumpFrame>,
    /// All linear memories in the coredump.
    memories: Vec<CoredumpMemory>,
    /// All global variables in the coredump.
    globals: Vec<CoredumpGlobal>,
    /// The serialized coredump bytes.
    bytes: Vec<u8>,
    /// Maps instance raw pointers to indices in [`Coredump::instances`].
    instance_map: Map<usize, u32>,
    /// Maps memory raw pointers to indices in [`Coredump::memories`].
    memory_map: Map<usize, u32>,
    /// Maps global raw pointers to indices in [`Coredump::globals`].
    global_map: Map<usize, u32>,
}

impl fmt::Debug for Coredump {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        f.debug_struct("Coredump")
            .field("executable_name", &self.executable_name)
            .field("modules", &self.modules)
            .field("instances", &self.instances)
            .field("frames", &self.frames)
            .field("memories", &self.memories)
            .field("globals", &self.globals)
            .field("bytes_len", &self.bytes.len())
            .finish()
    }
}

impl Coredump {
    /// Creates a new empty [`Coredump`] with the given `executable_name`.
    pub(crate) fn new(executable_name: &str) -> Self {
        Self {
            executable_name: executable_name.into(),
            ..Self::default()
        }
    }

    /// Captures the current state of the given `stack` into a new [`Coredump`].
    ///
    /// # Note
    ///
    /// - The captured frames are ordered youngest to oldest after serialization.
    /// - The `executable_name` is taken from the engine configuration.
    pub(crate) fn capture(
        store: &PrunedStore,
        stack: &Stack,
        code: &CodeMap,
        executable_name: &str,
    ) -> Coredump {
        let mut dump = Coredump::new(executable_name);
        dump.capture_frames(store, stack, code);
        dump.serialize();
        dump
    }

    /// Extends `self` with the frames of the given `stack`.
    ///
    /// # Note
    ///
    /// This is used when a host function re-enters Wasm and the inner execution
    /// traps: the coredump generated by the inner invocation is extended with
    /// the frames of the outer Wasm execution levels.
    pub(crate) fn extend_with_stack(&mut self, store: &PrunedStore, stack: &Stack, code: &CodeMap) {
        let mut outer = Coredump::new("");
        outer.capture_frames(store, stack, code);
        self.merge_outer(&outer);
        self.serialize();
    }

    /// Returns the serialized coredump bytes.
    pub(crate) fn bytes(&self) -> &[u8] {
        &self.bytes
    }

    /// Captures the frames of the given `stack` into `self`.
    fn capture_frames(&mut self, store: &PrunedStore, stack: &Stack, code: &CodeMap) {
        let frames = stack.frames();
        let cells = stack.cells();
        let len_frames = frames.len();
        if len_frames == 0 {
            return;
        }
        // Reconstruct the actual instance of every frame.
        let mut actual_instances = vec![None; len_frames];
        let mut current = stack.current_instance();
        for index in (0..len_frames).rev() {
            actual_instances[index] = current;
            if let Some(prev) = frames[index].instance() {
                current = Some(prev);
            }
        }
        for (index, frame) in frames.iter().enumerate() {
            let Some(instance) = actual_instances[index] else {
                continue;
            };
            let instance_index = self.get_or_add_instance(store, instance);
            let Some((_func, cref)) = code.find_func_by_ip(frame.ip()) else {
                continue;
            };
            let ops = cref.ops();
            let ip_addr = frame.ip().as_ptr() as usize;
            let code_offset = ip_addr.saturating_sub(ops.as_ptr() as usize) as u32;
            let frame_start = frame.start().into_inner();
            let local_tys = cref.locals();
            // Compute the values of all function parameters and declared locals.
            let mut locals = Vec::with_capacity(local_tys.len());
            let mut cell_offset = frame_start;
            for ty in local_tys {
                locals.push(read_cell(cells, cell_offset, *ty));
                cell_offset += cells_for_valtype(*ty);
            }
            // Compute the values on the operand stack.
            let operand_start = cell_offset;
            let operand_end = match frames.get(index + 1) {
                Some(next) => next.start().into_inner(),
                None => {
                    let frame_end = frame_start.saturating_add(usize::from(cref.len_stack_slots()));
                    frame_end.min(cells.len())
                }
            };
            // Guard against frames that overlap or where the callee starts at or
            // before the caller's operand area.
            let operand_end = operand_end.max(operand_start);
            let operands = cells[operand_start..operand_end]
                .iter()
                .map(|_| CoredumpValue::Unknown)
                .collect();
            self.frames.push(CoredumpFrame {
                instance_index,
                func_index: cref.func_index().into_u32(),
                code_offset,
                locals,
                operands,
            });
        }
    }

    /// Merges the frames of an outer execution into `self`.
    ///
    /// # Note
    ///
    /// The frames of the outer execution are older than the frames already
    /// contained in `self` and are therefore prepended to the frame list.
    fn merge_outer(&mut self, outer: &Coredump) {
        let mut instance_remap = vec![0; outer.instances.len()];
        for (index, instance) in outer.instances.iter().enumerate() {
            let new_index = if let Some(index) = self.instance_map.get(&instance.key) {
                *index
            } else {
                let module_index = self.modules.len() as u32;
                self.modules
                    .push(outer.modules[instance.module_index as usize].clone());
                let memory_indices = instance
                    .memory_indices
                    .iter()
                    .map(|&index| self.merge_memory(&outer.memories[index as usize]))
                    .collect();
                let global_indices = instance
                    .global_indices
                    .iter()
                    .map(|&index| self.merge_global(&outer.globals[index as usize]))
                    .collect();
                let new_index = self.instances.len() as u32;
                self.instances.push(CoredumpInstance {
                    key: instance.key,
                    module_index,
                    memory_indices,
                    global_indices,
                });
                self.instance_map.insert(instance.key, new_index);
                new_index
            };
            instance_remap[index] = new_index;
        }
        let mut new_frames = Vec::with_capacity(outer.frames.len() + self.frames.len());
        for frame in &outer.frames {
            let mut frame = frame.clone();
            frame.instance_index = instance_remap[frame.instance_index as usize];
            new_frames.push(frame);
        }
        new_frames.append(&mut self.frames);
        self.frames = new_frames;
    }

    /// Merges a memory from an outer capture into `self` returning its new index.
    fn merge_memory(&mut self, memory: &CoredumpMemory) -> u32 {
        if let Some(index) = self.memory_map.get(&memory.key) {
            return *index;
        }
        let index = self.memories.len() as u32;
        self.memories.push(memory.clone());
        self.memory_map.insert(memory.key, index);
        index
    }

    /// Merges a global from an outer capture into `self` returning its new index.
    fn merge_global(&mut self, global: &CoredumpGlobal) -> u32 {
        if let Some(index) = self.global_map.get(&global.key) {
            return *index;
        }
        let index = self.globals.len() as u32;
        self.globals.push(global.clone());
        self.global_map.insert(global.key, index);
        index
    }

    /// Returns the index of the given `instance`, adding it if necessary.
    fn get_or_add_instance(&mut self, store: &PrunedStore, instance: Inst) -> u32 {
        let entity = unsafe { instance.as_ref() };
        let key = store.inner().resolve_instance_index(entity);
        if let Some(index) = self.instance_map.get(&key) {
            return *index;
        }
        let module_index = self.modules.len() as u32;
        self.modules.push(String::new());
        let mut memory_indices = Vec::new();
        let mut memory_index = 0;
        while let Some(memory) = entity.get_memory(memory_index) {
            memory_indices.push(self.get_or_add_memory(store, &memory));
            memory_index += 1;
        }
        let mut global_indices = Vec::new();
        let mut global_index = 0;
        while let Some(global) = entity.get_global(global_index) {
            global_indices.push(self.get_or_add_global(store, &global));
            global_index += 1;
        }
        let index = self.instances.len() as u32;
        self.instances.push(CoredumpInstance {
            key,
            module_index,
            memory_indices,
            global_indices,
        });
        self.instance_map.insert(key, index);
        index
    }

    /// Returns the index of the given `memory`, adding it if necessary.
    fn get_or_add_memory(&mut self, store: &PrunedStore, memory: &crate::Memory) -> u32 {
        let core_memory = store.inner().resolve_memory(memory);
        let key = store.inner().resolve_memory_index(memory);
        if let Some(index) = self.memory_map.get(&key) {
            return *index;
        }
        let index = self.memories.len() as u32;
        self.memories.push(CoredumpMemory {
            key,
            ty: core_memory.ty(),
            data: core_memory.data().to_vec(),
        });
        self.memory_map.insert(key, index);
        index
    }

    /// Returns the index of the given `global`, adding it if necessary.
    fn get_or_add_global(&mut self, store: &PrunedStore, global: &crate::Global) -> u32 {
        let core_global = store.inner().resolve_global(global);
        let key = store.inner().resolve_global_index(global);
        if let Some(index) = self.global_map.get(&key) {
            return *index;
        }
        let index = self.globals.len() as u32;
        self.globals.push(CoredumpGlobal {
            key,
            ty: core_global.ty(),
            value: *core_global.get_raw(),
        });
        self.global_map.insert(key, index);
        index
    }

    /// Serializes `self` into the Wasm binary format.
    fn serialize(&mut self) {
        let mut out = vec![0x00, 0x61, 0x73, 0x6D, 0x01, 0x00, 0x00, 0x00];

        // Section: "core"
        let mut payload = Vec::new();
        payload.push(0x00);
        payload.encode_name(&self.executable_name);
        out.encode_custom_section("core", &payload);

        // Section: "coremodules"
        let mut payload = Vec::new();
        payload.encode_u32(self.modules.len() as u32);
        for module in &self.modules {
            payload.push(0x00);
            payload.encode_name(module);
        }
        out.encode_custom_section("coremodules", &payload);

        // Section: "coreinstances"
        let mut payload = Vec::new();
        payload.encode_u32(self.instances.len() as u32);
        for instance in &self.instances {
            payload.push(0x00);
            payload.encode_u32(instance.module_index);
            payload.encode_u32(instance.memory_indices.len() as u32);
            for &memory_index in &instance.memory_indices {
                payload.encode_u32(memory_index);
            }
            payload.encode_u32(instance.global_indices.len() as u32);
            for &global_index in &instance.global_indices {
                payload.encode_u32(global_index);
            }
        }
        out.encode_custom_section("coreinstances", &payload);

        // Section: "corestack"
        let mut payload = Vec::new();
        payload.push(0x00);
        payload.encode_name("main");
        payload.encode_u32(self.frames.len() as u32);
        for frame in self.frames.iter().rev() {
            payload.push(0x00);
            payload.encode_u32(frame.instance_index);
            payload.encode_u32(frame.func_index);
            payload.encode_u32(frame.code_offset);
            payload.encode_values(&frame.locals);
            payload.encode_values(&frame.operands);
        }
        out.encode_custom_section("corestack", &payload);

        // Section: memory (id 5)
        let mut section = Vec::new();
        section.encode_u32(self.memories.len() as u32);
        for memory in &self.memories {
            memory.encode(&mut section);
        }
        out.encode_standard_section(5, &section);

        // Section: global (id 6)
        let mut section = Vec::new();
        section.encode_u32(self.globals.len() as u32);
        for global in &self.globals {
            global.encode(&mut section);
        }
        out.encode_standard_section(6, &section);

        // Section: data (id 11)
        let mut section = Vec::new();
        let mut segments = Vec::new();
        for (index, memory) in self.memories.iter().enumerate() {
            if memory.data.is_empty() {
                continue;
            }
            segments.push((index as u32, &memory.data[..]));
        }
        section.encode_u32(segments.len() as u32);
        for (memory_index, data) in segments {
            if memory_index == 0 {
                section.push(0x00);
            } else {
                section.push(0x01);
                section.encode_u32(memory_index);
            }
            section.push(0x41);
            section.encode_signed_i32(0);
            section.push(0x0B);
            section.encode_u32(data.len() as u32);
            section.extend_from_slice(data);
        }
        out.encode_standard_section(11, &section);

        self.bytes = out;
    }
}

impl CoredumpMemory {
    /// Encodes `self` into the memory section payload.
    fn encode(&self, out: &mut Vec<u8>) {
        let mut flags = if self.ty.maximum().is_some() {
            0x01
        } else {
            0x00
        };
        if self.ty.is_64() {
            flags |= 0x04;
        }
        out.push(flags);
        if self.ty.is_64() {
            out.encode_u64(self.ty.minimum());
            if let Some(maximum) = self.ty.maximum() {
                out.encode_u64(maximum);
            }
        } else {
            out.encode_u32(self.ty.minimum() as u32);
            if let Some(maximum) = self.ty.maximum() {
                out.encode_u32(maximum as u32);
            }
        }
    }
}

impl CoredumpGlobal {
    /// Encodes `self` into the global section payload.
    fn encode(&self, out: &mut Vec<u8>) {
        out.push(valtype_byte(self.ty.content()));
        out.push(if self.ty.mutability().is_mut() {
            0x01
        } else {
            0x00
        });
        match self.ty.content() {
            ValType::I32 => {
                let value: i32 = self.value.read_as();
                out.push(0x41);
                out.encode_signed_i32(value);
                out.push(0x0B);
            }
            ValType::I64 => {
                let value: i64 = self.value.read_as();
                out.push(0x42);
                out.encode_signed_i64(value);
                out.push(0x0B);
            }
            ValType::F32 => {
                let value: f32 = self.value.read_as();
                out.push(0x43);
                out.extend_from_slice(&value.to_bits().to_le_bytes());
                out.push(0x0B);
            }
            ValType::F64 => {
                let value: f64 = self.value.read_as();
                out.push(0x44);
                out.extend_from_slice(&value.to_bits().to_le_bytes());
                out.push(0x0B);
            }
            _ => {
                // Reference and vector values cannot be represented in the
                // coredump global section, emit a zero i32 constant instead.
                out.push(0x41);
                out.encode_signed_i32(0);
                out.push(0x0B);
            }
        }
    }
}

/// Returns the number of cells required to represent a value of `ty`.
fn cells_for_valtype(ty: ValType) -> usize {
    match ty {
        #[cfg(feature = "simd")]
        ValType::V128 => 2,
        _ => 1,
    }
}

/// Returns the Wasm binary value type byte for `ty`.
fn valtype_byte(ty: ValType) -> u8 {
    match ty {
        ValType::I32 => 0x7F,
        ValType::I64 => 0x7E,
        ValType::F32 => 0x7D,
        ValType::F64 => 0x7C,
        ValType::V128 => 0x7B,
        ValType::FuncRef => 0x70,
        ValType::ExternRef => 0x6F,
    }
}

/// Reads a value of type `ty` from `cells` at `offset`.
fn read_cell(cells: &[crate::engine::executor::Cell], offset: usize, ty: ValType) -> CoredumpValue {
    let Some(cell) = cells.get(offset) else {
        return CoredumpValue::Unknown;
    };
    let bits = u64::from(*cell);
    match ty {
        ValType::I32 => CoredumpValue::I32(bits as i32),
        ValType::I64 => CoredumpValue::I64(bits as i64),
        ValType::F32 => CoredumpValue::F32(bits as u32),
        ValType::F64 => CoredumpValue::F64(bits),
        _ => CoredumpValue::Unknown,
    }
}

trait Encode {
    fn encode_u32(&mut self, value: u32);
    fn encode_u64(&mut self, value: u64);
    fn encode_signed_i32(&mut self, value: i32);
    fn encode_signed_i64(&mut self, value: i64);
    fn encode_name(&mut self, name: &str);
    fn encode_values(&mut self, values: &[CoredumpValue]);
    fn encode_custom_section(&mut self, name: &str, payload: &[u8]);
    fn encode_standard_section(&mut self, id: u8, payload: &[u8]);
}

impl Encode for Vec<u8> {
    fn encode_u32(&mut self, mut value: u32) {
        loop {
            let mut byte = (value & 0x7F) as u8;
            value >>= 7;
            if value != 0 {
                byte |= 0x80;
            }
            self.push(byte);
            if value == 0 {
                break;
            }
        }
    }

    fn encode_u64(&mut self, mut value: u64) {
        loop {
            let mut byte = (value & 0x7F) as u8;
            value >>= 7;
            if value != 0 {
                byte |= 0x80;
            }
            self.push(byte);
            if value == 0 {
                break;
            }
        }
    }

    fn encode_signed_i32(&mut self, value: i32) {
        self.encode_signed_i64(i64::from(value));
    }

    fn encode_signed_i64(&mut self, mut value: i64) {
        loop {
            let byte = (value & 0x7F) as u8;
            value >>= 7;
            let done = (value == 0 && byte & 0x40 == 0) || (value == -1 && byte & 0x40 != 0);
            self.push(if done { byte } else { byte | 0x80 });
            if done {
                break;
            }
        }
    }

    fn encode_name(&mut self, name: &str) {
        self.encode_u32(name.len() as u32);
        self.extend_from_slice(name.as_bytes());
    }

    fn encode_values(&mut self, values: &[CoredumpValue]) {
        self.encode_u32(values.len() as u32);
        for value in values {
            match *value {
                CoredumpValue::I32(value) => {
                    self.push(0x7F);
                    self.encode_signed_i32(value);
                }
                CoredumpValue::I64(value) => {
                    self.push(0x7E);
                    self.encode_signed_i64(value);
                }
                CoredumpValue::F32(value) => {
                    self.push(0x7D);
                    self.extend_from_slice(&value.to_le_bytes());
                }
                CoredumpValue::F64(value) => {
                    self.push(0x7C);
                    self.extend_from_slice(&value.to_le_bytes());
                }
                CoredumpValue::Unknown => {
                    self.push(0x01);
                }
            }
        }
    }

    fn encode_custom_section(&mut self, name: &str, payload: &[u8]) {
        self.push(0x00);
        let mut section = Vec::new();
        section.encode_name(name);
        section.extend_from_slice(payload);
        self.encode_u32(section.len() as u32);
        self.extend_from_slice(&section);
    }

    fn encode_standard_section(&mut self, id: u8, payload: &[u8]) {
        self.push(id);
        self.encode_u32(payload.len() as u32);
        self.extend_from_slice(payload);
    }
}
