# Customer engineer assignments

Administrators set a primary and secondary engineer when creating or editing a customer. Both are optional; an engineer cannot fill both positions for the same customer. An engineer can cover multiple customers, in either position. Enabled invited accounts can be assigned before they finish account setup, but sign-in still requires account verification.

Customer profiles and cards display both engineers, with an explicit Unassigned state. Disabled accounts retain their assignment label with a Disabled badge so coverage gaps remain visible; they cannot sign in or receive a new assignment.

The Engineers page and engineer profile list each explicitly assigned customer, its Primary/Secondary/Assigned designation, and archive status. Customer names link to their profiles. Administrator access to all customers is displayed separately from actual customer assignments.

Primary and secondary responsibilities grant customer access within the engineer's existing dashboard role. Customer managers and viewers can read assignment names for their accessible customers, but only administrators can change responsibilities because those changes affect access. Removing a responsibility removes that access source; any independently granted customer access remains. Additional access checkboxes do not silently remove primary or secondary responsibility.

## Existing database upgrade

This release adds a separate `customer_engineer` table with foreign keys and uniqueness constraints. It does not change or delete existing customer/user/access records. Before deploying new application code, take the normal database backup and run:

```sh
python -m flask --app web init-db
```

Run this schema step with schema-owner/deployment credentials, not the restricted production runtime user. The command creates the missing table; it is sufficient for this additive change only and is not a general migration system. Existing customers start with both positions unassigned. The local main and UI-fixture databases have already received this additive update.
