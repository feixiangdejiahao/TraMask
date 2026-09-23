"""Install historical mini-swe-agent versions in isolated import directories."""
import subprocess,sys,json
from pathlib import Path
root=Path(__file__).resolve().parents[1];rows=[]
for version in ['2.4.1','2.4.2','2.4.3']:
 dest=root/'vendor/harness'/version
 subprocess.run([sys.executable,'-m','pip','install','--no-deps','--target',str(dest),'mini-swe-agent=='+version],check=True,stdout=subprocess.DEVNULL)
 rows.append({'package':'mini-swe-agent','version':version,'target':str(dest.relative_to(root)),'dependency_environment':'.venv'})
rows.append({'package':'mini-swe-agent','version':'2.4.6','target':'.venv'})
(root/'results/harness_versions.json').write_text(json.dumps(rows,indent=2))
