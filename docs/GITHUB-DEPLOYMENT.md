# GitHub and automatic dashboard updates

Source repository: https://github.com/CheeseHeadChris96/SysTracker (public by owner choice).

The Dashboard checks and deployment workflow tests pull requests and pushes to `main`. It runs Python integration tests, JavaScript syntax validation, collector signature checks, and a Windows collector build. It packages only dashboard source and dependencies. A failed check prevents deployment. Collector builds are validation only: this workflow never publishes an installer or update manifest.

Deployment remains off unless repository variable `AZURE_DEPLOY_ENABLED` equals `true`. No cloud resources or account emails are created by the workflow. Initial Azure infrastructure, SQL setup, DNS, and email verification are separate steps in [AZURE.md](AZURE.md).

## One-time GitHub/Azure connection

1. Create the GitHub environment `production`. Restrict deployment branches to `main`. Protect `main` with required checks `checks` and `collector-checks`, and require pull requests before merging. Available protection features depend on the repository plan and visibility. Restrict who can change workflows and merge to this branch.
2. Create a dedicated deployment identity in Azure with a federated credential: issuer `https://token.actions.githubusercontent.com`, subject `repo:CheeseHeadChris96/SysTracker:environment:production`, audience `api://AzureADTokenExchange`.
3. Assign that identity Website Contributor scoped to the dashboard App Service only. Do not give it subscription-wide Contributor or access to the separate collector update app. App deployment rights can replace application code and must be treated as privileged access.
4. Add environment secrets `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, and `AZURE_SUBSCRIPTION_ID`. These are identity identifiers, not a client password. No publishing password, SQL administrator password, or signing key belongs in GitHub.
5. Add environment variables `AZURE_WEBAPP_NAME` and `AZURE_RESOURCE_GROUP` using the actual deployment output. Keep basic SCM/FTP authentication disabled. The workflow uses Azure CLI deployment with federated login.
6. Complete the database upgrade/restore procedure below and first-production verification in AZURE.md. Only then set repository variable `AZURE_DEPLOY_ENABLED=true` and run the workflow from `main`.

Once enabled, merging tested changes into `main` deploys the dashboard automatically. Page refresh loads the new UI. The Basic plan can briefly interrupt requests during deployment. It has no staging-slot swap in this setup.

The health check verifies that the application responds; it does not verify SQL access, email delivery, or the deployed commit identity. First-production acceptance must include sign-in and customer inventory checks.

## Database changes and rollback

Automatic application deployment is prepared, but production schema migrations are not yet automated. Before enabling production auto-deploy, introduce and test versioned migrations against Azure SQL and verify a restore. Do not run `init-db` automatically on every application restart: it only creates missing tables and cannot upgrade existing columns.

For the current initial deployment, initialize a fresh schema with the documented schema-owner step. For existing pilot databases, the only additive upgrade so far is [engineer assignments](ENGINEER-ASSIGNMENTS.md). Never upload the local SQLite databases to replace production data.

For a future schema-changing release, disable `AZURE_DEPLOY_ENABLED`, verify backup retention and a restore point, apply the reviewed backwards-compatible migration with the deployment/schema-owner identity, and verify it before enabling application deployment again. Destructive changes need a separate maintenance plan. Runtime SQL credentials stay restricted.

Keep each successful workflow's dashboard artifact (retained 30 days) and its commit SHA. For an application-only rollback, disable automatic deployment, download the last known-good `dashboard-<commit>` artifact, extract `web.zip`, and deploy it with the same `az webapp deploy` command from AZURE.md. Then revert the source change through a pull request before re-enabling automatic deployment. Reverting code does not roll back database changes; check compatibility first. Failed health checks fail the workflow but do not automatically restore an earlier release.

## Public repository contents

Commit application source, infrastructure templates, tests, and example configuration only. Never commit `instance/`, `.env`, SQLite files, generated packages, database connection strings, invitation links, enrollment tokens, or release private keys. The initial upload uses an explicit source allowlist. `.gitignore` helps later commits but does not scan for secrets inside source files.

Actions are pinned to verified commit SHAs. Dependabot proposes action updates monthly; these are not automatically merged. Cloud hosting charges and GitHub Actions usage remain subject to the account's rates and allowances.

References: [Azure GitHub deployments](https://learn.microsoft.com/en-us/azure/app-service/deploy-continuous-deployment), [Azure OIDC login action](https://github.com/Azure/login).
