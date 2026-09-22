"""Guided Azure infrastructure deployment. Does not alter DNS or publish unvalidated collectors."""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
from urllib.parse import quote

root=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser()
p.add_argument('--subscription',required=True)
p.add_argument('--prefix',required=True,help='Globally unique 3–16 lowercase letters/digits')
p.add_argument('--region',default='centralus')
p.add_argument('--apply',action='store_true',help='Create billable Azure resources after showing the deployment preview')
args=p.parse_args()
if not re.fullmatch('[a-z][a-z0-9]{2,15}',args.prefix):p.error('Use a lowercase alphanumeric prefix starting with a letter.')
def az(*a,capture=False):
    result=subprocess.run(['az',*a],check=True,text=True,capture_output=capture)
    return json.loads(result.stdout) if capture else None
az('account','set','--subscription',args.subscription)
account=az('account','show','--query','{name:name,id:id}','-o','json',capture=True)
print('Target subscription:',account['name'],account['id'])
group=args.prefix+'-systracker'
directory=root/'instance'/'deployment';directory.mkdir(parents=True,exist_ok=True,mode=0o700)
parameters=directory/(args.prefix+'.parameters.json')
if not parameters.exists():
    app_password=secrets.token_urlsafe(36)
    values={'prefix':args.prefix,'location':args.region,'adminEmail':'administrator@hbstest.com',
        'sqlAdminPassword':secrets.token_urlsafe(36),'sessionSecret':secrets.token_hex(48),
        'databaseUrl':f'mssql+pymssql://systracker_app:{quote(app_password,safe="")}@{args.prefix}-sql.database.windows.net:1433/systracker'}
    fd=os.open(parameters,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w') as f:json.dump({'$schema':'https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#','contentVersion':'1.0.0.0','parameters':{k:{'value':v} for k,v in values.items()}},f)
print('Private deployment parameters retained in instance/deployment. Do not share or commit them.')
if not args.apply:
    print('Prepared only. No Azure resources were created. Re-run with --apply to preview and deploy the pilot resources.')
    raise SystemExit(0)
print('Planning budget: approximately US $15–$25/month at light pilot usage; not a spending cap.')
az('group','create','--name',group,'--location',args.region,'--output','none')
common=['--resource-group',group,'--template-file',str(root/'infra/main.bicep'),'--parameters','@'+str(parameters)]
az('deployment','group','what-if',*common)
if input('Type DEPLOY to create/update these Azure resources: ')!='DEPLOY':raise SystemExit('No application resources deployed.')
result=az('deployment','group','create',*common,'--query','properties.outputs','-o','json',capture=True)
(directory/(args.prefix+'.outputs.json')).write_text(json.dumps(result,indent=2))
from datetime import datetime,timezone
start=datetime.now(timezone.utc).strftime('%Y-%m-01T00:00:00Z')
az('deployment','group','create','--resource-group',group,'--template-file',str(root/'infra/budget.bicep'),'--parameters','startDate='+start,'--output','none')
print('Infrastructure created. Follow docs/AZURE.md for database initialization, DNS, email verification, and application upload.')
