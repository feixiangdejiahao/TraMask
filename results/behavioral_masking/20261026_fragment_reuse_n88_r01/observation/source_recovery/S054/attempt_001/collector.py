
import base64,json,re,subprocess
from pathlib import Path
root=Path('/app')
p=subprocess.run(['git','-c','safe.directory=/app','-C','/app','ls-files','-z'],capture_output=True,check=True)
paths=[x.decode() for x in p.stdout.split(b'\0') if x]
selected=[p for p in paths if re.search(r'header[-_]increment|(^|/)jest[^/]*|^package\.json$|(^|/)rules?[^/]*test|^__tests__/(helpers|utils)',p,re.I)]
files={}
for p in selected:
 data=(root/p).read_bytes();files[p]=base64.b64encode(data).decode()
print(json.dumps({'tracked_paths':paths,'files_base64':files}))
