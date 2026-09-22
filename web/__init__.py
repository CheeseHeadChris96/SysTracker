import csv
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import secrets
import time
from datetime import timedelta
from functools import wraps
from urllib.parse import urlparse

import click
from email_validator import validate_email, EmailNotValidError
from flask import Flask, request, jsonify, session, g, abort, send_from_directory, Response
from flask_wtf.csrf import CSRFProtect, generate_csrf
from sqlalchemy import update, select, delete
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash, check_password_hash
from .models import *

csrf = CSRFProtect()
PRODUCTS = ['Windows Server', 'Hyper-V', 'VMware vCenter', 'VMware ESXi', 'Veeam Backup & Replication', 'Palo Alto PAN-OS']

def create_app(overrides=None):
    app = Flask(__name__, static_folder='static')
    Path(app.instance_path).mkdir(mode=0o700, exist_ok=True)
    production = os.getenv('APP_ENV') == 'production'
    secret = os.getenv('SECRET_KEY')
    if not secret and not production:
        path = Path(app.instance_path) / 'session.key'
        if not path.exists():
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as f: f.write(secrets.token_hex(48))
        secret = path.read_text()
    app.config.update(SECRET_KEY=secret, SQLALCHEMY_DATABASE_URI=os.getenv('DATABASE_URL', 'sqlite:///systracker.db'),
        SQLALCHEMY_TRACK_MODIFICATIONS=False, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict',
        SESSION_COOKIE_SECURE=production, PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        MAX_CONTENT_LENGTH=2*1024*1024, PUBLIC_URL=os.getenv('PUBLIC_URL', 'http://127.0.0.1:5080'),
        INGEST_HOST=os.getenv('INGEST_HOST', 'ingest.hbstest.com'), PRODUCTION=production,
        MAIL_MODE=os.getenv('MAIL_MODE', 'file'), MAIL_SENDER=os.getenv('MAIL_SENDER', 'systracker@hbstest.com'))
    if overrides: app.config.update(overrides)
    if app.config['PRODUCTION']:
        if not app.config['SECRET_KEY'] or len(app.config['SECRET_KEY']) < 40: raise RuntimeError('Set a strong SECRET_KEY.')
        if app.config['MAIL_MODE'] != 'azure': raise RuntimeError('Production requires Azure email delivery.')
        if not app.config['PUBLIC_URL'].startswith('https://'): raise RuntimeError('Production requires HTTPS PUBLIC_URL.')
        if app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite:'): raise RuntimeError('Production requires a managed database.')
    if app.config['SQLALCHEMY_DATABASE_URI'].startswith('mssql+pymssql:'):
        # Preserve existing connection strings while replacing the FreeTDS
        # driver that rejects Azure's wildcard certificate.
        app.config['SQLALCHEMY_DATABASE_URI']=app.config['SQLALCHEMY_DATABASE_URI'].replace('mssql+pymssql:', 'mssql+pytds:', 1)
    if app.config['SQLALCHEMY_DATABASE_URI'].startswith('mssql+pytds:'):
        from sqlalchemy.pool import NullPool
        import certifi
        app.config['SQLALCHEMY_ENGINE_OPTIONS']={'poolclass':NullPool,'connect_args':{'cafile':certifi.where(),'validate_host':True,'enc_login_only':False,'login_timeout':30,'timeout':30}}
    db.init_app(app)
    csrf.init_app(app)

    def digest(value):
        return hmac.new(app.config['SECRET_KEY'].encode(), value.encode(), hashlib.sha256).hexdigest()

    def data():
        d = request.get_json(silent=True)
        if not isinstance(d, dict): abort(400, 'Expected a JSON object.')
        return d

    def text(d, key, limit=160, required=True):
        value = d.get(key, '')
        if not isinstance(value, str) or len(value) > limit or (required and not value.strip()): abort(400, f'Invalid {key}.')
        return value.strip()

    def email(value):
        try: return validate_email(value, check_deliverability=False).normalized.lower()
        except (EmailNotValidError, TypeError): abort(400, 'Enter a valid email address.')

    def audit(action, subject):
        db.session.add(Audit(actor=g.user.email if getattr(g, 'user', None) else 'system', action=action, subject=subject))

    def rate(scope, identity, maximum, window):
        key = digest(f'{scope}:{identity}:{now() // window}')
        r = db.session.get(Rate, key)
        if not r:
            try:
                db.session.add(Rate(key=key, count=0, expires=now()+window*2)); db.session.commit()
            except IntegrityError: db.session.rollback()
        changed = db.session.execute(update(Rate).where(Rate.key == key, Rate.count < maximum).values(count=Rate.count+1)).rowcount
        db.session.commit()
        if not changed: abort(429, 'Too many attempts. Please try again later.')

    def mail(address, subject, body):
        if app.config['MAIL_MODE'] == 'file':
            outbox = Path(app.instance_path) / 'outbox'; outbox.mkdir(mode=0o700, exist_ok=True)
            filename = outbox / f'{time.time_ns()}.json'
            fd = os.open(filename, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as f: json.dump(dict(to=address, subject=subject, body=body), f)
        else:
            from azure.communication.email import EmailClient
            client = EmailClient.from_connection_string(os.environ['ACS_CONNECTION_STRING'])
            client.begin_send({'senderAddress':app.config['MAIL_SENDER'], 'recipients':{'to':[{'address':address}]},
                'content':{'subject':subject, 'plainText':body}}).result(timeout=30)

    def challenge(user, purpose):
        rate('email', user.id, 1, 60)
        db.session.execute(update(Challenge).where(Challenge.user_id == user.id, Challenge.purpose == purpose).values(used=True))
        code = f'{secrets.randbelow(1000000):06d}'
        c = Challenge(id=uid(), user_id=user.id, purpose=purpose, expires=now()+600, digest='')
        c.digest = digest(c.id+':'+code)
        db.session.add(c); db.session.commit()
        try: mail(user.email, 'Your SysTracker verification code', f'Your code is {code}. It expires in 10 minutes. If you did not request this, ignore this email.')
        except Exception:
            c.used = True; db.session.commit(); abort(503, 'Email could not be delivered. Please try again later.')
        return c.id

    def invite(user):
        db.session.execute(update(Invite).where(Invite.user_id == user.id).values(used=True))
        db.session.execute(update(Challenge).where(Challenge.user_id == user.id,Challenge.purpose=='setup').values(used=True))
        token = secrets.token_urlsafe(32)
        db.session.add(Invite(digest=digest(token), user_id=user.id, expires=now()+172800)); db.session.commit()
        try: mail(user.email, 'You are invited to SysTracker', f"Set up your account: {app.config['PUBLIC_URL']}/#invite={token}\nThis invitation expires in 48 hours.")
        except Exception: abort(503, 'Invitation saved, but email delivery failed. Use Resend invitation.')

    def allowed_ids():
        if g.user.role == 'admin': return [c.id for c in db.session.scalars(select(Customer))]
        return list(set(db.session.scalars(select(Access.customer_id).where(Access.user_id == g.user.id))) |
            set(db.session.scalars(select(CustomerEngineer.customer_id).where(CustomerEngineer.user_id == g.user.id))))

    def customer_engineers(cid):
        result={'primary_engineer':None,'secondary_engineer':None}
        for assignment,user in db.session.execute(select(CustomerEngineer,User).join(User).where(CustomerEngineer.customer_id==cid)):
            result[assignment.position+'_engineer']=dict(id=user.id,name=user.name,email=user.email,active=user.active)
        return result

    def set_customer_engineers(cid,d):
        if not any(k in d for k in ('primary_engineer_id','secondary_engineer_id')): return
        # Assignments grant customer access, so retain administrator-only access administration.
        if g.user.role!='admin': abort(403)
        previous={a.position:a.user_id for a in db.session.scalars(select(CustomerEngineer).where(CustomerEngineer.customer_id==cid))}
        desired={position:d.get(position+'_engineer_id',previous.get(position)) for position in ('primary','secondary')}
        if desired['primary'] and desired['primary']==desired['secondary']: abort(400,'Choose different primary and secondary engineers.')
        for position,value in desired.items():
            if value is None or value=='': continue
            if not isinstance(value,str): abort(400,'Invalid engineer assignment.')
            user=db.session.get(User,value)
            if not user or (not user.active and previous.get(position)!=value): abort(400,'Choose an enabled engineer account.')
        db.session.execute(delete(CustomerEngineer).where(CustomerEngineer.customer_id==cid)); db.session.flush()
        for position,value in desired.items():
            if value: db.session.add(CustomerEngineer(customer_id=cid,position=position,user_id=value))
        if desired!=previous: audit('customer.engineers_assigned',cid)

    def customer_access(customer_id, manage=False):
        c = db.session.get(Customer, customer_id)
        if not c or customer_id not in allowed_ids(): abort(404)
        if manage and g.user.role not in ('admin', 'manager'): abort(403)
        return c

    def auth(role=None):
        def deco(fn):
            @wraps(fn)
            def wrapped(*args, **kwargs):
                if not g.user: abort(401)
                if role and g.user.role not in role: abort(403)
                return fn(*args, **kwargs)
            return wrapped
        return deco

    @app.before_request
    def load_user():
        g.user = db.session.get(User, session['uid']) if session.get('uid') else None
        if g.user and (not g.user.active or not g.user.verified or session.get('epoch') != g.user.epoch):
            session.clear(); g.user = None
        if app.config['PRODUCTION']:
            host = request.host.split(':')[0]
            expected = app.config['INGEST_HOST'] if request.path.startswith('/ingest/') else urlparse(app.config['PUBLIC_URL']).hostname
            if request.path != '/health' and host != expected: abort(404)

    @app.after_request
    def headers(response):
        response.headers.update({'X-Content-Type-Options':'nosniff', 'Referrer-Policy':'no-referrer',
            'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            'Cache-Control':'no-store', 'Permissions-Policy':'camera=(), microphone=(), geolocation=()'})
        if app.config['PRODUCTION']: response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        return response

    @app.errorhandler(Exception)
    def error(exc):
        from werkzeug.exceptions import HTTPException
        if isinstance(exc, HTTPException): return jsonify(error=exc.description), exc.code
        db.session.rollback()
        app.logger.error('Request failed: %s', type(exc).__name__)
        return jsonify(error='The request could not be completed.'), 500

    @app.get('/')
    def index(): return send_from_directory(app.static_folder, 'index.html')

    @app.get('/health')
    def health(): return jsonify(status='ok')

    @app.get('/api/session')
    def current_session():
        u = g.user
        return jsonify(csrf=generate_csrf(), user=dict(id=u.id,name=u.name,email=u.email,role=u.role) if u else None,
            development=not app.config['PRODUCTION'], products=PRODUCTS)

    @app.post('/api/auth/login')
    def login():
        d=data(); address=email(d.get('email'))
        rate('login-ip', request.remote_addr, 30, 900); rate('login-email', address, 8, 900)
        u = db.session.scalar(select(User).where(User.email == address))
        candidate = d.get('password', '')
        if not isinstance(candidate,str) or len(candidate)>256: abort(400)
        # Run the same password work for absent users.
        valid = check_password_hash(u.password if u and u.password else app.config['DUMMY_HASH'], candidate)
        if not u or not valid or not u.active or not u.verified: abort(401, 'Email or password is incorrect, or the account is unavailable.')
        return jsonify(challenge=challenge(u, 'login'))

    @app.post('/api/auth/invite')
    def accept_invite():
        rate('invite-ip', request.remote_addr, 15, 900)
        token=text(data(),'token',200); inv=db.session.get(Invite,digest(token))
        if not inv or inv.used or inv.expires<now(): abort(400,'Invitation is invalid or expired.')
        u=db.session.get(User,inv.user_id)
        if not u.active or u.verified: abort(400,'Invitation is unavailable.')
        return jsonify(challenge=challenge(u,'setup'),email=u.email)

    @app.post('/api/auth/reset')
    def reset():
        address=email(data().get('email')); rate('reset-ip',request.remote_addr,10,900)
        u=db.session.scalar(select(User).where(User.email==address))
        cid=uid()
        if u and u.active and u.verified: cid=challenge(u,'reset')
        return jsonify(challenge=cid)

    @app.post('/api/auth/resend')
    def resend():
        rate('resend-ip',request.remote_addr,15,900)
        c=db.session.get(Challenge,text(data(),'challenge',36))
        if not c or c.used or c.expires<now(): abort(400,'Start the sign-in or setup process again.')
        u=db.session.get(User,c.user_id)
        if not u.active: abort(400)
        return jsonify(challenge=challenge(u,c.purpose))

    @app.post('/api/auth/verify')
    def verify():
        d=data(); cid=text(d,'challenge',36); code=text(d,'code',6)
        if len(code)!=6 or not code.isascii() or not code.isdigit(): abort(400,'Enter the six-digit code.')
        rate('verify-ip',request.remote_addr,40,900)
        changed=db.session.execute(update(Challenge).where(Challenge.id==cid,Challenge.used==False,
            Challenge.expires>=now(),Challenge.attempts<5).values(attempts=Challenge.attempts+1)).rowcount
        db.session.commit()
        c=db.session.get(Challenge,cid)
        if not changed or not hmac.compare_digest(c.digest,digest(cid+':'+code)): abort(400,'Code is invalid or expired.')
        u=db.session.get(User,c.user_id)
        if not u.active: abort(403)
        if c.purpose in ('setup','reset'):
            password=d.get('password','')
            if not isinstance(password,str) or len(password)<14 or len(password)>128: abort(400,'Use a password between 14 and 128 characters.')
        consumed=db.session.execute(update(Challenge).where(Challenge.id==cid,Challenge.used==False).values(used=True)).rowcount
        if not consumed: db.session.rollback(); abort(400,'Code has already been used.')
        if c.purpose in ('setup','reset'):
            u.password=generate_password_hash(password); u.verified=True; u.epoch+=1
            db.session.execute(update(Invite).where(Invite.user_id==u.id).values(used=True))
            db.session.execute(update(Challenge).where(Challenge.user_id==u.id).values(used=True))
        audit('account.'+c.purpose,u.email); db.session.commit()
        session.clear(); session['uid']=u.id; session['epoch']=u.epoch; session.permanent=True
        return jsonify(ok=True)

    @app.post('/api/auth/logout')
    def logout():
        if g.user:
            g.user.epoch+=1; db.session.commit()
        session.clear(); return jsonify(ok=True)

    @app.get('/api/customers')
    @auth()
    def customers():
        return jsonify([dict(id=c.id,name=c.name,notes=c.notes,archived=c.archived,**customer_engineers(c.id)) for c in db.session.scalars(select(Customer).where(Customer.id.in_(allowed_ids())).order_by(Customer.name))])

    @app.post('/api/customers')
    @auth(('admin','manager'))
    def add_customer():
        d=data(); c=Customer(name=text(d,'name'),notes=text(d,'notes',2000,False)); db.session.add(c); db.session.flush()
        set_customer_engineers(c.id,d)
        if g.user.role=='manager': db.session.add(Access(user_id=g.user.id,customer_id=c.id))
        audit('customer.created',c.id); db.session.commit(); return jsonify(id=c.id),201

    @app.patch('/api/customers/<cid>')
    @auth(('admin','manager'))
    def edit_customer(cid):
        c=customer_access(cid,True); d=data()
        set_customer_engineers(cid,d)
        if 'name' in d: c.name=text(d,'name')
        if 'notes' in d: c.notes=text(d,'notes',2000,False)
        if 'archived' in d:
            if not isinstance(d['archived'],bool): abort(400)
            c.archived=d['archived']
            if c.archived:
                db.session.execute(update(Collector).where(Collector.customer_id==cid).values(archived=True))
                db.session.execute(update(Device).where(Device.customer_id==cid).values(archived=True))
                db.session.execute(update(Enrollment).where(Enrollment.customer_id==cid).values(used=True))
        audit('customer.updated',cid); db.session.commit(); return jsonify(ok=True)

    @app.post('/api/customers/<cid>/enrollment')
    @auth(('admin','manager'))
    def enrollment(cid):
        c=customer_access(cid,True)
        if c.archived: abort(400,'Restore the customer first.')
        token=secrets.token_urlsafe(24)
        db.session.add(Enrollment(digest=digest(token),customer_id=cid,expires=now()+900)); audit('collector.enrollment_created',cid); db.session.commit()
        return jsonify(code=token,expires=now()+900,endpoint='https://'+app.config['INGEST_HOST'])

    @app.get('/api/engineers')
    @auth(('admin',))
    def engineers():
        result=[]
        for u in db.session.scalars(select(User).order_by(User.name)):
            explicit=list(db.session.scalars(select(Access.customer_id).where(Access.user_id==u.id)))
            responsibilities={a.customer_id:a.position for a in db.session.scalars(select(CustomerEngineer).where(CustomerEngineer.user_id==u.id))}
            ids=set(explicit)|set(responsibilities)
            assigned=[dict(id=c.id,name=c.name,position=responsibilities.get(c.id,'assigned'),archived=c.archived)
                for c in db.session.scalars(select(Customer).where(Customer.id.in_(ids)).order_by(Customer.name))]
            result.append(dict(id=u.id,name=u.name,email=u.email,role=u.role,active=u.active,verified=u.verified,
                customers=sorted(ids),explicit_customers=explicit,assignments=assigned))
        return jsonify(result)

    @app.post('/api/engineers')
    @auth(('admin',))
    def add_engineer():
        d=data(); role=text(d,'role',20)
        if role not in ('admin','manager','viewer'): abort(400)
        address=email(d.get('email'))
        if db.session.scalar(select(User).where(User.email==address)): abort(409,'This email already has an account.')
        u=User(name=text(d,'name',120),email=address,role=role); db.session.add(u); db.session.flush()
        assign(u,d.get('customers',[])); audit('engineer.invited',address); db.session.commit(); invite(u)
        return jsonify(id=u.id),201

    def assign(u,ids):
        if not isinstance(ids,list) or len(ids)>500 or any(not isinstance(x,str) for x in ids): abort(400)
        if set(ids)-set(db.session.scalars(select(Customer.id))): abort(400,'Unknown customer.')
        db.session.execute(delete(Access).where(Access.user_id==u.id))
        for cid in set(ids): db.session.add(Access(user_id=u.id,customer_id=cid))

    @app.patch('/api/engineers/<uid_>')
    @auth(('admin',))
    def edit_engineer(uid_):
        u=db.session.get(User,uid_)
        if not u: abort(404)
        d=data()
        if uid_==g.user.id and ('active' in d or 'role' in d): abort(400,'Another administrator must change your role or account status.')
        if 'role' in d:
            if d['role'] not in ('admin','manager','viewer'): abort(400)
            u.role=d['role']
        if 'active' in d:
            if not isinstance(d['active'],bool): abort(400)
            u.active=d['active']
        if 'customers' in d: assign(u,d['customers'])
        u.epoch+=1
        if u.id==g.user.id: session['epoch']=u.epoch
        db.session.execute(update(Challenge).where(Challenge.user_id==u.id).values(used=True))
        audit('engineer.updated',u.email); db.session.commit(); return jsonify(ok=True)

    @app.post('/api/engineers/<uid_>/invite')
    @auth(('admin',))
    def resend_invite(uid_):
        u=db.session.get(User,uid_)
        if not u or u.verified or not u.active: abort(400)
        rate('invite-send',u.id,1,60); invite(u); audit('engineer.invitation_resent',u.email); db.session.commit(); return jsonify(ok=True)

    @app.get('/api/inventory')
    @auth()
    def inventory():
        ids=allowed_ids(); devices=[]
        for v in db.session.scalars(select(Device).where(Device.customer_id.in_(ids))):
            obs=list(db.session.scalars(select(Observation).join(Collector).where(Observation.device_id==v.id,Observation.observed_at>now()-172800,Collector.archived==False)))
            conflict=len(set(o.version for o in obs))>1
            failure=db.session.get(Failure,(v.collector_id,v.target)) if v.target else None
            failed=failure is not None and failure.at>=v.last_success
            devices.append(dict(id=v.id,customer_id=v.customer_id,name=v.name,product=v.product,version=v.version,collector_id=v.collector_id,
                last_success=v.last_success,archived=v.archived,rediscovered=v.rediscovered,conflict=conflict,
                observations=[dict(collector_id=o.collector_id,version=o.version,at=o.observed_at) for o in obs],
                status='Archived' if v.archived else 'Conflict' if conflict else 'Collection failed' if failed else 'Stale' if v.last_success<now()-172800 else 'Current'))
        return jsonify(devices)

    @app.patch('/api/devices/<did>')
    @auth(('admin','manager'))
    def archive_device(did):
        v=db.session.get(Device,did)
        if not v: abort(404)
        c=customer_access(v.customer_id,True); d=data()
        if not isinstance(d.get('archived'),bool): abort(400)
        if c.archived and not d['archived']: abort(400,'Restore the customer first.')
        v.archived=d['archived']; v.rediscovered=False; audit('device.archived' if v.archived else 'device.restored',did); db.session.commit(); return jsonify(ok=True)

    @app.get('/api/collectors')
    @auth()
    def collectors():
        return jsonify([dict(id=c.id,name=c.name,customer_id=c.customer_id,archived=c.archived,last_seen=c.last_seen,
            version=c.version,update_version=c.update_version,
            failures=[dict(target=f.target,category=f.category,at=f.at) for f in db.session.scalars(select(Failure).where(Failure.collector_id==c.id))])
            for c in db.session.scalars(select(Collector).where(Collector.customer_id.in_(allowed_ids())))])

    @app.post('/api/collectors/<cid>/archive')
    @auth(('admin','manager'))
    def archive_collector(cid):
        c=db.session.get(Collector,cid)
        if not c: abort(404)
        customer_access(c.customer_id,True); c.archived=True; audit('collector.revoked',cid); db.session.commit(); return jsonify(ok=True)

    @app.get('/api/history')
    @auth()
    def history():
        rows=db.session.execute(select(History,Device).join(Device).where(Device.customer_id.in_(allowed_ids())).order_by(History.at.desc()).limit(1000))
        return jsonify([dict(customer_id=d.customer_id,name=d.name,product=d.product,previous=h.previous,version=h.version,at=h.at) for h,d in rows])

    @app.get('/api/audit')
    @auth(('admin',))
    def audit_log():
        return jsonify([dict(actor=a.actor,action=a.action,subject=a.subject,at=a.at) for a in db.session.scalars(select(Audit).order_by(Audit.at.desc()).limit(500))])

    @app.post('/ingest/enroll')
    @csrf.exempt
    def enroll():
        rate('enroll-ip',request.remote_addr,20,900)
        d=data(); key=digest(text(d,'code',100)); name=text(d,'name')
        e=db.session.get(Enrollment,key)
        if not e or e.used or e.expires<now(): abort(401,'Enrollment code is invalid or expired.')
        customer=db.session.get(Customer,e.customer_id)
        if customer.archived: abort(403)
        count=db.session.execute(update(Enrollment).where(Enrollment.digest==key,Enrollment.used==False,Enrollment.expires>=now()).values(used=True)).rowcount
        if not count: db.session.rollback(); abort(401)
        token=secrets.token_urlsafe(48); c=Collector(customer_id=e.customer_id,name=name,digest=digest(token),last_seen=now())
        db.session.add(c); db.session.flush(); audit('collector.enrolled',c.id); db.session.commit()
        return jsonify(collector_id=c.id,customer_name=customer.name,token=token),201

    @app.post('/ingest/inventory')
    @csrf.exempt
    def ingest():
        token=request.headers.get('Authorization','')
        if not token.startswith('Bearer ') or len(token)>200: abort(401)
        c=db.session.scalar(select(Collector).where(Collector.digest==digest(token[7:]),Collector.archived==False))
        if not c or db.session.get(Customer,c.customer_id).archived: abort(401)
        rate('ingest',c.id,120,3600)
        d=data(); batch=text(d,'batch_id',36)
        try: uuid.UUID(batch)
        except ValueError: abort(400,'Invalid batch identifier.')
        if db.session.get(Receipt,(c.id,batch)): return jsonify(accepted=True)
        at=d.get('collected_at')
        if type(at)!=int or at<now()-8*86400 or at>now()+300: abort(400,'Invalid collection timestamp.')
        records=d.get('devices',[]); failures=d.get('failures',[])
        if not isinstance(records,list) or len(records)>2000 or not isinstance(failures,list) or len(failures)>500: abort(400)
        validated=[]
        for r in records:
            if not isinstance(r,dict): abort(400)
            product=text(r,'product',80)
            if product not in PRODUCTS: abort(400,'Unknown product.')
            validated.append((text(r,'identity',180),product,text(r,'name'),text(r,'version'),text(r,'target',160,False)))
        parsed_failures=[]
        for f in failures:
            if not isinstance(f,dict): abort(400)
            category=text(f,'category',40)
            if category not in ('unreachable','authentication','permissions','unsupported','query_failed'): abort(400)
            parsed_failures.append((text(f,'target'),category))
        ver=text(d,'version',80); available=text(d,'update_version',80,False)
        for identity,product,name,version,target in validated:
            v=db.session.scalar(select(Device).where(Device.customer_id==c.customer_id,Device.identity==identity,Device.product==product))
            if not v:
                v=Device(customer_id=c.customer_id,identity=identity,product=product,name=name,version=version,collector_id=c.id,last_success=at,target=target)
                db.session.add(v); db.session.flush()
            elif v.archived: v.rediscovered=True
            elif at>=v.last_success:
                if v.version!=version: db.session.add(History(device_id=v.id,previous=v.version,version=version,at=at))
                v.name=name; v.version=version; v.collector_id=c.id; v.last_success=at; v.target=target
            o=db.session.get(Observation,(v.id,c.id))
            if not o: db.session.add(Observation(device_id=v.id,collector_id=c.id,version=version,observed_at=at))
            elif at>=o.observed_at: o.version=version; o.observed_at=at
        # A delayed retry must not replace more recent failure/status information.
        latest=db.session.scalar(select(Receipt.at).where(Receipt.collector_id==c.id).order_by(Receipt.at.desc()).limit(1))
        if latest is None or at>=latest:
            db.session.execute(delete(Failure).where(Failure.collector_id==c.id))
            for target,category in dict(parsed_failures).items(): db.session.add(Failure(collector_id=c.id,target=target,category=category,at=at))
            c.version=ver; c.update_version=available
        c.last_seen=now(); db.session.add(Receipt(collector_id=c.id,batch_id=batch,at=at))
        db.session.commit(); return jsonify(accepted=True)

    @app.cli.command('init-db')
    def init_db():
        db.create_all(); click.echo('Database initialized.')

    @app.cli.command('bootstrap')
    @click.argument('address')
    def bootstrap(address):
        if db.session.scalar(select(User.id).limit(1)): raise click.ClickException('An account already exists. Bootstrap is disabled.')
        address=validate_email(address,check_deliverability=False).normalized.lower()
        u=User(email=address,name='Administrator',role='admin'); db.session.add(u); db.session.commit(); invite(u)
        click.echo('Administrator invitation sent. In local development, read instance/outbox.')

    @app.cli.command('prune')
    def prune():
        for model,col,cutoff in [(Challenge,Challenge.expires,now()-86400),(Rate,Rate.expires,now()),(Receipt,Receipt.at,now()-9*86400),(History,History.at,now()-365*86400)]:
            db.session.execute(delete(model).where(col<cutoff))
        db.session.commit(); click.echo('Expired transient data and old version history removed.')

    @app.cli.command('resend-setup')
    @click.argument('address')
    def resend_setup(address):
        u=db.session.scalar(select(User).where(User.email==address.lower(),User.verified==False,User.active==True))
        if not u: raise click.ClickException('No pending active account with this address.')
        invite(u); click.echo('Setup invitation resent.')

    app.config['DUMMY_HASH']=generate_password_hash(secrets.token_urlsafe(32))
    return app
