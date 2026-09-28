"""Source-local creator results and their later receiver/argument references.

A root is a versioned local result binding, not a claim about a runtime type.
Cross-callee payload alignment on that root remains a relation hypothesis.
"""
from __future__ import annotations

from collections import defaultdict

from anchor_retrieval.syntax import CALLS, FUNCTIONS, Source, walk
from .frontend import is_operation_argument


_LEXICAL_SCOPES = {"block", "statement_block", "switch_body"}
_FUNCTION_SCOPES = FUNCTIONS | {"arrow_function", "function_expression", "func_literal", "lambda"}
_DECLARATIONS = {"short_var_declaration", "var_spec", "const_spec", "variable_declarator"}


def _position(row):
    span = row.get("span", row) or {}
    return span.get("path"), span.get("start_byte"), span.get("end_byte")


def operation_eligible(call):
    """Stateful source helpers may both perform an action and check a guard."""
    return call.get("role") == "operation" or call.get("operation_eligible") is True


class ResourceRoots:
    """Index direct creator bindings and source-local alias chains once.

    The supported relation is a call result assigned to a simple local name,
    followed by references to that value as a receiver or explicit actual.
    Multi-result assignments keep each output binding distinct. They do not
    assert that separate results alias. Conditional writes and closure captures
    are explicitly excluded from the exact source binding relation.
    """

    def __init__(self, frontend: dict, sources: dict[str, Source]):
        self.sources = sources
        self.calls = {c["id"]: c for c in frontend.get("calls", ())}
        self.call_positions = {(c["test_id"], _position(c)): c for c in self.calls.values()}
        self.bindings = {b["id"]: b for b in frontend.get("bindings", ())}
        self.by_name = defaultdict(list)
        self.creators = defaultdict(list)
        self.root_bindings = {}
        self._nodes = {}
        self._association_cache = {}
        for binding in self.bindings.values():
            if binding.get("simple_name") and binding.get("name") != "_":
                self.by_name[binding["test_id"], binding["name"]].append(binding)
        for members in self.by_name.values():
            members.sort(key=lambda b: (b["definition_end"], _position(b)))
        for binding in self.bindings.values():
            if not binding.get("simple_name") or binding.get("name") == "_" or binding.get("contexts"):
                continue
            value = binding.get("value") or {}
            if value.get("kind") not in CALLS | {"expression_list"}:
                continue
            call = self.call_positions.get((binding["test_id"], _position(value)))
            if call is None or not operation_eligible(call) or call.get("contexts"):
                continue
            # The value span must be exactly the creator invocation. A call
            # nested inside another expression does not establish this root.
            self.creators[call["id"]].append(binding)
            self.root_bindings[binding["id"]] = (binding, call)

    def _node(self, expression):
        path, start, end = _position(expression)
        if path not in self.sources:
            return None
        if path not in self._nodes:
            nodes = defaultdict(list)
            for node in walk(self.sources[path].root):
                nodes[node.start_byte, node.end_byte].append(node)
            self._nodes[path] = nodes
        choices = self._nodes[path].get((start, end), ())
        kind = expression.get("kind")
        return next((n for n in choices if n.type == kind), choices[-1] if choices else None)

    @staticmethod
    def _scope_chain(node, kinds):
        scopes = []
        while node is not None:
            if node.type in kinds:
                scopes.append((node.type, node.start_byte, node.end_byte))
            node = node.parent
        return scopes

    def _visible(self, binding, reference):
        target = self._node(binding.get("target") or {})
        if target is None or reference is None:
            return False
        target_functions = self._scope_chain(target, _FUNCTION_SCOPES)
        reference_functions = self._scope_chain(reference, _FUNCTION_SCOPES)
        if target_functions[:1] != reference_functions[:1]:
            return False
        path = binding["span"]["path"]
        if self.sources[path].language == "python":
            return True  # Python assignments are local to the function scope.
        statement = self._node(binding)
        # Non-declaration writes may update an outer binding. Keep them as
        # potential barriers even when their block no longer contains the read.
        if statement is not None and statement.type not in _DECLARATIONS:
            return True
        scopes = self._scope_chain(target, _LEXICAL_SCOPES)
        return not scopes or scopes[0] in self._scope_chain(reference, _LEXICAL_SCOPES)

    def _active(self, test_id, name, expression):
        reference = self._node(expression)
        if reference is None:
            return None
        available = [b for b in self.by_name.get((test_id, name), ())
                     if b["definition_end"] <= reference.start_byte and self._visible(b, reference)]
        return available[-1] if available else None

    def _root(self, test_id, expression):
        if not expression or expression.get("kind") != "identifier":
            return None
        binding = self._active(test_id, expression.get("text"), expression)
        chain, seen = [], set()
        while binding is not None and binding["id"] not in seen:
            seen.add(binding["id"])
            if binding.get("contexts"):
                return None
            chain.append(binding)
            if binding["id"] in self.root_bindings:
                return binding, chain
            if not binding.get("alias_name") or not binding.get("projection_known"):
                return None
            binding = self._active(test_id, binding["alias_name"], binding["value"])
        return None

    def _fact(self, binding, creator, call, relation, expression=None, chain=(), slot=None):
        return {
            "root_id": binding["id"], "root_binding_id": binding["id"],
            "root_name": binding["name"], "root_binding_span": binding["span"],
            "creator_call_id": creator["id"], "creator_call_span": creator["span"],
            "call_id": call["id"], "call_span": call["span"],
            "relation": relation, "argument_slot": slot,
            "reference_span": expression.get("span") if expression else None,
            "alias_binding_ids": [b["id"] for b in chain],
            "alias_binding_spans": [b["span"] for b in chain],
            "result_projection": "single_value" if binding.get("projection_known") else "distinct_source_assignment_target",
            "binding_status": "source_local_creator_result_and_reference",
            "runtime_identity": "unknown; source_binding_does_not_prove_resource_semantics",
        }

    def associations(self, call):
        """Return exact source associations, retaining multiple explicit roots."""
        if call["id"] in self._association_cache:
            return self._association_cache[call["id"]]
        if not operation_eligible(call) or call.get("contexts"):
            return []
        facts = [self._fact(b, call, call, "creator_result") for b in self.creators.get(call["id"], ())]
        references = [("receiver_reference", call.get("receiver"), None)]
        references += [("argument_reference", arg, arg["slot"]) for arg in call.get("arguments", ())
                       if not arg.get("spread") and is_operation_argument(call, arg["slot"])]
        for kind, expression, slot in references:
            recovered = self._root(call["test_id"], expression)
            if recovered is None:
                continue
            binding, chain = recovered
            creator = self.root_bindings[binding["id"]][1]
            if creator["span"]["end_byte"] > call["span"]["start_byte"]:
                continue
            facts.append(self._fact(binding, creator, call, kind, expression, chain, slot))
        unique = {}
        for fact in facts:
            unique.setdefault((fact["root_id"], fact["relation"], fact["argument_slot"]), fact)
        self._association_cache[call["id"]] = list(unique.values())
        return self._association_cache[call["id"]]
