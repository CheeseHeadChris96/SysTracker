"""Run only on the release workstation. Private keys must never be deployed to Azure."""
import argparse
import hashlib
import json
from getpass import getpass
from pathlib import Path
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding

p=argparse.ArgumentParser()
p.add_argument('--key',required=True,type=Path)
p.add_argument('--installer',required=True,type=Path)
p.add_argument('--version',required=True)
p.add_argument('--notes',required=True,type=Path)
p.add_argument('--output',type=Path,default=Path('updates/releases'))
args=p.parse_args()
key=serialization.load_pem_private_key(args.key.read_bytes(),password=getpass('Signing key passphrase: ').encode())
if args.installer.name!=f'SysTracker-{args.version}.msi':raise SystemExit('Installer filename does not match version.')
manifest={'version':args.version,'url':'https://updates.hbstest.com/'+args.installer.name,'sha256':hashlib.file_digest(args.installer.open('rb'),'sha256').hexdigest(),'notes':args.notes.read_text()}
payload=json.dumps(manifest,separators=(',',':')).encode()
signature=key.sign(payload,padding.PSS(mgf=padding.MGF1(hashes.SHA256()),salt_length=32),hashes.SHA256())
args.output.mkdir(parents=True,exist_ok=True)
(args.output/'stable.json').write_bytes(payload)
(args.output/'stable.sig').write_bytes(signature)
import shutil
shutil.copy2(args.installer,args.output/args.installer.name)
print('Signed manifest and installer staged. Deploy them together after Windows validation.')
