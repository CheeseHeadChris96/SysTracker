import hashlib
import hmac
import json
import re
import uuid
from pathlib import Path
import pytest
from sqlalchemy import select
from werkzeug.security import generate_password_hash
from web import create_app
from web.models import db, User, Customer, Access, Challenge, Collector, Device, History, Rate, now

@pytest.fixture
def app(tmp_path):
    a=create_app({'TESTING':True,'SECRET_KEY':'test-secret-'*5,'SQLALCHEMY_DATABASE_URI':'sqlite:///'+str(tmp_path/'test.db'),'MAIL_MODE':'file'})
    a.instance_path=str(tmp_path)
    with a.app_context():
        db.create_all()
        users=[User(id=r,email=r+'@example.com',name=r,role=r,password=generate_password_hash('a long test password'),verified=True) for r in ('admin','manager','viewer')]
        db.session.add_all(users+[Customer(id='a',name='Alpha'),Customer(id='b',name='Beta')]);db.session.flush()
        db.session.add_all([Access(user_id='manager',customer_id='a'),Access(user_id='viewer',customer_id='a')]);db.session.commit()
    yield a

def client(app,role='admin'):
    c=app.test_client()
    if role:
        with c.session_transaction() as s:s['uid']=role;s['epoch']=0
    return c

def post(c,url,d,method='POST'):
    token=c.get('/api/session').json['csrf']
    return c.open(url,method=method,json=d,headers={'X-CSRFToken':token})

def enroll(c,customer='a',name='Collector'):
    code=post(c,f'/api/customers/{customer}/enrollment',{}).json['code']
    r=c.post('/ingest/enroll',json={'code':code,'name':name})
    assert r.status_code==201
    return r.json

def batch(version='2022',at=None):
    return {'batch_id':str(uuid.uuid4()),'collected_at':at or now(),'version':'0.1.0','devices':[{'identity':'uuid-host','product':'Windows Server','name':'DC01','version':version}],'failures':[]}

def send(c,collector,payload):return c.post('/ingest/inventory',json=payload,headers={'Authorization':'Bearer '+collector['token']})

def code(app):
    files=sorted((Path(app.instance_path)/'outbox').glob('*.json'))
    return re.search(r'code is (\d{6})',json.loads(files[-1].read_text())['body'])[1]

def test_requires_password_then_code(app):
    c=client(app,None)
    assert c.get('/api/customers').status_code==401
    r=post(c,'/api/auth/login',{'email':'admin@example.com','password':'a long test password'})
    assert r.status_code==200
    assert c.get('/api/customers').status_code==401
    challenge=r.json['challenge'];otp=code(app)
    assert post(c,'/api/auth/verify',{'challenge':challenge,'code':otp}).status_code==200
    assert c.get('/api/customers').status_code==200
    assert post(c,'/api/auth/verify',{'challenge':challenge,'code':otp}).status_code==400

def test_code_attempt_limit_and_expiry(app):
    c=client(app,None);r=post(c,'/api/auth/login',{'email':'admin@example.com','password':'a long test password'});cid=r.json['challenge'];otp=code(app)
    wrong='000000' if otp!='000000' else '111111'
    for _ in range(5):assert post(c,'/api/auth/verify',{'challenge':cid,'code':wrong}).status_code==400
    assert post(c,'/api/auth/verify',{'challenge':cid,'code':otp}).status_code==400
    with app.app_context():
        db.session.query(Rate).delete();ch=db.session.get(Challenge,cid);ch.attempts=0;ch.expires=now()-1;db.session.commit()
    assert post(c,'/api/auth/verify',{'challenge':cid,'code':otp}).status_code==400

def test_csrf(app):
    c=client(app)
    assert c.post('/api/customers',json={'name':'bad'}).status_code==400

def test_customer_isolation_and_viewer_readonly(app):
    manager=client(app,'manager');viewer=client(app,'viewer')
    assert [c['id'] for c in viewer.get('/api/customers').json]==['a']
    assert post(manager,'/api/customers/b/enrollment',{}).status_code==404
    assert post(viewer,'/api/customers',{'name':'Forbidden'}).status_code==403
    assert post(viewer,'/api/customers/a/enrollment',{}).status_code==403
    assert viewer.get('/api/engineers').status_code==403
    assert post(manager,'/api/engineers',{'name':'No'}).status_code==403

def test_manager_owns_new_customer(app):
    c=client(app,'manager');r=post(c,'/api/customers',{'name':'New customer'})
    assert r.status_code==201
    assert r.json['id'] in [x['id'] for x in c.get('/api/customers').json]

