# SysTracker

Customer-organized infrastructure inventory: a browser dashboard and an outbound-reporting Windows collector.

**Status: local pilot implementation, not deployed or production certified.** The dashboard has been exercised locally; the collector compiles for Windows. Actual MSI install/upgrade/uninstall, Azure SQL/email, and customer product connections still require their respective environments. No customer credentials are included.

## What is implemented

- Invitation-only email/password accounts, six-digit codes at setup and sign-in, password reset, expiring codes, throttling, and session revocation.
- Administrator, customer manager, and viewer roles with server-enforced customer assignments.
- Customer creation/editing/archive; engineer invitations and access management.
- Primary and secondary engineer assignments on customer profiles, with linked customer lists under each engineer. See [assignment behavior and database upgrade](docs/ENGINEER-ASSIGNMENTS.md).
- Single-use collector enrollment, reporting-token revocation, customer-scoped inventory, retry deduplication, conflicting collector observations, stale/failed collection status, version history, archive, and CSV export.
- Windows GUI and Windows service; encrypted local configuration and credentials, daily collection, offline queue, connection tests, and diagnostics.
- Fixed inventory query adapters for Windows/Hyper-V, vSphere, Veeam REST, and PAN-OS XML API. Compatibility is provisional until tested against the pilot's exact versions.
- Daily update checks, GUI-only update installation, pinned release signing key, SHA-256 verification, and downgrade rejection. Updates fail closed until the release public key is configured.
- Azure Bicep templates, budget alerts, deployment helper, separate update-serving application, and release-signing helper.
- GitHub Actions checks and an Azure dashboard deployment workflow, disabled until production is configured. See [GitHub setup and rollback](docs/GITHUB-DEPLOYMENT.md).

## Local dashboard

Requires Python 3.12 or later.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m flask --app web init-db
.venv/bin/python -m flask --app web bootstrap administrator@hbstest.com
.venv/bin/python -m flask --app web run --host 127.0.0.1 --port 5080
```

Open `http://127.0.0.1:5080`. Development email is written to `instance/outbox/` with restricted permissions; nothing is emailed. Open the invitation link in the most recent invitation file, request a code, read the new local code message, and set your password. Use `flask --app web resend-setup administrator@hbstest.com` if an invitation expires. Bootstrap cannot overwrite an existing account.

The first local invitation has already been created for `administrator@hbstest.com`. Customer inventory starts empty. Never expose the development server publicly.

`.env.example` documents configuration; variables must be exported or supplied by the hosting platform. It is not automatically loaded. Session keys and state are under ignored `instance/`; preserve the session key between restarts.

## Separate UI demonstration

`python scripts/ui-fixture.py` runs a separate synthetic-data database on `http://127.0.0.1:5081`. The test account is `preview@example.com`; its random password is in `instance/ui-fixture/password.txt`. Its email codes go to `instance/ui-fixture/outbox/`. This fixture is excluded from deployment packages and never mixes with your customer database.

## Verification

```sh
.venv/bin/python -m pytest -q
dotnet run --project tests/ReleaseVerification
dotnet build collector/SysTracker.Collector.csproj -c Release
```

See [verification results](docs/VERIFICATION.md), [Azure deployment](docs/AZURE.md), [collector setup](docs/COLLECTOR.md), and [security boundaries](docs/SECURITY.md).

## Packaging

```sh
.venv/bin/python scripts/package-web.py
```

This creates `dist/web.zip` from an explicit source allowlist, excluding all local secrets and test records. On Windows, `scripts/build-collector.ps1` builds the service/GUI and MSI. The currently cross-published `dist/collector/` is a Windows x64 application build, **not a tested installer**.

## Deliberate pilot limits

- Windows targets are configured explicitly; automatic AD discovery is not implemented.
- No vendor lifecycle feeds, vulnerability scoring, target-version rules, or remote actions.
- Veeam versions without the documented REST endpoint are not yet supported; no unverified registry fallback is silently used.
- Read permissions must be validated for each product. Veeam's documented `serverInfo` endpoint requires Backup Administrator, despite the collector only issuing a read query.
- No production database migration history yet: `init-db` creates missing tables but cannot alter existing columns. The additive engineer-assignment table upgrade is documented above; future structural changes require a migration and backup/restore test.
- Archived records remain until an explicit future retention/deletion workflow; no automatic customer-data deletion.
- Single-region pilot hosting; no high-availability or disaster-recovery claims.
