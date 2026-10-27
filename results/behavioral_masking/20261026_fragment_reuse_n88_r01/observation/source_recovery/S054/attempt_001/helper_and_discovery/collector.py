
import base64,json,subprocess
from pathlib import Path
files={p:base64.b64encode(Path('/app',p).read_bytes()).decode() for p in ['__tests__/common.ts','babel.config.js']}
git=subprocess.run(['git','-c','safe.directory=/app','-C','/app','diff','--name-only','6393b3ab32a2ace1fc24d4b0f5e0f13a179c874f','HEAD','--','__tests__/header-increment.test.ts','__tests__/common.ts','jest.config.ts','package.json','babel.config.js'],capture_output=True,check=True)
print(json.dumps({'files_base64':files,'changed_since_base':git.stdout.decode()}))
