"""Context lifting: generated commuting-path obligations for embedded runtimes.

No expected outputs, pilot identifiers, target test names, or reference changes
are inputs. Seeds are the retrieval artifact's first ten test excerpts. The two
small language adapters implement one equation: observe(execute(lift(x))) ==
observe(lift(execute(x))). Go crosses the host/guest or clone boundary; schema
composition compares recursive resolution with finite syntactic unfolding.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from anchor_retrieval.syntax import Source, call_parts, child, walk


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:12]


def _seeds(retrieval: Path | dict, top_k: int) -> list[dict]:
    data = json.loads(retrieval.read_text()) if isinstance(retrieval, Path) else retrieval
    return data["selected_tests"][:top_k]


def _provenance(seed: dict) -> dict:
    return {key: seed.get(key) for key in ("rank", "path", "line", "name", "test_id")}


def _toplevel_bindings(code: str) -> list[dict]:
    """Lexical scope scan, preserving positions while masking strings/comments.

    Tengo's short declaration/function syntax is a strict subset for this
    transformation. We only export top-level declarations; statements are kept
    byte-for-byte in the lifted body. Imports/export and free callback bindings
    can still be unsupported and are recorded as invalid at runtime.
    """
    masked = list(code)
    for match in re.finditer(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', code):
        for index in range(match.start(), match.end()):
            if masked[index] != "\n":
                masked[index] = " "
    clean = "".join(masked)
    depth = 0
    depths = []
    for character in clean:
        depths.append(depth)
        if character in "{[":
            depth += 1
        elif character in "}]":
            depth -= 1
    output = []
    for match in re.finditer(r"\b([A-Za-z_]\w*)\s*:=\s*", clean):
        if depths[match.start()] != 0:
            continue
        tail = clean[match.end():]
        function = re.match(r"func\s*\(([^)]*)\)", tail)
        scalar = re.match(r"(?:-?\d+(?:\.\d+)?|true|false)\b", tail)
        # Reading every declared scalar through an extra closure creates a
        # second use of its cell. It does not assert any particular value.
        output.append({"name": match.group(1), "function": bool(function),
                       "scalar": bool(scalar), "offset": match.start()})
    return output


def _guest_free_identifiers(code: str, builtin_names: set[str]) -> list[str]:
    """Conservative lexical precondition for self-contained embedded programs.

    This is not name resolution for arbitrary Tengo. It recognizes declarations,
    parameters, iteration bindings, and member/map-key positions in the small
    extracted subset. Unknown host callbacks are rejected with evidence instead
    of turning a missing test fixture into a defect signal.
    """
    clean = re.sub(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', " ", code)
    declared = set(re.findall(r"\b([A-Za-z_]\w*)\s*:=", clean))
    for match in re.finditer(r"\bfunc\s*\(([^)]*)\)", clean):
        declared.update(re.findall(r"[A-Za-z_]\w*", match.group(1)))
    for match in re.finditer(r"\bfor\s+([\w\s,]+?)\s+in\b", clean):
        declared.update(re.findall(r"[A-Za-z_]\w*", match.group(1)))
    keywords = {"func", "return", "if", "else", "for", "in", "break", "continue",
                "true", "false", "undefined", "import", "export"}
    unknown = set()
    for match in re.finditer(r"\b[A-Za-z_]\w*\b", clean):
        name = match.group()
        if name in declared | builtin_names | keywords:
            continue
        before, after = clean[:match.start()].rstrip(), clean[match.end():].lstrip()
        if before.endswith(".") or (after.startswith(":") and not after.startswith(":=")):
            continue
        unknown.add(name)
    return sorted(unknown)


def mine_go_programs(retrieval: Path | dict, top_k: int = 10) -> tuple[list[dict], list[dict]]:
    programs, rejected, seen = [], [], set()
    for seed in _seeds(retrieval, top_k):
        source = Source(seed.get("path", "seed.go"), seed["code"], "go")
        for node in walk(source.root):
            if node.type != "raw_string_literal":
                continue
            code = source.text(node)[1:-1]
            identifier = _digest(code.strip())
            if identifier in seen:
                continue
            seen.add(identifier)
            bindings = _toplevel_bindings(code)
            evidence = {"seed": _provenance(seed), "snippet_line": seed.get("line", 1) + node.start_point.row,
                        "snippet_sha256": hashlib.sha256(code.encode()).hexdigest()}
            if not any(binding["function"] for binding in bindings):
                rejected.append({**evidence, "reason": "no top-level function declaration"})
                continue
            if re.search(r"\b(import|export)\b", code):
                rejected.append({**evidence, "reason": "external module setup is not reconstructed"})
                continue
            names = [binding["name"] for binding in bindings]
            observers = [binding["name"] for binding in bindings if binding["scalar"]]
            # Export all declarations so functions produced by other functions
            # and functions nested in pre-existing containers remain reachable.
            entries = [json.dumps(name) + ": " + name for name in names]
            entries += [json.dumps("__observe_" + name) + ": func() { return " + name + " }" for name in observers]
            lifted = "__cc_factory := func() {\n" + code + "\nreturn {" + ", ".join(entries) + "}\n}\n"
            direct = code + "\n__cc_bundle := {" + ", ".join(entries) + "}\n"
            programs.append({"id": "scope_" + identifier, "source": code, "lifted": lifted, "direct": direct,
                             "bindings": bindings, "observers": observers, "evidence": evidence})
    return programs, rejected


_GO_RUNTIME = r'''// Generated by context lifting; expected results come from alternate execution paths.
package tengo_test

import (
  "encoding/json"
  "fmt"
  "reflect"
  "sort"
  "strings"
  "testing"
  tengo "__MODULE__"
)

type ccProgram struct { ID, Source, Direct string }
type ccResult struct { ID string `json:"id"`; Status string `json:"status"`; Relation string `json:"relation"`; Observed interface{} `json:"observed,omitempty"`; Expected interface{} `json:"expected,omitempty"`; Details string `json:"details,omitempty"`; ControlID string `json:"control_id,omitempty"`; IsControl bool `json:"is_control,omitempty"` }
func ccEmit(t *testing.T, r ccResult) {
  raw, _ := json.Marshal(r); fmt.Printf("CC_RESULT %s\n", raw)
  if r.Status == "violation" { t.Errorf("%s: %v != %v (%s)", r.ID, r.Observed, r.Expected, r.Details) }
}
func ccRun(source string) (out *tengo.Compiled, err error) {
  defer func(){ if p:=recover(); p!=nil { err=fmt.Errorf("panic: %v",p) } }()
  return tengo.NewScript([]byte(source)).Run()
}
func ccCall(fn tengo.Object, args ...tengo.Object) (out tengo.Object, err error) {
  defer func(){ if p:=recover(); p!=nil { err=fmt.Errorf("panic: %v",p) } }()
  if fn == nil || !fn.CanCall() { return nil, fmt.Errorf("not callable: %T", fn) }
  return fn.Call(args...)
}
func ccError(err error) string {
  if err==nil {return ""}; return strings.Split(err.Error(),"\n")[0]
}
func ccOutcome(value tengo.Object, err error) interface{} {
  if err!=nil {return map[string]interface{}{"error":ccError(err)}}; return ccValue(value)
}
func ccArgs(fn tengo.Object) ([]tengo.Object, string, bool) {
  f, ok := fn.(*tengo.CompiledFunction); if !ok { return nil,"",false }
  n:=f.NumParameters; if f.VarArgs { n-- }; if n<0 || n>3 { return nil,"",false }
  args:=make([]tengo.Object,n); literals:=make([]string,n)
  for i:=range args { args[i]=&tengo.Int{Value:1}; literals[i]="1" }
  return args, strings.Join(literals, ","), true
}
func ccValue(o tengo.Object) interface{} {
  if o==nil { return "<nil>" }
  switch v:=o.(type) {
  case *tengo.Array: a:=make([]interface{},len(v.Value)); for i,x:=range v.Value { a[i]=ccValue(x) }; return a
  case *tengo.Map: m:=map[string]interface{}{}; for k,x:=range v.Value { m[k]=ccValue(x) }; return m
  case *tengo.CompiledFunction: return "<callable>"
  default: return fmt.Sprintf("%T:%s",o,o.String())
  }
}
func ccBundle(c *tengo.Compiled) (*tengo.Map,error) {
  m,ok:=c.Get("__cc_bundle").Object().(*tengo.Map); if !ok { return nil,fmt.Errorf("bundle has type %T",c.Get("__cc_bundle").Object()) }; return m,nil
}
func ccNames(m *tengo.Map, observers bool) []string {
  names:=[]string{}; for k,v:=range m.Value { if v.CanCall() && (strings.HasPrefix(k,"__observe_")==observers) { names=append(names,k) } }; sort.Strings(names); return names
}
func ccObserve(m *tengo.Map) (map[string]interface{},error) {
  out:=map[string]interface{}{}; for _,k:=range ccNames(m,true) { v,e:=ccCall(m.Value[k]); if e!=nil { return nil,e }; out[k]=ccValue(v) }; return out,nil
}
func ccTrace(m *tengo.Map, name string) ([]interface{},error) {
  fn:=m.Value[name]; args,_,ok:=ccArgs(fn); if !ok { return nil,fmt.Errorf("unsupported call signature") }
  out:=[]interface{}{}; for i:=0;i<2;i++ { v,callErr:=ccCall(fn,args...); observation,e:=ccObserve(m); if e!=nil{return nil,e}; out=append(out,ccOutcome(v,callErr),observation) }; return out,nil
}
type ccStep struct { Kind string; Key string; Index int; Args []tengo.Object; ArgText string }
type ccPath struct { Suffix string; Steps []ccStep; Depth int }
func ccPathValue(value tengo.Object, steps []ccStep) (out tengo.Object, err error) {
  defer func(){if p:=recover();p!=nil{out=nil;err=fmt.Errorf("panic: %v",p)}}()
  for _,step:=range steps {
    var err error
    switch step.Kind {
    case "call": value,err=ccCall(value,step.Args...)
    case "key": value,err=value.IndexGet(&tengo.String{Value:step.Key})
    case "index": value,err=value.IndexGet(&tengo.Int{Value:int64(step.Index)})
    }
    if err!=nil {return nil,err}
  }; return value,nil
}
func ccChildren(value tengo.Object, path ccPath) []ccPath {
  if path.Depth>=2 {return nil}; children:=[]ccPath{}
  add:=func(suffix string,step ccStep) {steps:=append([]ccStep{},path.Steps...); steps=append(steps,step); children=append(children,ccPath{path.Suffix+suffix,steps,path.Depth+1})}
  switch v:=value.(type) {
  case *tengo.CompiledFunction: args,text,ok:=ccArgs(v); if ok {add("("+text+")",ccStep{Kind:"call",Args:args,ArgText:text})}
  case *tengo.Array: for i:=range v.Value {if i>=4 {break}; add(fmt.Sprintf("[%d]",i),ccStep{Kind:"index",Index:i})}
  case *tengo.Map: keys:=[]string{};for key:=range v.Value{keys=append(keys,key)};sort.Strings(keys);for i,key:=range keys{if i>=4{break};add("["+fmt.Sprintf("%q",key)+"]",ccStep{Kind:"key",Key:key})}
  }; return children
}
func ccHostBundle(p ccProgram, control bool) (*tengo.Map,error) {
  if control {c,e:=ccRun(p.Direct);if e!=nil{return nil,e};return ccBundle(c)}
  c,e:=ccRun(p.Source);if e!=nil{return nil,e};obj,e:=ccCall(c.Get("__cc_factory").Object());if e!=nil{return nil,e}
  m,ok:=obj.(*tengo.Map);if !ok{return nil,fmt.Errorf("factory returned %T",obj)};return m,nil
}
func ccCheckCalls(t *testing.T,p ccProgram,name string,fn tengo.Object,control bool) {
  initialized:=p.Source+"\n__cc_bundle := __cc_factory()\n";prefix:=p.ID+"/call/"+name
  if control {initialized=p.Direct;prefix=p.ID+"/control_call/"+name}
  args,argText,ok:=ccArgs(fn);if !ok{return};root:="__cc_bundle["+fmt.Sprintf("%q",name)+"]"
  queue:=[]ccPath{{"("+argText+")",[]ccStep{{Kind:"call",Args:args,ArgText:argText}},0}}
  for len(queue)>0 {
    path:=queue[0];queue=queue[1:];oracle,oracleErr:=ccRun(initialized+"\n__cc_observed := "+root+path.Suffix+"\n");var expectedObject tengo.Object
    if oracleErr==nil {expectedObject=oracle.Get("__cc_observed").Object();queue=append(queue,ccChildren(expectedObject,path)...)}
    t.Run(prefix+path.Suffix,func(t *testing.T){
      host,e:=ccHostBundle(p,control);var actual tengo.Object;if e==nil{actual,e=ccPathValue(host.Value[name],path.Steps)}
      expected:=ccOutcome(expectedObject,oracleErr);observed:=ccOutcome(actual,e);status:="pass";if !reflect.DeepEqual(expected,observed){status="violation"}
      controlID:="";if !control{controlID=p.ID+"/control_call/"+name+path.Suffix}
      ccEmit(t,ccResult{ID:prefix+path.Suffix,Status:status,Relation:"host_guest",Observed:observed,Expected:expected,ControlID:controlID,IsControl:control})
    })
  }
}
func ccCheckClone(t *testing.T,p ccProgram,name string,control bool) {
  initialized:=p.Source+"\n__cc_bundle := __cc_factory()\n";id:=p.ID+"/clone/"+name
  if control{initialized=p.Direct;id=p.ID+"/control_clone/"+name}
  t.Run(id,func(t *testing.T){
    result:=ccResult{ID:id,Status:"invalid",Relation:"clone_fresh",IsControl:control};if !control{result.ControlID=p.ID+"/control_clone/"+name}
    original,e:=ccRun(initialized);if e!=nil{result.Details=e.Error();ccEmit(t,result);return}
    fresh,e:=ccRun(initialized);if e!=nil{result.Details=e.Error();ccEmit(t,result);return}
    sourceMap,e:=ccBundle(original);if e!=nil{result.Details=e.Error();ccEmit(t,result);return}
    before,e:=ccObserve(sourceMap);if e!=nil{result.Details=e.Error();ccEmit(t,result);return}
    freshMap,e:=ccBundle(fresh);if e!=nil{result.Details=e.Error();ccEmit(t,result);return}
    expected,e:=ccTrace(freshMap,name);if e!=nil{result.Details=e.Error();ccEmit(t,result);return}
    cloned:=original.Clone();cloneMap,e:=ccBundle(cloned);if e!=nil{result.Status="violation";result.Details=e.Error();ccEmit(t,result);return}
    observed,e:=ccTrace(cloneMap,name);after,observeErr:=ccObserve(sourceMap);result.Status="pass"
    if e!=nil{result.Status="violation";result.Details=e.Error()}else if observeErr!=nil{result.Status="violation";result.Details=observeErr.Error()}else if !reflect.DeepEqual(expected,observed)||!reflect.DeepEqual(before,after){result.Status="violation"}
    result.Observed=[]interface{}{observed,after};result.Expected=[]interface{}{expected,before};ccEmit(t,result)
  })
}
func TestCombinationContext(t *testing.T) {
  for _,p:=range []ccProgram{__PROGRAMS__} {
    p:=p
    t.Run(p.ID,func(t *testing.T){
      initialized:=p.Source+"\n__cc_bundle := __cc_factory()\n"
      guest,err:=ccRun(initialized)
      if err!=nil { ccEmit(t,ccResult{ID:p.ID+"/seed",Status:"invalid",Relation:"scope_lift",Details:err.Error()}); return }
      guestMap,err:=ccBundle(guest)
      if err!=nil { ccEmit(t,ccResult{ID:p.ID+"/seed",Status:"invalid",Relation:"scope_lift",Details:err.Error()}); return }
      for _,name:=range ccNames(guestMap,false) {
        ccCheckCalls(t,p,name,guestMap.Value[name],true)
        ccCheckCalls(t,p,name,guestMap.Value[name],false)
        ccCheckClone(t,p,name,true)
        ccCheckClone(t,p,name,false)
      }
    })
  }
}
'''


def generate_go(repository: Path, retrieval: Path | dict, top_k: int = 10) -> dict:
    programs, rejected = mine_go_programs(retrieval, top_k)
    builtin_path = repository / "builtins.go"
    builtins = set(re.findall(r'Name:\s*"([A-Za-z_]\w*)"', builtin_path.read_text())) if builtin_path.exists() else set()
    supported = []
    for program in programs:
        missing = _guest_free_identifiers(program["source"], builtins)
        if missing:
            rejected.append({**program["evidence"], "reason": "unreconstructed external bindings", "identifiers": missing})
        else:
            supported.append(program)
    programs = supported
    module_match = re.search(r"(?m)^module\s+(\S+)", (repository / "go.mod").read_text())
    if not module_match:
        raise ValueError("Go module declaration is missing")
    entries = ",\n".join("{" + json.dumps(p["id"]) + "," + json.dumps(p["lifted"]) + "," + json.dumps(p["direct"]) + "}" for p in programs)
    if entries:
        entries += ","
    content = _GO_RUNTIME.replace("__MODULE__", module_match.group(1)).replace("__PROGRAMS__", entries)
    return {"files": {"combination_context_generated_test.go": content},
            "command": "go test -run '^TestCombinationContext$' -count=1 -v -timeout 120s .",
            "report_format": "jsonl", "report_path": "stdout.txt",
            "metadata": {"adapter": "go_context_lift", "top_k": top_k, "programs": programs, "rejected": rejected,
                         "oracle": "alternate execution of the same lifted source; no expected output literals",
                         "bounds": {"integer_argument": 1, "max_arity": 3, "trace_repetitions": 2,
                                    "returned_value_depth": 2, "container_width": 4}}}


def _pure_object_extension(source: Source, arrow) -> str | None:
    params = child(arrow, "parameters")
    if params is None or len(params.named_children) != 1:
        return None
    param = child(params.named_children[0], "pattern")
    if param is None or param.type != "identifier":
        return None
    body = child(arrow, "body")
    if body is not None and body.type == "parenthesized_expression":
        body = body.named_children[0]
    if body is None or body.type != "object":
        return None
    spread = [item for item in body.named_children if item.type == "spread_element"]
    additions = [item for item in body.named_children if item.type == "pair"]
    if len(spread) != 1 or not additions or source.text(spread[0].named_children[0]) != source.text(param):
        return None
    if body.named_children[0] != spread[0]:
        return None  # spread must precede writes to retain an observable change
    for pair in additions:
        key = child(pair, "key")
        value = child(pair, "value")
        if key is None or key.type not in {"property_identifier", "string", "number"}:
            return None
        if value is None or value.type not in {"string", "number", "true", "false", "null"}:
            return None
    if len(spread) + len(additions) != len(body.named_children):
        return None
    expression = source.text(body)
    # Replace only the single spread identifier, never property names/literals.
    relative_start = spread[0].named_children[0].start_byte - body.start_byte
    relative_end = spread[0].named_children[0].end_byte - body.start_byte
    raw = expression.encode()
    expression = (raw[:relative_start] + b"__cc_value" + raw[relative_end:]).decode()
    return "transform((__cc_value: any) => (" + expression + "))"


def mine_ts_donors(repository: Path) -> list[dict]:
    donors, seen = [], set()
    for path in sorted(repository.glob("library/src/**/*.test.ts")):
        source = Source(str(path.relative_to(repository)), path.read_text(), "typescript")
        for node in walk(source.root):
            if node.type != "call_expression":
                continue
            fn, arguments = call_parts(node)
            if source.text(fn) != "transform" or len(arguments) != 1 or arguments[0].type != "arrow_function":
                continue
            expression = _pure_object_extension(source, arguments[0])
            if expression and expression not in seen:
                seen.add(expression)
                donors.append({"expression": expression, "path": source.path, "line": node.start_point.row + 1,
                               "source": source.text(node), "proof": "object spread followed by constant property writes"})
    return donors


def mine_ts_schemas(retrieval: Path | dict, top_k: int = 10) -> list[dict]:
    schemas, seen = [], set()
    for seed in _seeds(retrieval, top_k):
        source = Source(seed.get("path", "seed.ts"), seed["code"], "typescript")
        declarations = {}
        for node in walk(source.root):
            if node.type == "variable_declarator":
                declarations[source.text(child(node, "name"))] = child(node, "value")
        for name, node in declarations.items():
            if node is None or node.type != "call_expression":
                continue
            fn, args = call_parts(node)
            wrapper = source.text(fn)
            if wrapper not in {"recursive", "recursiveAsync"} or len(args) != 1:
                continue
            expression = source.text(args[0])
            if not re.search(r"\bRecur\b", expression):
                continue
            # Locate the test's parse(schema, input) observation, not a variable
            # called "input". Input must be a self-contained object literal.
            for call in walk(source.root):
                if call.type != "call_expression":
                    continue
                parse_fn, parse_args = call_parts(call)
                if source.text(parse_fn) not in {"parse", "parseAsync"} or len(parse_args) < 2 or source.text(parse_args[0]) != name:
                    continue
                value = parse_args[1]
                if value.type == "identifier":
                    value = declarations.get(source.text(value))
                if value is None or value.type != "object":
                    continue
                input_expression = source.text(value)
                identity = _digest(wrapper + expression + input_expression)
                if identity not in seen:
                    seen.add(identity)
                    schemas.append({"id": "schema_" + identity, "wrapper": wrapper, "body": expression,
                                    "input": input_expression, "evidence": _provenance(seed)})
    return schemas


def generate_typescript(repository: Path, retrieval: Path | dict, top_k: int = 10) -> dict:
    seeds = mine_ts_schemas(retrieval, top_k)
    donors = mine_ts_donors(repository)
    imports = {"Recur", "parseAsync", "never", "pipe", "pipeAsync", "transform"}
    obligations, blocks = [], []
    for seed in seeds:
        imports.add(seed["wrapper"])
        imports.update(re.findall(r"\b([A-Za-z_]\w*)\s*\(", seed["body"]))
        for donor in [None] + donors:
            identifier = seed["id"] + ("/identity" if donor is None else "/extend_" + _digest(donor["expression"]))
            control_id = None if donor is None else seed["id"] + "/identity"
            record_context = ", is_control:" + ("true" if donor is None else "false")
            if control_id is not None:
                record_context += ", control_id:" + json.dumps(control_id)
            body = re.sub(r"\bRecur\b", "__cc_self", seed["body"])
            unmodified_body = body
            if donor is not None:
                composition = "pipeAsync" if seed["wrapper"].endswith("Async") else "pipe"
                body = composition + "(" + body + ", " + donor["expression"] + ")"
            obligations.append({"id": identifier, "relation": "recursive_unfold", "seed": seed["evidence"],
                                "donor": donor, "unfold_depth": 8, "control_id": control_id,
                                "is_control": donor is None})
            nonvacuity = ""
            if donor is not None:
                nonvacuity = f'''
  const unmodified = (__cc_self: any): any => ({unmodified_body});
  let baseline: any = never();
  for (let depth = 0; depth < 8; depth++) baseline = unmodified(baseline);
  let baselineOutput: any;
  try {{ baselineOutput = await parseAsync(baseline, structuredClone(input)); }}
  catch (error) {{
    console.log('CC_RESULT ' + JSON.stringify({{id:{json.dumps(identifier)}, status:'invalid', relation:'recursive_unfold', details:'Unfolded baseline failed: ' + String(error){record_context}}}));
    return;
  }}
  if (isDeepStrictEqual(expected, baselineOutput)) {{
    console.log('CC_RESULT ' + JSON.stringify({{id:{json.dumps(identifier)}, status:'invalid', relation:'recursive_unfold', details:'Donor has no observable effect on this input'{record_context}}}));
    return;
  }}
'''
            blocks.append(f'''test({json.dumps(identifier)}, async () => {{
  const input = {seed['input']};
  const build = (__cc_self: any): any => ({body});
  let explicit: any = never();
  for (let depth = 0; depth < 8; depth++) explicit = build(explicit);
  let expected: any;
  try {{ expected = await parseAsync(explicit, structuredClone(input)); }}
  catch (error) {{ console.log('CC_RESULT ' + JSON.stringify({{id: {json.dumps(identifier)}, status:'invalid', relation:'recursive_unfold', details:String(error){record_context}}})); return; }}
{nonvacuity}
  try {{
    const actual = await parseAsync({seed['wrapper']}(build(Recur)), structuredClone(input));
    expect(actual).toStrictEqual(expected);
    console.log('CC_RESULT ' + JSON.stringify({{id: {json.dumps(identifier)}, status:'pass', relation:'recursive_unfold', observed:actual, expected{record_context}}}));
  }} catch(error) {{
    console.log('CC_RESULT ' + JSON.stringify({{id: {json.dumps(identifier)}, status:'violation', relation:'recursive_unfold', expected, details:String(error){record_context}}}));
    throw error;
  }}
}});''')
    content = "// Generated by finite context unfolding; no expected output literals.\n"
    content += "import { expect, test } from 'vitest';\n"
    content += "import { isDeepStrictEqual } from 'node:util';\n"
    content += "import { " + ", ".join(sorted(imports)) + " } from './index.ts';\n\n" + "\n\n".join(blocks) + "\n"
    return {"files": {"library/src/combination.context.generated.test.ts": content},
            "command": "pnpm --dir library exec vitest run src/combination.context.generated.test.ts",
            "report_format": "jsonl", "report_path": "stdout.txt",
            "metadata": {"adapter": "typescript_context_unfold", "top_k": top_k,
                         "seeds": seeds, "donors": donors, "obligations": obligations,
                         "oracle": "finite syntactic unfolding followed by ordinary parsing"}}


def generate_structural(repository: Path, language: str, retrieval: Path | dict, top_k: int = 10) -> dict:
    """Return files and command for the runner's immutable artifact manifest."""
    if language == "go":
        return generate_go(repository, retrieval, top_k)
    if language == "typescript":
        return generate_typescript(repository, retrieval, top_k)
    raise ValueError(f"Unsupported structural adapter: {language}")
