# High-Risk Actions (MP19)

Defaults are conservative; organizations make them stricter, never looser
than the platform baseline.

## Always require approval

- Destructive: delete production data, drop database, delete repository / cloud resource.
- Privileged: change org owner, modify platform config, create platform credentials, change security policy.
- External: send email/message, publish content, submit forms, external API mutations, browser purchases.
- Financial: payment, purchase, refund, transfer, billing changes.
- Code: merge to protected branch, production deploy, privileged execution, infra changes, force push.
- Credential: create / rotate / expose / re-permission credentials.

## Never allowed

- Production database deletion (`DENY`, platform mandatory).
- Unknown action categories / unknown tools reaching execution (`REQUIRE_APPROVAL` minimum).

## Categories

`READ, WRITE, UPDATE, DELETE, DEPLOY, EXECUTE_CODE, NETWORK_ACCESS,
SEND_MESSAGE, SEND_EMAIL, PUBLISH_CONTENT, MODIFY_REPOSITORY, CREATE_COMMIT,
CREATE_BRANCH, CREATE_PULL_REQUEST, MERGE_CODE, CHANGE_CONFIGURATION,
ACCESS_CREDENTIAL, ACCESS_SENSITIVE_DATA, FINANCIAL_ACTION, ACCOUNT_ACTION,
USER_ADMINISTRATION, ORGANIZATION_ADMINISTRATION, INFRASTRUCTURE_ACTION,
BROWSER_EXTERNAL_ACTION, MCP_ACTION, SANDBOX_EXECUTION` (+ registry extensions).
