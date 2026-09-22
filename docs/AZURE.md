# Azure pilot deployment

No Azure resources or Cloudflare records have been created. Local template compilation does not establish regional SKU availability, subscription eligibility, RBAC rights, DNS ownership, or real email delivery.

## Planned resources and cost controls

One Linux B1 App Service plan hosts two applications: dashboard/ingestion and a separate read-only update site. Azure SQL uses the free serverless offer with `AutoPause` at the free limit. Key Vault holds session, database, and dedicated ACS credentials. The update application has no managed identity or access to these secrets. Azure Communication Services handles account email.

Planning budget is roughly US $15–$25/month at light pilot use, subject to region, traffic, and subscription rates. SQL auto-pause can make the dashboard unavailable after its monthly allowance is exhausted. Use database `NullPool` to avoid keeping sessions open unnecessarily. Email, logs, downloads, and excess services are not capped by the database limit. Budget notifications at $10/$20/$25 are alerts, not hard caps. No paid registry, gateway, managed Redis, or VM is provisioned.

Official pricing references:
- https://azure.microsoft.com/en-us/pricing/details/app-service/linux/
- https://learn.microsoft.com/en-us/azure/azure-sql/database/free-offer
- https://learn.microsoft.com/en-us/azure/communication-services/concepts/email-pricing

## 1. Authenticate and prepare

Use an account authorized for the subscription/resource group and role assignments. Install Azure CLI and sign in yourself (`az login`). Do not send cloud passwords or keys through chat.

```sh
python scripts/deploy-azure.py --subscription YOUR_SUBSCRIPTION_ID --prefix YOUR_UNIQUE_PREFIX
```

The default region is `centralus`; change `--region` if necessary. This selects the subscription and writes restricted local parameter files but creates no resources. The parameter file contains secrets; it is ignored and excluded from packaging. On Windows, additionally restrict the directory ACL to your administrator account.

Preserve the parameter file in a password manager or other approved secret store. Reusing it avoids rotating the session key and database password on a redeployment. Do not rerun initial deployment with regenerated secrets against an existing database.

```sh
python scripts/deploy-azure.py --subscription YOUR_SUBSCRIPTION_ID --prefix YOUR_UNIQUE_PREFIX --apply
```

The helper creates the resource group, shows ARM what-if, asks for `DEPLOY`, creates the resources, and deploys budget alerts. Inspect the actual estimate before confirming. The resource provider may reject the SQL free offer if unavailable; do not silently switch to paid serverless.

## 2. Initialize SQL

The template restricts SQL firewall rules to the web app's possible outbound addresses. For initialization, temporarily allow **only your workstation's public IP** using Azure SQL networking, then run:

```sh
python scripts/initialize-sql.py --parameters instance/deployment/YOUR_PREFIX.parameters.json
```

It creates the initial tables and a separate contained application user with SELECT/INSERT/UPDATE/DELETE permissions on the application schema. SQL administrative credentials never become the application's runtime connection string. Remove the temporary workstation firewall rule afterward. Validate the TLS trust chain; never bypass certificate checks. Reconcile app egress firewall rules after plan changes.

For later upgrades, back up first and apply an explicit schema migration. `create_all` is not a migration system.

## 3. Cloudflare DNS and HTTPS

Use the deployment output's actual hostnames and verification IDs. Add **DNS-only** records initially so Azure custom-domain verification and managed certificates work directly:

| Cloudflare record | Value |
|---|---|
| CNAME `systracker` | Dashboard app `dnsTarget` |
| CNAME `ingest` | Same dashboard app `dnsTarget` |
| CNAME `updates` | Update app `updatesDnsTarget` |
| TXT `asuid.systracker` | Dashboard `domainVerificationId` |
| TXT `asuid.ingest` | Dashboard `domainVerificationId` |
| TXT `asuid.updates` | Update app `updatesVerificationId` |

Add the custom domains in each App Service and create/bind free managed certificates. HTTPS must validate from a Windows Server before enrollment. The production application rejects dashboard routes on the ingestion hostname and vice versa. The default Azure hostname exposes only `/health`; use the custom hostname for the UI.

## 4. Configure account email

In the created Email Communication Service, open the `hbstest.com` custom domain. Copy its exact verification, SPF, and DKIM records into Cloudflare. Merge SPF requirements into any existing SPF record; do not create a second SPF record or replace Microsoft 365's settings. Do not change existing MX records.

Complete verification, link the verified domain to the dedicated Communication Service, and configure the `systracker` sender username. The application reads that dedicated service's connection string through Key Vault. It has no Azure management role on ACS. Test delivery to `administrator@hbstest.com`, including spam handling and resend limits, before inviting engineers.

## 5. Deploy application code

```sh
python scripts/package-web.py
az webapp deploy --resource-group YOUR_PREFIX-systracker --name YOUR_PREFIX-web --src-path dist/web.zip --type zip
```

Use Azure CLI's authenticated deployment; basic SCM and FTP credentials are disabled. The package installs pinned requirements and runs `startup.sh` under Gunicorn. If deployment doesn't support this authentication mode in your CLI version, update the CLI; do not enable basic publishing authentication as a shortcut.

After the schema and email service are ready, run this once in the App Service SSH terminal using the deployed Python environment:

```sh
python -m flask --app web bootstrap administrator@hbstest.com
```

The invitation is actually emailed only in production. If delivery fails, repair the sender configuration and run `resend-setup` for that pending account. Keep production `MAIL_MODE=azure`; the application refuses file-based email in production.

## 6. Updates and collector distribution

Do not publish a release until the Windows pilot checklist in COLLECTOR.md passes. Create an encrypted RSA release key on a trusted release workstation; keep the private key off Azure and out of source. Put only its public key in `collector/update-public-key.pem` before building. Sign the MSI and PowerShell scripts with an approved Windows code-signing certificate where required by your policy; price and procure that separately.

`scripts/sign-release.py` creates an RSA-PSS signed manifest and copies the matching installer into `updates/releases`. Stage `stable.json`, `stable.sig`, and the MSI together in a new update-site package, then deploy that package to the separate update app. The folder also needs `updates/app.py` and `updates/requirements.txt` at its root.

No signing private key is present in the dashboard, update server, or collector. A missing/invalid key, invalid signature, unexpected download host, hash mismatch, or downgrade stops update installation.

## 7. Operations before onboarding

- Confirm real email delivery, enrollment over HTTPS, customer isolation, and SQL reconnection after auto-pause.
- Restore an Azure SQL point-in-time backup into a separate database and verify representative records. Record the recovery procedure and actual retention policy.
- Arrange a daily maintenance execution of `python -m flask --app web prune` in the deployed environment. Until scheduling is configured, run it manually; it removes expired auth/rate/receipt records and history older than 12 months, never archived customers/devices.
- Review logging, email quotas, billing alerts, and the actual monthly estimate. Do not enable request-body capture or SQL parameter logging.
- Use the GUI to create the pilot customer manually and enroll its collector. Enter customer collection credentials locally only.

Initial external prerequisites remaining: authenticated Azure access/subscription selection, Cloudflare changes, email verification, a Windows pilot machine, and a release-signing identity. None are replaced by local test success.
