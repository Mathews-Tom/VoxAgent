# Admin Bootstrap

## Platform Admin

Seed a platform admin at startup by setting:

| Variable                  | Purpose                                                    |
| ------------------------- | ---------------------------------------------------------- |
| `PLATFORM_ADMIN_EMAIL`    | Login email for the platform administrator                 |
| `PLATFORM_ADMIN_PASSWORD` | Bootstrap password; converted to Argon2id on first startup |

If both variables are set, the server creates the admin user if it does not already exist.

## Tenant Admin Onboarding

Public onboarding now uses `POST /api/public/tenants` and requires:

| Field         | Notes                                    |
| ------------- | ---------------------------------------- |
| `name`        | Tenant display name                      |
| `domain`      | Tenant domain / identifier               |
| `admin_email` | Initial tenant admin login               |
| `password`    | Minimum 8 characters; stored as Argon2id |

The onboarding flow creates:

1. The tenant record
2. The initial tenant admin principal
3. The tenant membership binding the admin to that tenant

## Login Contract

Dashboard login uses admin email and password. Legacy SHA-256 hashes are still accepted during migration and are rewritten to Argon2id after a successful login.
