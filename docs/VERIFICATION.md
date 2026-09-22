# Verification record

Verified locally on macOS during initial implementation:

| Check | Result |
|---|---|
| Python security/inventory integration tests | 26 passed, including engineer assignments, access boundaries, and SQL TLS configuration |
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

Azure pilot checks on September 22, 2026:

- Infrastructure and budget deployments succeeded; SQL free allowance uses AutoPause.
- SQL schema initialization succeeded. The runtime account can read the schema and has no ALTER permission; the temporary workstation firewall rule was removed.
- All three application Key Vault references resolved.
- Dashboard deployment `63584b6f-347e-4b73-92ff-fd94d29db5ff` built successfully with the TLS-validating python-tds driver.
- The dashboard's Azure HTTPS `/health` endpoint returned `{"status":"ok"}`. This checks startup, not end-to-end production sign-in.
- The separate update service started successfully and returns HTTP 404 for the unpublished release manifest, as expected.

- Nine Cloudflare DNS records were imported; the existing SPF ending changed to `-all` with explicit owner approval. Microsoft 365 records were preserved.
- Managed certificates were issued and bound for dashboard, ingest, and updates hostnames. HTTPS requests validated the certificates; dashboard `/` and `/health` returned 200, ingest `/` returned 404, and the unpublished update manifest returned 404.
- The production sign-in page rendered in the browser.
- Azure verified Domain, SPF, DKIM, and DKIM2. The domain is linked and sender `systracker@hbstest.com` is configured. Azure Email accepted the initial production administrator invitation; the temporary bootstrap firewall rule was removed.

Not verified or not performed:

- Windows MSI installation, uninstall, service restart, DPAPI permissions, and upgrade rollback.
- WiX packaging was attempted locally; WiX explicitly reports Windows-only support and cannot build the MSI reliably on this Mac. Installer source and the Windows build script are provided; no MSI is claimed as delivered.
- Live customer Windows/Hyper-V, VMware, Veeam, or Palo Alto queries and minimum permissions.
- Administrator inbox receipt, end-to-end production sign-in, and backup restore. Infrastructure provisioning, SQL schema initialization, restricted SQL login, and application startup passed on September 22, 2026.
- A signed collector release; update checks deliberately fail closed until a real release key is configured.
- An independent security assessment or production load test.

No real customer has been enrolled. Azure Email accepted a production setup invitation to `administrator@hbstest.com`; inbox receipt has not yet been confirmed. The approved Azure pilot resources have been provisioned, including a billable B1 App Service plan and a $25 monthly budget alert. Budget alerts do not stop spending.
