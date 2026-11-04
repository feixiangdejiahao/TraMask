"""Cheap relationships for scheduling sliced evidence before composition.

The index orders a complete workset. It does not infer API effects or turn
the slicer's may-alias components into object-identity constraints.
"""
from collections import Counter, defaultdict
import re

from .evidence import MEMBERS
from .issue_filter import rank_lexical
from .anchors import changed_lines,parse_source


def interface_features(graph, nodes):
    """Use existing syntax to expose names, observations and input carriers."""
    calls, fields, observations, names, keys = set(), set(), set(), set(), set()
    for identity in nodes:
        node = graph.nodes[identity]
        names.update(name for _, name in node['uses'] | node['defs'])
        calls.update(name for name, _, _ in node['calls'] if name)
        if node['observation']:
            observations.update(name for _, name in node['uses'])
        pending = [node['ast']]
        while pending:
            ast = pending.pop()
            if ast.type in MEMBERS:
                member = next((ast.child_by_field_name(k) for k in ('attribute','field','property')
                               if ast.child_by_field_name(k) is not None), None)
                if member is not None:
                    fields.add(graph.text(member))
            if ast.type in {'keyword_argument','pair','property_assignment'}:
                key = ast.child_by_field_name('name') or ast.child_by_field_name('key')
                if key is not None:
                    keys.add(graph.text(key).strip('\"\''))
            # A function header references its body, but that body can contain
            # independent tests outside this view's selected statements.
            if ast == node['ast'] and node['kind'] in {'function','class'}:
                body = ast.child_by_field_name('body')
                pending.extend(c for c in ast.named_children if c != body)
            else:
                pending.extend(ast.named_children)
    return {key:sorted(values) for key,values in (
        ('calls',calls),('fields',fields),('observations',observations),('names',names),('keys',keys))}


def text_features(text):
    """Data keys and paths let output/configuration records join the same query."""
    return {'keys':sorted(set(re.findall(r'[\"\']([A-Za-z_][\w.-]*)[\"\']\s*:',text))),
            'paths':sorted(set(re.findall(r'(?:[\w.-]+/)+[\w.-]+',text)))}


def related_order(records, centers, query):
    """Round-robin several concrete connections, then retain the lexical tail."""
    lexical = rank_lexical(records,query)
    by_id = {r['id']:r for r in records}
    rank = {identity:i for i,identity in enumerate(lexical)}
    index = defaultdict(set)
    for record in records:
        for kind, values in record['features'].items():
            for value in values:
                index[kind,value].add(record['id'])
    queues, reasons = [], defaultdict(set)
    for center in centers:
        record = by_id[center]
        signals = {
            'operation':set().union(*(index['calls',v] for v in record['features']['calls'])),
            'observation':set().union(*(index[k,v] for k in ('fields','keys','observations')
                                      for v in record['features']['fields']+record['features']['keys'])),
            'data':set().union(*(index[k,v] for k in ('keys','paths')
                                for v in record['features'][k])),
            'revision':{r['id'] for r in records if r['kind']=='program' and record['kind']=='program'
                        and r['path']==record['path'] and r['boundary']==record['boundary']},
        }
        for kind, identities in signals.items():
            ordered = sorted(identities-{center},key=rank.__getitem__)
            queues.append(ordered)
            for identity in ordered:
                reasons[identity].add(kind+':'+center)
    result, seen = list(centers), set(centers)
    for offset in range(max(map(len,queues),default=0)):
        for queue in queues:
            if offset<len(queue) and queue[offset] not in seen:
                identity=queue[offset];result.append(identity);seen.add(identity)
    result.extend(identity for identity in lexical if identity not in seen)
    return result,{k:sorted(v) for k,v in reasons.items()}


