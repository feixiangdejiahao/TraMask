"""Fair proposal service across rounds, with exact-input duplicate suppression."""
from collections import defaultdict, deque
import heapq

from prototypes.source_edit_identity import input_identity


def select(candidates, budget=128, previously_attempted=()):
    previous = set(previously_attempted)
    served = defaultdict(int)
    known = set()
    for row in candidates:
        key = input_identity(row)
        if row['id'] in previous and key not in known:
            served[row.get('operator', row.get('kind', 'unknown'))] += 1
            known.add(key)
    groups = defaultdict(deque)
    for row in candidates:
        key = input_identity(row)
        if key in known:
            continue
        known.add(key)
        groups[row.get('operator', row.get('kind', 'unknown'))].append(row)
    queue = [(served[family], family) for family in groups]
    heapq.heapify(queue)
    result = []
    while queue and len(result) < budget:
        count, family = heapq.heappop(queue)
        result.append(groups[family].popleft())
        if groups[family]:
            heapq.heappush(queue, (count+1, family))
    return result
