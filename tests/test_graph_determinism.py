"""Independent synthetic regressions: graph numbering must not depend on hash seed."""
import json
import os
from pathlib import Path
import subprocess
import sys

import generic_composition
import pytest

ROOT = Path(generic_composition.__file__).resolve().parents[1]
PROBE = r'''
import hashlib,json,sys,tempfile
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from generic_composition.corpus import build_corpus
with tempfile.TemporaryDirectory() as temporary:
 root=Path(temporary);(root/'test_toy.py').write_text(sys.argv[2])
 corpus=build_corpus(root,'python')
 print(hashlib.sha256(json.dumps(corpus,sort_keys=True).encode()).hexdigest())
'''

@pytest.mark.parametrize('source', [
'''def test_toy():
    alpha = 1
    beta = 2
    gamma = 3
    if condition:
        alpha = 4
        beta = 5
        gamma = 6
    actual = subject(alpha, beta, gamma)
    assert actual == 9
''',
'''def test_toy():
    alpha = []
    beta = []
    gamma = []
    mutate(alpha, beta, gamma)
    actual = subject(alpha, beta, gamma)
    assert actual == 9
''',
], ids=['branch_join_numbering','may_effect_numbering'])
def test_corpus_graph_is_hash_seed_independent(source):
    hashes=[]
    for seed in (1,2,7,31):
        env=dict(os.environ, PYTHONHASHSEED=str(seed))
        process=subprocess.run([sys.executable,'-c',PROBE,str(ROOT),source],env=env,cwd=ROOT,
                               capture_output=True,text=True,check=True,timeout=20)
        hashes.append(process.stdout.strip())
    assert len(set(hashes)) == 1