def test_enrollment_single_use_and_no_commands(app):
    c=client(app);code_=post(c,'/api/customers/a/enrollment',{}).json['code']
    assert c.post('/ingest/enroll',json={'code':code_,'name':'first'}).status_code==201
    assert c.post('/ingest/enroll',json={'code':code_,'name':'second'}).status_code==401
    assert c.get('/ingest/commands').status_code==404

def test_reporting_identity_overrides_customer_payload(app):
    c=client(app);collector=enroll(c);payload=batch();payload['customer_id']='b'
    assert send(c,collector,payload).status_code==200
    devices=c.get('/api/inventory').json
    assert len(devices)==1 and devices[0]['customer_id']=='a'

def test_retries_deduplicate_and_old_batches_do_not_regress(app):
    c=client(app);collector=enroll(c);payload=batch()
    assert send(c,collector,payload).status_code==200
    assert send(c,collector,payload).status_code==200
    assert send(c,collector,batch('2019',now()-3600)).status_code==200
    assert c.get('/api/inventory').json[0]['version']=='2022'
    assert c.get('/api/history').json==[]

def test_multi_collector_conflict_and_version_history(app):
    c=client(app);first=enroll(c);second=enroll(c,name='second')
    assert send(c,first,batch('2019')).status_code==200
    assert send(c,second,batch('2022')).status_code==200
    ds=c.get('/api/inventory').json
    assert len(ds)==1 and ds[0]['conflict']
    assert len(c.get('/api/history').json)==1

def test_archive_retains_inventory_and_revokes_collector(app):
    c=client(app);collector=enroll(c);send(c,collector,batch())
    assert post(c,'/api/collectors/'+collector['collector_id']+'/archive',{}).status_code==200
    assert send(c,collector,batch()).status_code==401
    assert len(c.get('/api/inventory').json)==1

def test_device_archive_does_not_silently_restore(app):
    c=client(app);collector=enroll(c);send(c,collector,batch())
    did=c.get('/api/inventory').json[0]['id']
    post(c,'/api/devices/'+did,{'archived':True},'PATCH');send(c,collector,batch('2025'))
    device=c.get('/api/inventory').json[0]
    assert device['archived'] and device['rediscovered'] and device['version']=='2022'

def test_customer_archive_revokes_unused_enrollment(app):
    c=client(app);code_=post(c,'/api/customers/a/enrollment',{}).json['code']
    post(c,'/api/customers/a',{'archived':True},'PATCH');post(c,'/api/customers/a',{'archived':False},'PATCH')
    assert c.post('/ingest/enroll',json={'code':code_,'name':'late'}).status_code==401

def test_disabled_engineer_loses_sessions(app):
    admin=client(app);viewer=client(app,'viewer')
    assert viewer.get('/api/customers').status_code==200
    assert post(admin,'/api/engineers/viewer',{'active':False},'PATCH').status_code==200
    assert viewer.get('/api/customers').status_code==401

def test_invalid_batch_is_atomic(app):
    c=client(app);collector=enroll(c);payload=batch();payload['devices'].append({'identity':'x','product':'Invalid','name':'bad','version':'1'})
    assert send(c,collector,payload).status_code==400
    assert c.get('/api/inventory').json==[]

def test_secrets_never_returned_in_dashboard(app):
    c=client(app);collector=enroll(c)
    body=c.get('/api/collectors').get_data(as_text=True)
    assert collector['token'] not in body and 'digest' not in body

def test_signup_requires_email_code(app):
    admin=client(app)
    r=post(admin,'/api/engineers',{'name':'New','email':'new@example.com','role':'viewer','customers':['a']})
    assert r.status_code==201
    invite=json.loads(sorted((Path(app.instance_path)/'outbox').glob('*.json'))[-1].read_text())
    token=re.search(r'#invite=(\S+)',invite['body'])[1]
    c=client(app,None);cid=post(c,'/api/auth/invite',{'token':token}).json['challenge']
    assert post(c,'/api/auth/verify',{'challenge':cid,'code':code(app),'password':'new secure passphrase'}).status_code==200
    assert len(c.get('/api/customers').json)==1
    assert post(c,'/api/auth/invite',{'token':token}).status_code==400

def test_production_rejects_local_email_and_database():
    with pytest.raises(RuntimeError):create_app({'PRODUCTION':True,'SECRET_KEY':'a'*50,'MAIL_MODE':'file'})

def test_failed_connection_marks_previous_inventory(app):
    c=client(app);collector=enroll(c);payload=batch();payload['devices'][0]['target']='dc01.example.local'
    assert send(c,collector,payload).status_code==200
    failed=batch();failed['devices']=[];failed['failures']=[{'target':'dc01.example.local','category':'permissions'}]
    assert send(c,collector,failed).status_code==200
    assert c.get('/api/inventory').json[0]['status']=='Collection failed'