def check_plan(plan, records, issue, patch):
    """Verify cited evidence and order constraints, without judging API laws."""
    by_id = {r['id']:r for r in records}
    text = {identity:r['text'] for identity,r in by_id.items()}
    text.update(issue=issue,patch=patch)
    references = [plan['base']]+plan['sources']
    unknown_ids = sorted(set(references)-text.keys())
    citations = []
    for check in plan['checks']:
        for basis in check['basis']:
            valid = basis['source'] in text and basis['quote'] in text[basis['source']] and bool(basis['quote'])
            citations.append({**basis,'quote_found':valid})
    successors=defaultdict(set);indegree=Counter()
    for before,after in plan['order']:
        if after not in successors[before]:
            successors[before].add(after);indegree[after]+=1
        indegree[before]+=0
    ready=[n for n in indegree if not indegree[n]];visited=0
    while ready:
        node=ready.pop();visited+=1
        for following in successors[node]:
            indegree[following]-=1
            if not indegree[following]:ready.append(following)
    return {'unknown_source_ids':unknown_ids,'citations':citations,
            'order_acyclic':visited==len(indegree),
            'has_check_basis':bool(citations) and all(c['quote_found'] for c in citations),
            'semantic_applicability':'requires_review_and_execution'}


def changed_declaration_names(patch,sources):
    """Names and owners of innermost changed declarations in final source."""
    changes=changed_lines(patch);modified=set()
    for path,raw in sources:
        relative=path.removeprefix('/app/')
        if relative not in changes:continue
        parsed=parse_source(path,raw)
        for line in changes[relative]:
            declarations=[d for d in parsed['declarations'] if d['first_line']<=line<=d['last_line']]
            if declarations:
                declaration=min(declarations,key=lambda d:d['end']-d['start'])
                modified.add(declaration['name'])
                if declaration['owner']:modified.add(declaration['owner'])
    return modified


def select_validation_centers(programs,lexical,changes,modified,limit=4):
    """Prioritize supplied validation units; every other record stays eligible."""
    rank={identity:i for i,identity in enumerate(lexical)}
    operation_frequency=Counter(v for r in programs for v in set(r['features']['calls']+r['features']['fields']))
    def tier(row):
        uses=set(row['features']['calls']+row['features']['fields'])
        affinity=sum(1/operation_frequency[v] for v in uses & modified)
        return row['path'].removeprefix('/app/') in changes,affinity
    frequency=Counter((kind,v) for r in programs for kind in ('keys','fields','observations') for v in r['features'][kind])
    def signature(row):return {(kind,v) for kind in ('keys','fields','observations') for v in row['features'][kind]}
    centers=[];seen=set();boundaries=set()
    while len(centers)<limit:
        candidates=[r for r in programs if (r['source'],tuple(r['boundary'])) not in boundaries]
        chosen=max(candidates,key=lambda r:(tier(r),
            sum(1/frequency[v] for v in signature(r)-seen) if centers else 0,-rank[r['id']]))
        centers.append(chosen['id']);seen.update(signature(chosen));boundaries.add((chosen['source'],tuple(chosen['boundary'])))
    return centers


def focused_patch(patch,centers):
    """Expose related diff bodies and retain all hunk headings for later reads."""
    sections=[s for s in re.split(r'(?=^diff --git )',patch,flags=re.M) if s.strip()]
    paths={r['path'].removeprefix('/app/') for r in centers}
    names={v for r in centers for k in ('calls','fields','keys') for v in r['features'][k]}
    def score(section):
        header=re.search(r'^\+\+\+ b/(.+)$',section,re.M)
        return (header is not None and header[1] in paths,
                sum(bool(re.search(r'\b'+re.escape(name)+r'\b',section)) for name in names))
    selected=sorted(enumerate(sections),key=lambda item:score(item[1]),reverse=True)[:4]
    selected.sort()
    def excerpt(section):
        if len(section)<=8000:return section
        return section[:4000]+'\n[... excerpt; request context if needed ...]\n'+section[-4000:]
    index='\n'.join(line for section in sections for line in section.splitlines() if line.startswith(('diff --git ','@@')))
    return 'PATCH INDEX (full public patch can be requested):\n'+index+'\nSELECTED DIFFS:\n'+'\n'.join(excerpt(s) for _,s in selected)


