"""Observed assertion storage origins, restricted to instrumented Python code.

This independent prototype never changes an assertion or evaluates a getter.
Only eager, side-effect-free assertion operand syntax is supported. An event's
writer is the last *observed* direct assignment to this exact instance, not a
closed-world claim about arbitrary Python or native extensions. Same-value
unobserved writes, threads, source introspection and dynamic monkeypatching are
outside the guarantee. Weak references avoid extending subject object lifetime.

The runtime part is standard-library-only and may be copied as one helper file.
The offline planner imports assertion_write_origin lazily; it executes no subject
code. Every span and checksum in a plan refers to the unmodified input source.
"""
from __future__ import annotations

import ast
import hashlib
import json
import math
import os
from pathlib import Path
import types
import weakref


_MISSING = object()


def _identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:24]


def _value(value):
    kind = type(value)
    if value is _MISSING:
        return {'status': 'unknown', 'reason': 'field_absent_from_instance_dict'}
    if kind in {bool, int, str, type(None)}:
        return {'status': 'observed', 'type': kind.__name__, 'value': value}
    if kind is float and math.isfinite(value):
        return {'status': 'observed', 'type': 'float', 'value': value}
    if kind is bytes:
        return {'status': 'observed', 'type': 'bytes', 'hex': value.hex()}
    return {'status': 'unknown', 'reason': 'non_scalar_storage_value'}


def _storage(obj, field):
    """Read only an actual native __dict__ descriptor, never a Python getter."""
    cls = type(obj)
    for base in type.__getattribute__(cls, '__mro__'):
        namespace = type.__getattribute__(base, '__dict__')
        for special in ('__getattribute__', '__setattr__', '__delattr__'):
            if special in namespace and namespace[special] is not getattr(object, special):
                return None, 'dynamic_instance_attribute_protocol'
        if '__getattr__' in namespace:
            return None, 'dynamic_instance_attribute_protocol'
        descriptor_type = type(namespace[field]) if field in namespace else None
        if descriptor_type is not None and any('__get__' in type.__getattribute__(owner, '__dict__')
                for owner in type.__getattribute__(descriptor_type, '__mro__')):
            return None, 'storage_field_has_descriptor'
    for base in type.__getattribute__(cls, '__mro__'):
        namespace = type.__getattribute__(base, '__dict__')
        if '__dict__' not in namespace:
            continue
        descriptor = namespace['__dict__']
        if type(descriptor) is not types.GetSetDescriptorType:
            return None, 'non_native_instance_dict'
        data = descriptor.__get__(obj, cls)
        if type(data) is not dict:
            return None, 'non_native_instance_dict'
        return dict.get(data, field, _MISSING), None
    return None, 'instance_has_no_dict'


class Observer:
    def __init__(self, trace_path=None):
        self.events, self.classes, self.objects = [], {}, {}
        self.next_object, self.sequence = 0, 0
        self.trace_path = Path(trace_path) if trace_path else None

    def _emit(self, event):
        self.sequence += 1
        event = {'sequence': self.sequence, **event}
        self.events.append(event)
        if self.trace_path is not None:
            self.trace_path.parent.mkdir(parents=True, exist_ok=True)
            with self.trace_path.open('a') as stream:
                stream.write(json.dumps(event, sort_keys=True)+'\n')
        return event

    def register_class(self, cls, class_id):
        # An exact registered type prevents similarly named fields in unrelated
        # classes or subclasses from sharing an observed writer.
        if type(cls) is type:
            self.classes[class_id] = weakref.ref(cls)

    def _object(self, obj, class_id):
        expected = self.classes.get(class_id)
        if expected is None or expected() is not type(obj):
            return None, 'runtime_type_not_registered_bound_class'
        key = id(obj)
        prior = self.objects.get(key)
        if prior is not None and prior['reference']() is obj:
            return prior, None
        try:
            reference = weakref.ref(obj)
        except TypeError:
            return None, 'instance_not_weak_referenceable'
        self.next_object += 1
        record = dict(reference=reference, token=self.next_object,
                      allocation=None, writes={})
        self.objects[key] = record
        return record, None

    def constructed(self, obj, site):
        record, error = self._object(obj, site['class_id'])
        if record is not None:
            record['allocation'] = site['allocation_span']
            self._emit(dict(kind='construction', object_token=record['token'],
                            class_id=site['class_id'], allocation_span=record['allocation']))
        return obj

    def after_write(self, obj, site):
        record, error = self._object(obj, site['class_id'])
        value, issue = _storage(obj, site['storage_field']) if record else (None, error)
        if issue:
            self._emit(dict(kind='write_unknown', site=site, reason=issue))
            return
        observed = _value(value)
        event = self._emit(dict(kind='write', object_token=record['token'],
            class_id=site['class_id'], field=site['storage_field'],
            writer_span=site['writer_span'], value=observed,
            source_writer_span=site.get('source_writer_span'),
            source_writer_sha256=site.get('source_writer_sha256')))
        record['writes'][site['storage_field']] = event

    def before_assert(self, obj, site):
        record, error = self._object(obj, site['class_id'])
        value, issue = _storage(obj, site['storage_field']) if record else (None, error)
        observed = _value(value) if issue is None else {'status': 'unknown', 'reason': issue}
        writer = record['writes'].get(site['storage_field']) if record else None
        reason = issue
        if reason is None and writer is None:
            reason = 'no_observed_write'
        if reason is None and record['allocation'] != site['allocation_span']:
            reason = 'runtime_allocation_not_observed_at_bound_site'
        if reason is None and (observed['status'] != 'observed' or writer['value']['status'] != 'observed'):
            reason = 'storage_value_not_comparable_without_user_code'
        if reason is None and writer['value'] != observed:
            reason = 'storage_changed_since_last_observed_write'
        self._emit(dict(kind='assertion_read', q_span=site['q_span'],
            read_span=site['read_span'], field=site['storage_field'],
            observed_field=site['observed_field'], class_id=site['class_id'],
            object_token=record['token'] if record else None,
            allocation_span=record['allocation'] if record else None,
            status='observed_within_instrumented_code' if reason is None else 'unknown',
            reason=reason, value=observed,
            last_observed_writer=writer['writer_span'] if writer else None,
            writer_event_sequence=writer['sequence'] if writer else None,
            source_q_span=site.get('source_q_span'),
            source_q_sha256=site.get('source_q_sha256'),
            source_allocation_span=site.get('source_allocation_span'),
            source_allocation_sha256=site.get('source_allocation_sha256'),
            source_last_observed_writer=writer.get('source_writer_span') if writer else None,
            source_last_observed_writer_sha256=writer.get('source_writer_sha256') if writer else None,
            source_assertion_edited=site.get('source_assertion_edited'),
            source_assertion_edit_roles=site.get('source_assertion_edit_roles'),
            complete_external_write_coverage=False))


