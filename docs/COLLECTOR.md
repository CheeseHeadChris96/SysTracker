# Windows collector pilot

## Build and install

The initial host target is Windows Server 2019/2022/2025 with Desktop Experience, Windows PowerShell 5.1, and direct outbound HTTPS. Other Windows host versions and Server Core are not certified. The GUI requires desktop access; the service runs without a signed-in user.

On a Windows build machine with .NET 10 SDK and WiX 5.0.2:

```powershell
dotnet tool install --global wix --version 5.0.2
.\scripts\build-collector.ps1 -UnsignedPilot
```

The switch allows a local pilot build with update installation disabled by the missing release trust key. It does not make the MSI trusted for production distribution. For release builds, configure the public key, sign required artifacts, and omit the switch. WiX/MSI execution has not been verified on this Mac.

Install the MSI as a local administrator. Open SysTracker Collector from the Start menu. Enter the single-use code from the customer's Add collector dialog. The reporting origin is built in: `https://ingest.hbstest.com`; enrollment requires working DNS and a trusted certificate. There is no cloud-controlled endpoint override.

The service is `SysTrackerCollector`. Local data is under `%ProgramData%\SysTracker`, accessible only to SYSTEM and local administrators. Configuration, credentials, queue contents, and status use Windows DPAPI machine protection. The service runs as LocalSystem; explicit target credentials are passed privately through a child process's stdin, not its command line. Local administrators and SYSTEM can access these secrets and are part of the trust boundary.

## Connections

| Product | Local interface | Prerequisites / limits |
|---|---|---|
| Windows Server | CIM over WinRM, HTTPS 5986 by default | Target firewall allows collector; trusted WinRM certificate; account authorized for WinRM and WMI namespace reads. HTTP 5985 option uses Negotiate authentication; do not enable Basic or unencrypted WinRM. Validate Kerberos/domain behavior in pilot. |
| Hyper-V | Same Windows query plus `vmms` service identification | Choose Hyper-V target type. Produces both Windows release and Hyper-V host records. No VM management methods are invoked. |
| vCenter / standalone ESXi | vSphere SOAP API, HTTPS 443 | Read-only inventory account scoped appropriately, trusted certificate; host UUID and config.product properties. Transient API session/view objects are created and destroyed; no host/VM configuration changes. |
| Veeam | HTTPS 9419, OAuth session, `/api/v1/serverInfo` | API revision must match installed VBR. The documented endpoint requires **Backup Administrator**, a broader credential than the query needs. Do not assume a read-only role works. Versions lacking this endpoint require later adapter work. |
| Palo Alto | HTTPS 443 XML API key generation and `show system info` | Dedicated account with necessary API/operational permissions; trusted management certificate. Minimum role must be tested; operational API access is not necessarily limited to this one command by the vendor. |

The service must trust customer-issued certificates in the Local Computer trust store. Do not turn off certificate validation to handle private PKI. Allow required **local** collector-to-target connections; no inbound internet rule is required on the collector.

Each connection is added explicitly by hostname/IP. Test connection reads inventory without saving a cloud report. Collection runs every 24 hours by default, configurable locally from 1 to 168 hours. Dashboard stale threshold is currently 48 hours, so longer schedules intentionally appear stale until this threshold becomes configurable.

`Collect now` writes a protected local request file which the service checks within five minutes. Uploads retry every five minutes while queued. Offline storage is capped at seven days, 168 reports, or 50 MB; oldest expired/overflow reports are discarded with a visible count. The last known local report remains available.

## Updates

The service checks daily and the GUI checks when opened. Only the GUI can call the installation routine, after the engineer chooses Update now and confirms. Checks verify a signed manifest against an embedded RSA public key. The package hash and download origin are checked before MSI starts. HTTPS redirects are not followed for reporting or updates.

MSI major upgrade is authored to preserve local data and use Windows Installer rollback. Failed-upgrade recovery still requires a Windows test; it is not established by compilation. Collectors never receive commands, schedules, scripts, credentials, or update instructions from the dashboard.

## Removal

Use Windows Installed Apps to uninstall. The MSI stops/removes the service, removes application files and shortcut, and calls the local purge operation for stored credentials, queue, and configuration. Upgrade removal is excluded from purge. After removal, archive/revoke the collector in the customer's dashboard. Review dedicated accounts in customer systems separately; they may be shared with other tools.

## Required pilot checks

1. Install, enroll, and run after Windows reboot with no user logged in.
2. Test each connector using the actual product version and minimum available permissions; compare with vendor consoles.
3. Confirm credential files cannot be read by an ordinary Windows user.
4. Interrupt internet access, collect, restore connectivity, and confirm retry deduplication.
5. Revoke enrollment identity and confirm reporting stops.
6. Publish a signed test update, confirm no automatic installation, then test GUI installation and forced failure recovery.
7. Uninstall and confirm service, binaries, local credentials, queue, and configuration are removed.

Reference endpoints: [Microsoft CIM](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_cimsession), [vSphere API](https://developer.broadcom.com/xapis/vsphere-web-services-api/latest/), [Veeam server info](https://helpcenter.veeam.com/references/vbr/13/rest/1.3-rev2/tag/Service/index.html), [PAN-OS XML API](https://docs.paloaltonetworks.com/ngfw/api/getting-started/explore-xmlapi).
