"""Create a source deployment ZIP with an explicit allowlist; never package local secrets."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
root=Path(__file__).resolve().parents[1]
(root/'dist').mkdir(exist_ok=True)
with ZipFile(root/'dist/web.zip','w',ZIP_DEFLATED) as archive:
    for folder in ('web',):
        for path in (root/folder).rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts:
                archive.write(path,path.relative_to(root))
    for filename in ('requirements.txt','requirements.lock.txt','startup.sh'):
        archive.write(root/filename,filename)
print('Created dist/web.zip without local state, credentials, or test data.')
