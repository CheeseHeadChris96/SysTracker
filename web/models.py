import time
import uuid
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
def uid(): return str(uuid.uuid4())
def now(): return int(time.time())

class User(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=uid)
    email = db.Column(db.String(254), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='viewer')
    password = db.Column(db.String(256))
    active = db.Column(db.Boolean, nullable=False, default=True)
    verified = db.Column(db.Boolean, nullable=False, default=False)
    epoch = db.Column(db.Integer, nullable=False, default=0)

class Customer(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=uid)
    name = db.Column(db.String(160), nullable=False)
    notes = db.Column(db.Text, nullable=False, default='')
    archived = db.Column(db.Boolean, nullable=False, default=False)

class Access(db.Model):
    user_id = db.Column(db.String(36), db.ForeignKey('user.id'), primary_key=True)
    customer_id = db.Column(db.String(36), db.ForeignKey('customer.id'), primary_key=True)

class CustomerEngineer(db.Model):
    __table_args__ = (db.UniqueConstraint('customer_id', 'user_id'),
        db.CheckConstraint("position IN ('primary', 'secondary')"),)
    customer_id = db.Column(db.String(36), db.ForeignKey('customer.id'), primary_key=True)
    position = db.Column(db.String(16), primary_key=True)
    user_id = db.Column(db.String(36), db.ForeignKey('user.id'), nullable=False)

class Challenge(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=uid)
    user_id = db.Column(db.String(36), db.ForeignKey('user.id'), nullable=False)
    purpose = db.Column(db.String(16), nullable=False)
    digest = db.Column(db.String(64), nullable=False)
    expires = db.Column(db.BigInteger, nullable=False)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    used = db.Column(db.Boolean, nullable=False, default=False)

class Invite(db.Model):
    digest = db.Column(db.String(64), primary_key=True)
    user_id = db.Column(db.String(36), db.ForeignKey('user.id'), nullable=False)
    expires = db.Column(db.BigInteger, nullable=False)
    used = db.Column(db.Boolean, nullable=False, default=False)

class Enrollment(db.Model):
    digest = db.Column(db.String(64), primary_key=True)
    customer_id = db.Column(db.String(36), db.ForeignKey('customer.id'), nullable=False)
    expires = db.Column(db.BigInteger, nullable=False)
    used = db.Column(db.Boolean, nullable=False, default=False)

class Collector(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=uid)
    customer_id = db.Column(db.String(36), db.ForeignKey('customer.id'), nullable=False)
    name = db.Column(db.String(160), nullable=False)
    digest = db.Column(db.String(64), unique=True, nullable=False)
    archived = db.Column(db.Boolean, nullable=False, default=False)
    last_seen = db.Column(db.BigInteger)
    version = db.Column(db.String(80), nullable=False, default='')
    update_version = db.Column(db.String(80), nullable=False, default='')

class Device(db.Model):
    __table_args__ = (db.UniqueConstraint('customer_id', 'identity', 'product'),)
    id = db.Column(db.String(36), primary_key=True, default=uid)
    customer_id = db.Column(db.String(36), db.ForeignKey('customer.id'), nullable=False)
    identity = db.Column(db.String(180), nullable=False)
    product = db.Column(db.String(80), nullable=False)
    name = db.Column(db.String(160), nullable=False)
    version = db.Column(db.String(160), nullable=False)
    collector_id = db.Column(db.String(36), db.ForeignKey('collector.id'), nullable=False)
    target = db.Column(db.String(160), nullable=False, default='')
    last_success = db.Column(db.BigInteger, nullable=False)
    archived = db.Column(db.Boolean, nullable=False, default=False)
    rediscovered = db.Column(db.Boolean, nullable=False, default=False)

class Observation(db.Model):
    device_id = db.Column(db.String(36), db.ForeignKey('device.id'), primary_key=True)
    collector_id = db.Column(db.String(36), db.ForeignKey('collector.id'), primary_key=True)
    version = db.Column(db.String(160), nullable=False)
    observed_at = db.Column(db.BigInteger, nullable=False)

class History(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=uid)
    device_id = db.Column(db.String(36), db.ForeignKey('device.id'), nullable=False)
    previous = db.Column(db.String(160), nullable=False)
    version = db.Column(db.String(160), nullable=False)
    at = db.Column(db.BigInteger, nullable=False)

class Receipt(db.Model):
    collector_id = db.Column(db.String(36), db.ForeignKey('collector.id'), primary_key=True)
    batch_id = db.Column(db.String(36), primary_key=True)
    at = db.Column(db.BigInteger, nullable=False, default=now)

class Failure(db.Model):
    collector_id = db.Column(db.String(36), db.ForeignKey('collector.id'), primary_key=True)
    target = db.Column(db.String(160), primary_key=True)
    category = db.Column(db.String(40), nullable=False)
    at = db.Column(db.BigInteger, nullable=False)

class Audit(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=uid)
    actor = db.Column(db.String(254), nullable=False)
    action = db.Column(db.String(80), nullable=False)
    subject = db.Column(db.String(180), nullable=False)
    at = db.Column(db.BigInteger, nullable=False, default=now)

class Rate(db.Model):
    key = db.Column(db.String(64), primary_key=True)
    count = db.Column(db.Integer, nullable=False, default=0)
    expires = db.Column(db.BigInteger, nullable=False)
