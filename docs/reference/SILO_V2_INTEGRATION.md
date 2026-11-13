# REST and MCP v2 integration credential

Both functions use the same authentication gateway. To provision one dedicated
read integration, create a confirmed password-based Auth identity and use the
existing owner-managed `api_user_tier` grant to give that identity Pro access.
Keep the password and identity in Edge secrets as
`SILO_INTEGRATION_AUTH_EMAIL`, `SILO_INTEGRATION_AUTH_PASSWORD` and
`SILO_INTEGRATION_AUTH_USER_ID`. The gateway uses this identity's short access
token for reads and rate counting.

Generate a key from 32 random bytes encoded as lowercase hex with the prefix
`silo_int_`. Give the raw value only to the authorized integration through its
secret store. Set `SILO_INTEGRATION_KEY_SHA256` to the lowercase hex SHA-256 of
the entire key and `SILO_INTEGRATION_KEY_EXPIRES_AT` to its ISO 8601 expiry, at
most 60 days from issue. To rotate or revoke, replace or unset the digest and
verify rejection on both live functions after the settings propagate. Deploy
`silo-api` and `silo-mcp-v2` from the same reviewed commit. Verify anonymous and
authenticated data calls before publishing instructions for the new credential.
