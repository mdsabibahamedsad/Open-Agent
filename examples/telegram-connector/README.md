# telegram-connector

Webhook connector: Bot API send + signed webhook receive. The bot token is a
`secrets:` reference resolved server-side; inbound updates verify the secret
token before JSON parsing/normalizing.

```bash
openagent test
openagent validate && openagent package && openagent publish
```
