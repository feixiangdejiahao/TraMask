cd /app/libs/core && python -c "
import langchain_core.runnables as r
print('coalesce in dir:', 'CoalesceBackend' in dir(r), 'CoalesceStats' in dir(r), 'InMemoryCoalesceBackend' in dir(r))
print('RunnableCoalesce in dir:', 'RunnableCoalesce' in dir(r))
from langchain_core.runnables import CoalesceBackend, CoalesceStats, InMemoryCoalesceBackend
print('imports ok')
from langchain_core.runnables.coalesce import __all__
print('module __all__:', __all__)
"