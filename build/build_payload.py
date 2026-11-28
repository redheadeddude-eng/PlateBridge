from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import sys
base=Path(sys.base_prefix)
with ZipFile('build/PlateBridge.payload', 'w', ZIP_DEFLATED,compresslevel=5) as z:
 for n in ('python.exe','pythonw.exe','python314.dll','python3.dll','vcruntime140.dll','vcruntime140_1.dll','LICENSE.txt'):
  z.write(base/n,'runtime/'+n)
 for top in ('DLLs','Lib','tcl'):
  for p in (base/top).rglob('*'):
   if p.is_file() and not set(p.relative_to(base).parts)&{'__pycache__','site-packages','test','tests','ensurepip','idlelib','turtledemo'} and p.suffix.lower() not in ('.pdb','.lib','.pyc'):
    z.write(p,'runtime/'+p.relative_to(base).as_posix())
 for n in ('PlateBridge.py','plateproject.py','plate_review.py','pocket_ui.py','creator5-native.json','printer-presets.json','PlateBridge.ico'):
  src = Path('app') / n
  if src.suffix == '.py':
   compile(src.read_bytes(), str(src), 'exec')
  z.write(src, n)