def test_reset_revokes_existing_sessions_and_requires_code(app):
    old=client(app,'viewer');c=client(app,None)
    cid=post(c,'/api/auth/reset',{'email':'viewer@example.com'}).json['challenge']
    assert c.get('/api/customers').status_code==401
    assert post(c,'/api/auth/verify',{'challenge':cid,'code':code(app),'password':'replacement long password'}).status_code==200
    assert old.get('/api/customers').status_code==401

def test_unauthorized_customer_data_is_absent_from_all_views(app):
    admin=client(app);collector=enroll(admin,'b');send(admin,collector,batch('2019'));send(admin,collector,batch('2022'))
    viewer=client(app,'viewer')
    for endpoint in ('/api/inventory','/api/collectors','/api/history'):
        assert viewer.get(endpoint).json==[]
    did=admin.get('/api/inventory').json[0]['id']
    assert post(client(app,'manager'),'/api/devices/'+did,{'archived':True},'PATCH').status_code==404

def test_logout_revokes_copied_session(app):
    c=client(app,'viewer');copied=c.get_cookie('session').value
    assert post(c,'/api/auth/logout',{}).status_code==200
    attacker=client(app,None);attacker.set_cookie('session',copied)
    assert attacker.get('/api/customers').status_code==401

def test_customer_engineer_assignments_and_reverse_list(app):
    admin=client(app)
    r=post(admin,'/api/customers/b',{'primary_engineer_id':'viewer','secondary_engineer_id':'manager'},'PATCH')
    assert r.status_code==200
    customer=next(c for c in admin.get('/api/customers').json if c['id']=='b')
    assert customer['primary_engineer']['id']=='viewer'
    assert customer['secondary_engineer']['name']=='manager'
    assert set(c['id'] for c in client(app,'viewer').get('/api/customers').json)=={'a','b'}
    user=next(u for u in admin.get('/api/engineers').json if u['id']=='viewer')
    assert user['explicit_customers']==['a']
    assert [(c['name'],c['position']) for c in user['assignments']]==[('Alpha','assigned'),('Beta','primary')]
    # Clearing responsibility removes only the access supplied by that assignment.
    assert post(admin,'/api/customers/b',{'primary_engineer_id':''},'PATCH').status_code==200
    assert [c['id'] for c in client(app,'viewer').get('/api/customers').json]==['a']

def test_customer_engineer_validation_and_swapping(app):
    c=client(app)
    assert post(c,'/api/customers/a',{'primary_engineer_id':'viewer','secondary_engineer_id':'viewer'},'PATCH').status_code==400
    assert post(c,'/api/customers/a',{'primary_engineer_id':'missing'},'PATCH').status_code==400
    assert post(c,'/api/customers/a',{'primary_engineer_id':['viewer']},'PATCH').status_code==400
    assert post(c,'/api/customers/a',{'primary_engineer_id':'viewer','secondary_engineer_id':'manager'},'PATCH').status_code==200
    assert post(c,'/api/customers/a',{'primary_engineer_id':'manager','secondary_engineer_id':'viewer'},'PATCH').status_code==200
    assert post(c,'/api/engineers/viewer',{'active':False},'PATCH').status_code==200
    assert post(c,'/api/customers/b',{'primary_engineer_id':'viewer'},'PATCH').status_code==400
    # Existing disabled assignments remain visible and do not block unrelated edits.
    assert post(c,'/api/customers/a',{'notes':'Reviewed','secondary_engineer_id':'viewer'},'PATCH').status_code==200
    customer=next(x for x in c.get('/api/customers').json if x['id']=='a')
    assert customer['secondary_engineer']['active'] is False

def test_responsibilities_cannot_be_used_to_escalate_access(app):
    for role in ('viewer','manager'):
        assert post(client(app,role),'/api/customers/a',{'primary_engineer_id':role},'PATCH').status_code==403
    c=client(app)
    assert post(c,'/api/customers/a',{'primary_engineer_id':'viewer'},'PATCH').status_code==200
    assert post(c,'/api/engineers/viewer',{'customers':[]},'PATCH').status_code==200
    # Explicit-access editing does not silently remove customer responsibility.
    viewer=client(app,'viewer')
    with viewer.session_transaction() as s:s['epoch']=1  # fresh sign-in after session revocation
    assert [x['id'] for x in viewer.get('/api/customers').json]==['a']

def test_assignments_can_be_set_when_customer_is_created(app):
    c=client(app)
    r=post(c,'/api/customers',{'name':'Gamma','primary_engineer_id':'manager','secondary_engineer_id':'viewer'})
    assert r.status_code==201
    assert r.json['id'] in [x['id'] for x in client(app,'viewer').get('/api/customers').json]
