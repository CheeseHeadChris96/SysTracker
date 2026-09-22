"""Disposable local UI verification database. Not included in web deployment packages."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from web import create_app
from web.models import *
from werkzeug.security import generate_password_hash
import secrets
root=Path(__file__).resolve().parents[1]/'instance'/'ui-fixture'
root.mkdir(parents=True,exist_ok=True)
app=create_app({'SQLALCHEMY_DATABASE_URI':'sqlite:///'+str(root/'fixture.db'),'MAIL_MODE':'file'})
app.instance_path=str(root)
with app.app_context():
    db.create_all()
    if not db.session.get(User,'test-engineer'):
        password=secrets.token_urlsafe(24)
        (root/'password.txt').write_text(password);(root/'password.txt').chmod(0o600)
        db.session.add(User(id='test-engineer',name='Preview Engineer',email='preview@example.com',role='admin',verified=True,password=generate_password_hash(password)))
        db.session.add_all([Customer(id='sample-a',name='Example • Northwind',notes='Synthetic data for local UI testing'),Customer(id='sample-b',name='Example • Contoso',notes='Synthetic data for local UI testing')]);db.session.flush()
        db.session.add(Collector(id='sample-collector',name='Main Office',customer_id='sample-a',digest='not-a-real-token',last_seen=now(),version='0.1.0'));db.session.flush()
        for i,(name,product,version) in enumerate([('DC-01','Windows Server','Windows Server 2022'),('HV-01','Hyper-V','Windows Server 2019'),('ESXi-01','VMware ESXi','8.0.3 build 24022510'),('BACKUP-01','Veeam Backup & Replication','12.3.0.310'),('FW-01','Palo Alto PAN-OS','11.1.4')]):
            db.session.add(Device(customer_id='sample-a',identity='sample-'+str(i),product=product,name=name,version=version,collector_id='sample-collector',last_success=now()-(200000 if i==3 else 1000)))
        db.session.commit()
    if not db.session.get(User,'sample-support'):
        db.session.add(User(id='sample-support',name='Sample Support Engineer',email='support@example.com',role='viewer',verified=False))
        db.session.flush()
        if not db.session.get(CustomerEngineer,('sample-a','primary')):
            db.session.add(CustomerEngineer(customer_id='sample-a',position='primary',user_id='test-engineer'))
        if not db.session.get(CustomerEngineer,('sample-a','secondary')):
            db.session.add(CustomerEngineer(customer_id='sample-a',position='secondary',user_id='sample-support'))
        db.session.commit()
app.run(host='127.0.0.1',port=5081)
