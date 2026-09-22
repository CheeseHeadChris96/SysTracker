# Security boundaries

- Dashboard identities authorize customer records, not infrastructure access. Administrators cannot dispatch collector commands. Only two ingestion endpoints exist: enrollment and inventory submission.
- Reporting credentials are random, HMAC-hashed centrally, tied to one collector/customer, and independently revocable. Enrollment credentials expire in 15 minutes and are consumed atomically. The uploaded customer field is ignored.
- Browser requests require authenticated, active, verified users; authorization is checked server-side for each customer. Mutation endpoints require CSRF tokens. Cookies use HttpOnly, Strict SameSite, and Secure in production. Sessions expire after eight hours; logout and account changes revoke older session epochs.
- Password hashes use Werkzeug scrypt. Verification codes are random six-digit values, HMAC-hashed with challenge identity, single-use, expire after ten minutes, and permit five attempts. Resends invalidate old challenges and are throttled. Login and reset endpoints use persistent database rate limits.
- Email-code authentication depends on mailbox security and is not phishing-resistant. There is no bypassing recovery code or public administrator-reset endpoint.
- Production fails startup without HTTPS configuration, an external database, a strong persistent secret, and real email mode. Local email outboxes and test fixtures never ship in the application ZIP.
- Collector data is encrypted locally with DPAPI and restricted directory ACLs. Local admin/SYSTEM access can recover machine-protected credentials. Protect and patch the collector host accordingly.
- Only fixed queries run locally. APIs used to read inventory can expose broader management capabilities to the supplied credentials; notably Veeam's Backup Administrator requirement. Credential permissions need pilot validation.
- Update signing private keys never reside in the application or update server. The updater accepts only signed metadata, validates the MSI hash and exact origin, rejects downgrades, and executes only after a local GUI action.
- Runtime database permissions exclude schema administration. SQL connections require encryption, trusted CA, and hostname validation. Key Vault holds application secrets; database and SMTP/API credentials are never displayed by the dashboard.
- Infrastructure application request bodies and query parameters must not be captured in logs. Audit records describe actions and identifiers, not passwords/tokens. Diagnostics contain inventory names and should be reviewed before sharing.

## Limits requiring validation

The source has automated boundary tests, not an independent security audit. Windows DPAPI/ACL behavior, service identity, MSI lifecycle, vendor permissions, live Azure RBAC, TLS chains, SQL restore, and email deliverability need environment-specific verification. The deployment has no WAF or dedicated private SQL network; SQL is firewall-restricted to application egress addresses with authenticated TLS. Request-level account rate limits work without trusting forwarded IP headers; behind Azure, IP limits can be shared by proxy traffic and should be tuned after observing topology rather than blindly trusting spoofable headers.
