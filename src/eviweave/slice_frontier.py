"""Choose dependence endpoints instead of independently slicing every hit."""
from collections import defaultdict
from .evidence import strongly_connected_components,BLOCKS
from .anchors import STRINGS
from .pre_slice import merge_ranges
from .test_units import discover


def matching_statements(graph, units, query_points):
    """Lower D's exact/coarse locations to call and source-input ports."""
    ports = {};unmapped = []
    for index, unit in units:
        for start,end in unit['anchors']:
            points = ([(a,b) for a,b in query_points if unit['start']<=a and b<=unit['end']]
                      if [start,end]==[unit['start'],unit['end']] else [(start,end)])
            for a,b in points:
                criterion = graph.criterion(a,b)
                if criterion is None:
                    unmapped.append({'range':[a,b], 'entry':index})
                elif criterion['kind'] in {'call','input_string'}:
                    port = ports.setdefault(criterion['node'], {'node':criterion['node'], 'points':set(), 'entries':set()})
                    port['points'].add((a,b));port['entries'].add(index)
    return [{'node':node, 'points':[list(p) for p in sorted(port['points'])], 'entries':sorted(port['entries'])}
            for node,port in sorted(ports.items())], unmapped


def frontier_groups(graph, seeds, *, dependencies=None):
    """Group connected forward effects and retain their terminal components.

    Each group stays in one lexical execution scope. A branch can have several
    endpoints; keeping all of them lets backward slicing recover its inputs.
    """
    headers={s['header']:s['id'] for s in graph.scopes
             if s['header'] is not None and s['kind']=='function'}
    scopes=defaultdict(set)
    for seed in seeds:scopes[headers.get(seed,graph.nodes[seed]['scope'])].add(seed)
    if dependencies is None:
        forward=graph.forward
        if True not in graph.components:graph.components[True]=graph._forward_components(True)
        component=graph.components[True]
    else:
        forward=defaultdict(set);local=defaultdict(set)
        for node,predecessors in dependencies.items():
            for pred in predecessors:
                forward[pred].add(node)
                if graph.nodes[pred]['scope']==graph.nodes[node]['scope']:local[pred].add(node)
        component=strongly_connected_components(range(len(graph.nodes)),local)
    groups=[]
    for scope,starts in sorted(scopes.items()):
        region=set(starts);pending=list(starts);successors=defaultdict(set);neighbors=defaultdict(set)
        while pending:
            current=pending.pop()
            for nxt in forward[current]:
                if graph.nodes[nxt]['scope']!=scope:continue
                successors[current].add(nxt);neighbors[current].add(nxt);neighbors[nxt].add(current)
                if nxt not in region:region.add(nxt);pending.append(nxt)
        unseen=set(region)
        while unseen:
            start=min(unseen);connected={start};pending=[start];unseen.remove(start)
            while pending:
                current=pending.pop()
                for nxt in neighbors[current] & unseen:
                    unseen.remove(nxt);connected.add(nxt);pending.append(nxt)
            members=defaultdict(list);nonterminal=set()
            for node in connected:
                members[component[node]].append(node)
                for nxt in successors[node]:
                    if component[nxt]!=component[node]:nonterminal.add(component[node])
            endpoints=[]
            for cid,nodes in members.items():
                if cid not in nonterminal:
                    endpoints.append(max(nodes,key=lambda n:(graph.nodes[n]['observation'],graph.nodes[n]['end'],n)))
            groups.append({'scope':scope,'matches':sorted(connected & starts),
                           'frontier':sorted(endpoints),'forward_nodes':sorted(connected)})
    return groups


def attached_comments(graph, ranges):
    """Keep comments directly attached to selected statements or headers."""
    comments=[];pending=[graph.root]
    while pending:
        node=pending.pop()
        if node.type in {'comment','line_comment','block_comment'}:comments.append((node.start_byte,node.end_byte))
        else:pending.extend(node.named_children)
    result=list(ranges)
    for start,end in sorted(comments,reverse=True):
        for a,b in result:
            before=graph.raw[end:a] if end<=a else None
            after=graph.raw[b:start] if b<=start else None
            if ((before is not None and not before.strip() and before.count(b'\n')<=1) or
                (after is not None and not after.strip() and b'\n' not in after)):
                result.append([start,end]);break
    return merge_ranges(result)


def validation_groups(graph,seeds,*,dependencies=None):
    """Keep all dependence endpoints belonging to the same validation case.

    Unregistered helpers and module code keep their lexical boundaries. Nested
    callbacks inside a test share its view; independent tests remain separate.
    """
    if graph.test_definitions is None:
        graph.test_definitions=discover(graph.source['path'],graph.raw,normalized=True)
    definitions=graph.test_definitions
    if definitions['status']=='parsed':tests=definitions['ranges']
    else:tests={}
    groups=defaultdict(list)
    for group in frontier_groups(graph,seeds,dependencies=dependencies):
        for match in group['matches']:
            node=graph.nodes[match]
            enclosing=[(b-a,identity) for identity,(a,b) in tests.items()
                       if a<=node['start'] and node['end']<=b]
            key=('test',min(enclosing)[1]) if enclosing else ('scope',group['scope'])
            groups[key].append((match,group))
    result=[{'boundary':list(key),'matches':sorted({match for match,_ in rows}),
             'frontier':sorted({n for _,group in rows for n in group['frontier']})}
            for key,rows in sorted(groups.items())]
    if definitions['status']!='parsed':
        for group in result:group['boundary_issue']=definitions
    return result


def source_syntax(graph,nodes,ranges):
    """Retain syntax delimiters and documentation of selected definitions."""
    punctuation={'(',')','{','}','[',']',',',';',':'}
    result=list(ranges);seen=set();pending=[graph.nodes[n]['ast'] for n in nodes]
    while pending:
        node=pending.pop()
        if node.id in seen:continue
        seen.add(node.id)
        result.extend([c.start_byte,c.end_byte] for c in node.children if c.type in punctuation)
        if node.parent is not None:pending.append(node.parent)
        # A selected declaration/control can have an empty body.
        for child in node.named_children:
            if child.type in BLOCKS:
                result.extend([c.start_byte,c.end_byte] for c in child.children if c.type in punctuation)
        if node.type=='function_definition':
            body=node.child_by_field_name('body');statements=body.named_children
            if statements and statements[0].type=='expression_statement':
                first=statements[0]
                if len(first.named_children)==1 and first.named_children[0].type in STRINGS:
                    result.append([first.start_byte,first.end_byte])
    return merge_ranges(result)
