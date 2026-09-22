"""Read-only release serving. Deploy separately; no signing keys or database access."""
from pathlib import Path
from flask import Flask, abort, send_from_directory
app=Flask(__name__)
root=Path(__file__).parent/'releases'

@app.get('/<name>')
def release(name):
    if name not in ('stable.json','stable.sig') and not (name.startswith('SysTracker-') and name.endswith('.msi')):abort(404)
    response=send_from_directory(root,name)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Cache-Control']='public, max-age=300'
    response.headers['Strict-Transport-Security']='max-age=31536000'
    return response
