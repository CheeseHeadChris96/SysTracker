import certifi
from sqlalchemy.pool import NullPool
from web import create_app


def test_legacy_sql_url_retains_credentials_and_enforces_tls(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'mssql+pymssql://test:dummy@pilot.database.windows.net:1433/systracker')
    app = create_app({'TESTING': True, 'SECRET_KEY': 'test-only-key'})
    assert app.config['SQLALCHEMY_DATABASE_URI'] == 'mssql+pytds://test:dummy@pilot.database.windows.net:1433/systracker'
    options = app.config['SQLALCHEMY_ENGINE_OPTIONS']
    assert options['poolclass'] is NullPool
    assert options['connect_args']['cafile'] == certifi.where()
    assert options['connect_args']['validate_host'] is True
    assert options['connect_args']['enc_login_only'] is False