SYSTEM='You are a software testing researcher. Use only supplied public task and historical evidence. Return one JSON object.'
PLAN='''Propose ONE concrete additional validation test, using this task's existing
tests, historical code, outputs, data and read contracts. No hidden failing test
or manual bug diagnosis is supplied. The patch may be correct for your proposed
check; propose a meaningful check rather than assuming a particular bug.

Use requirements AND historical differences/revisions to discover a combination.
Inputs, multiple setup conditions, observations, and assertions may be combined.
An old complete test or an oracle-only change is also allowed. A historical PASS
or printed value is not by itself a correct oracle. Derive expected behavior from
applicable issue/API contracts. Distinguish test setup from the product obligation.
Do not invent observed object identity or field values from a static dependency.

Choose a base and sources by supplied IDs. Cite exact short excerpts as evidence.
Edits and bindings must identify expressions in the supplied code. Specify when
to observe and which instances/paths/values must be shared or separate. Consider
several coordinated changes when a single change is insufficient. A metamorphic
relation is optional; it must specify preconditions and what the two runs share.
Do not force an MR when a direct contract provides a stronger oracle.

If important material is missing, request precise APIs, paths, fields or snippets;
the next step can retrieve more public history. You may request an existing ID's
full context. Do not fill the gap with a guessed API signature.

Return this exact structure (arrays may be empty):
{"decision":"plan|need_material|no_plan", "base":"ID", "sources":["ID"],
 "intent":"what interaction/check is added",
 "edits":[{"source":"ID","anchor":"exact existing expression or line","action":"substitute|attach|restore|new_operation","change":"concrete change"}],
 "bindings":[{"name":"plan value/object/resource","members":[{"source":"ID","expression":"existing expression"}],"relation":"same|separate|value_transfer"}],
 "order":[["named operation","named operation"]],
 "preconditions":[{"name":"condition","observe":"runtime expression or diagnostic","expected":"required condition"}],
 "checks":[{"id":"C1","observe":"expression and moment","expected":"value or relation",
             "basis":[{"source":"issue|patch|ID","quote":"exact contiguous excerpt","reason":"why the requirement applies"}]}],
 "requests":[{"query":"precise search terms or ID","reason":"material needed"}],
 "unknowns":["specific unresolved condition"]}
'''
GENERATE='''Implement the supplied frozen composition plan as ONE independently
selectable test (or one script with checks). You have public repository excerpts
and original commands; choose a command supported by that environment. Include
necessary test helpers/fixtures. Their historical files may not be installed.
Do not modify implementation files, dependency manifests or project config. Put
new code in a test/fixture path (Go: *_test.go). Preserve the plan's inputs,
bindings, required preconditions and oracle. Do not weaken expected behavior.
For Rust integration tests select only this test; use existing features from the
recorded commands. Do not run an entire expensive test suite unnecessarily.

Emit diagnostics for actual runtime values using lines whose payload begins
EVIWEAVE_FACT followed by a JSON object with name, value, phase. Emit setup,
target invocation, and observations before final assertions, so a failed assertion
does not hide the observations. A diagnostic's value must come from an actual
expression: do not merely print that a plan was satisfied. Do not evaluate an
effectful expression twice just to print it. For an expected exception, catch it,
record its actual class and post-state, then check both. Do not add cleanup before
the required observation. A fact that violates a product obligation is a possible
bug, not an excuse to skip the test. Use actual assertions/nonzero exit on failure.

Return:
{"files":[{"path":"relative repository test/fixture path","content":"complete file"}],
 "command":"precise runner command", "build_commands":["only necessary build commands"],
 "realization":[{"edit":0,"path":"file","anchor":"exact generated code implementing it"}],
 "facts":[{"name":"diagnostic name","path":"file","expression":"actual expression","role":"precondition|target|observation"}],
 "checks":[{"id":"C1","path":"file","expression":"actual check expression"}],
 "unresolved":["anything not realized"]}
'''
