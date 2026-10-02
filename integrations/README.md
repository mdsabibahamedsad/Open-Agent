# Integrations

This directory contains third-party integrations for OpenAgent.

## Structure

Each integration should be in its own subdirectory:

```
integrations/
├── slack/
├── github/
├── gitlab/
├── jira/
├── linear/
├── notion/
└── ...
```

## Integration Requirements

Each integration must provide:

1. **Manifest** - `manifest.json` with metadata
2. **Authentication** - OAuth, API key, or other auth method
3. **Actions** - List of available actions/triggers
4. **Configuration** - Schema for user configuration
5. **Documentation** - README with setup instructions

## Manifest Format

```json
{
  "id": "slack",
  "name": "Slack",
  "description": "Send messages and receive events from Slack",
  "version": "1.0.0",
  "author": "OpenAgent Team",
  "category": "communication",
  "auth": {
    "type": "oauth2",
    "scopes": ["chat:write", "channels:read"]
  },
  "actions": [
    {
      "id": "send_message",
      "name": "Send Message",
      "description": "Send a message to a channel",
      "input_schema": { ... },
      "output_schema": { ... }
    }
  ],
  "triggers": [
    {
      "id": "new_message",
      "name": "New Message",
      "description": "Triggered when a new message is posted"
    }
  ]
}
```

## Development

See the main [CONTRIBUTING.md](../CONTRIBUTING.md) for development guidelines.