observer = Observer(os.environ.get('OBSERVED_WRITE_TRACE'))


def _eager_operand(node):
    return (isinstance(node, (ast.Name, ast.Constant)) or
            isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name))


def _eager_assertion(node):
    expression = node.test
    if _eager_operand(expression):
        return True
    if isinstance(expression, ast.UnaryOp) and isinstance(expression.op, ast.Not):
        return _eager_operand(expression.operand)
    return (isinstance(expression, ast.Compare) and len(expression.ops) == 1
            and _eager_operand(expression.left) and _eager_operand(expression.comparators[0]))


def build_plan(sources, *, assertion_paths=None, assertion_functions=None):
    from prototypes.assertion_write_origin import Index, analyze_assertion
    index = Index(sources)
    selected_paths = set(assertion_paths) if assertion_paths is not None else set(index.paths)
    queries, writes, allocations, classes, unsupported, enumerated = [], {}, {}, {}, [], []
    for path, module in sorted(index.paths.items()):
        if path not in selected_paths:
            continue
        for node in ast.walk(module.tree):
            if not isinstance(node, ast.Assert):
                continue
            q_span = module.span(node)
            if assertion_functions is not None and not any(
                    isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and function.name in assertion_functions.get(path, [])
                    and function.lineno <= node.lineno <= function.end_lineno
                    for function in ast.walk(module.tree)):
                continue
            enumerated.append(q_span)
            if not _eager_assertion(node):
                unsupported.append(dict(q_span=q_span, reason='assertion_read_may_short_circuit_or_have_effects'))
                continue
            try:
                analysis = analyze_assertion(sources, path, node.lineno, index=index,
                    assertion_start_byte=q_span['start_byte'], include_source_hashes=False)
            except (AttributeError, TypeError) as error:
                unsupported.append(dict(q_span=q_span, reason='static_analyzer_error',
                                        error_type=type(error).__name__))
                continue
            if not analysis['reads']:
                unsupported.append(dict(q_span=q_span, reason=analysis.get('reason') or
                                        analysis.get('unsupported_reason') or 'no_supported_read'))
                continue
            if any(read['status'] != 'statically_bound_partial_slice' for read in analysis['reads']):
                unsupported.append(dict(q_span=q_span, reason='assertion_has_unresolved_read',
                    read_reasons=[read['reason'] for read in analysis['reads']
                                  if read['status'] != 'statically_bound_partial_slice']))
                continue
            for read in analysis['reads']:
                if read['status'] != 'statically_bound_partial_slice':
                    unsupported.append(dict(q_span=q_span, read_span=read['read_span'], reason=read['reason']))
                    continue
                class_id = read['binding']['class_id']
                owner, cls = index.classes[class_id]
                methods = {n.name for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
                if cls.decorator_list or methods & {'__getattribute__', '__getattr__', '__setattr__', '__delattr__'}:
                    unsupported.append(dict(q_span=q_span, reason='dynamic_class_attribute_protocol'))
                    continue
                supported_writes = []
                for writer in read['writers']:
                    statement = next(n for n in ast.walk(owner.tree)
                        if isinstance(n, (ast.Assign, ast.AnnAssign, ast.AugAssign))
                        and owner.span(n) == writer['span'])
                    targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                    if len(targets) != 1 or not isinstance(targets[0], ast.Attribute) or not isinstance(targets[0].value, ast.Name):
                        unsupported.append(dict(q_span=q_span, writer_span=writer['span'], reason='non_single_direct_assignment'))
                        continue
                    site = dict(class_id=class_id, storage_field=read['storage_field'],
                        writer_span=writer['span'], receiver=targets[0].value.id)
                    writes[_identity(site)] = site
                    supported_writes.append(site)
                if not supported_writes:
                    unsupported.append(dict(q_span=q_span, reason='no_supported_writer_sites'))
                    continue
                classes[class_id] = dict(class_id=class_id, class_span=owner.span(cls), name=cls.name)
                allocation = dict(class_id=class_id, allocation_span=read['binding']['allocation_span'])
                allocations[_identity(allocation)] = allocation
                receiver = ast.parse(read['expression'], mode='eval').body.value.id
                queries.append(dict(**allocation, q_span=q_span, read_span=read['read_span'],
                    observed_field=read['observed_field'], storage_field=read['storage_field'],
                    receiver=receiver, property_aliases=read['property_aliases']))
    return dict(version=1, queries=queries, writes=list(writes.values()),
        allocations=list(allocations.values()), classes=list(classes.values()),
        enumerated_assertions=enumerated, unsupported=unsupported, parse_errors=index.parse_errors,
        source_sha256={path:hashlib.sha256(module.code_bytes).hexdigest() for path,module in index.paths.items()},
        guarantee='last_observed_direct_write_within_instrumented_sources_not_global_reaching_definition',
        no_getter_calls=True, original_assertions_unchanged=True)


def instrument_sources(sources, plan, *, runtime_module='__observed_write_runtime'):
    """Return reviewable source overlays; no source is imported or executed."""
    from prototypes.assertion_write_origin import Module
    transformed = {}
    for path, value in sources.items():
        code = value['code'] if isinstance(value, dict) else value
        if path not in plan['source_sha256']:
            continue
        if hashlib.sha256(code.encode()).hexdigest() != plan['source_sha256'][path]:
            raise ValueError('Source changed since instrumentation planning')
        module = Module(path, code, ast.parse(code, filename=path))
        matching = lambda rows, key: [row for row in rows if row[key]['path'] == path]
        queries = matching(plan['queries'], 'q_span')
        writers = matching(plan['writes'], 'writer_span')
        allocations = matching(plan['allocations'], 'allocation_span')
        classes = matching(plan['classes'], 'class_span')
        if not any([queries, writers, allocations, classes]):
            continue
        name = '_owo_'+hashlib.sha256(code.encode()).hexdigest()[:16]
        if any(isinstance(n, ast.Name) and n.id == name for n in ast.walk(module.tree)):
            raise ValueError('Instrumentation binding collides with source')
        def call(method, args, site=None):
            if site is not None:
                args = [*args, ast.parse(repr(site), mode='eval').body]
            return ast.Call(func=ast.Attribute(value=ast.Name(id=name, ctx=ast.Load()),
                            attr=method, ctx=ast.Load()), args=args, keywords=[])
        class Transform(ast.NodeTransformer):
            def visit_Call(self, node):
                span = module.span(node)
                node = self.generic_visit(node)
                matches = [site for site in allocations if site['allocation_span'] == span]
                return call('constructed', [node], matches[0]) if matches else node
            def visit_ClassDef(self, node):
                span = module.span(node)
                node = self.generic_visit(node)
                matches = [site for site in classes if site['class_span'] == span]
                if not matches:
                    return node
                return [node, ast.Expr(call('register_class',
                    [ast.Name(id=node.name, ctx=ast.Load()), ast.Constant(matches[0]['class_id'])]))]
            def visit_Assert(self, node):
                span = module.span(node)
                before = [ast.Expr(call('before_assert', [ast.Name(id=site['receiver'], ctx=ast.Load())], site))
                          for site in queries if site['q_span'] == span]
                # Python -O removes assertions; do not report an observation at
                # a q that the interpreter has removed.
                return [ast.If(test=ast.Name(id='__debug__', ctx=ast.Load()),
                               body=before, orelse=[]), node] if before else node
            def assignment(self, node):
                span = module.span(node)
                node = self.generic_visit(node)
                after = [ast.Expr(call('after_write', [ast.Name(id=site['receiver'], ctx=ast.Load())], site))
                         for site in writers if site['writer_span'] == span]
                return [node, *after]
            visit_Assign = assignment
            visit_AnnAssign = assignment
            visit_AugAssign = assignment
        tree = Transform().visit(module.tree)
        at = 1 if tree.body and isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, ast.Constant) and isinstance(tree.body[0].value.value, str) else 0
        while at < len(tree.body) and isinstance(tree.body[at], ast.ImportFrom) and tree.body[at].module == '__future__':
            at += 1
        tree.body.insert(at, ast.ImportFrom(module=runtime_module,
                         names=[ast.alias(name='observer', asname=name)], level=0))
        ast.fix_missing_locations(tree)
        transformed[path] = ast.unparse(tree)+'\n'
    return transformed
