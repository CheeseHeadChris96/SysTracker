# Verification record

Verified locally on macOS during initial implementation:

| Check | Result |
|---|---|
| Python security/inventory integration tests | 25 passed, including engineer assignments and access boundaries |
| Update manifest verification checks | 5 passed: valid signature, tampering, unexpected host, HTTP, downgrade |
| Windows .NET collector compilation | Passed |
| Windows x64 self-contained publish | Passed; output in `dist/collector` |
| PowerShell connector/build-script parsing | Passed using official PowerShell parser |
| Azure main and budget Bicep compilation | Passed |
| Browser password and six-digit code sign-in | Passed against isolated local fixture |
| Browser product filtering and customer creation | Passed against isolated local fixture |
| Browser primary/secondary assignments and engineer customer links | Passed against isolated local fixture |
| Desktop and 390px-wide layout inspection | Passed; tables/navigation scroll where needed |
| Web source package | Created from allowlist excluding local state and secrets |

Not verified or not performed:

- Windows MSI installation, uninstall, service restart, DPAPI permissions, and upgrade rollback.
- WiX packaging was attempted locally; WiX explicitly reports Windows-only support and cannot build the MSI reliably on this Mac. Installer source and the Windows build script are provided; no MSI is claimed as delivered.
- Live customer Windows/Hyper-V, VMware, Veeam, or Palo Alto queries and minimum permissions.
- Azure deployment, SQL dialect execution against Azure SQL, email delivery, certificate issuance, and backup restore.
- Cloudflare DNS changes.
- A signed collector release; update checks deliberately fail closed until a real release key is configured.
- An independent security assessment or production load test.

No real customer has been enrolled. No email has been sent to `administrator@hbstest.com`; its development invitation is in the local outbox. No billable cloud resources have been provisioned.
