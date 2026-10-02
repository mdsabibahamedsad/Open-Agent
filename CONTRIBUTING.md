# Contributing to OpenAgent

Thank you for your interest in contributing to OpenAgent! This document provides guidelines for contributing to the project.

## Code of Conduct

By participating in this project, you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md). Please report unacceptable behavior to conduct@openagent.dev.

## How to Contribute

### Reporting Bugs

1. Check if the bug has already been reported in [Issues](https://github.com/openagent/openagent/issues)
2. If not, create a new issue with:
   - Clear title and description
   - Steps to reproduce
   - Expected vs actual behavior
   - Environment details (OS, Node/Python versions, Docker version)
   - Screenshots if applicable

### Suggesting Features

1. Check existing issues and discussions
2. Create a feature request issue with:
   - Clear use case
   - Proposed solution
   - Alternatives considered
   - Potential implementation approach

### Pull Requests

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature-name`
3. Make your changes following our guidelines
4. Run tests and linting locally
5. Commit with conventional commit messages
6. Push to your fork
7. Open a Pull Request against `main`

### Extension Contributions

Extensions (agents, tools, connectors, MCP servers, skills, evaluators, …)
are first-class contributions — see [`docs/developers/`](docs/developers/README.md):

1. Scaffold with `openagent init --type <kind> --name <slug>` or copy the
   matching starter from `templates/`.
2. Keep `openagent.yaml` field names exact (see
   `apps/api/src/openagent/developer/manifest.py`); declare only the
   permissions your extension needs.
3. Never commit secrets — use `secrets:` references. `openagent validate`
   and the publish scan gate will reject embedded credentials.
4. Add/update an example under `examples/` and cover new behavior with tests
   (`openagent test` harness + co-located unit tests).
5. Run `openagent validate && openagent package` and include the scan report
   in your PR. Sign published versions with your own Ed25519 `key_id`.
6. Follow the security rules in `docs/developers/security.md` and
   `SECURITY.md` (sandbox-only execution, SSRF allowlists, prompt-injection
   handling, dependency pins + SBOM).

## Development Setup

### Prerequisites

- Node.js 20+
- Python 3.11+
- pnpm 8.15+
- Docker & Docker Compose
- Git

### Initial Setup

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/openagent.git
cd openagent

# Add upstream remote
git remote add upstream https://github.com/openagent/openagent.git

# Install dependencies
pnpm install

# Set up environment
cp .env.example .env

# Start services
docker compose up -d

# Run database migrations
cd apps/api && alembic upgrade head

# Verify everything works
pnpm test
```

## Coding Standards

### TypeScript (Frontend & Packages)

- Use strict TypeScript configuration
- Prefer interfaces over types for object shapes
- Use functional components with hooks
- Follow React best practices
- Use `cn()` utility for class names
- Co-locate tests with components

### Python (Backend & Worker)

- Use type hints everywhere
- Follow PEP 8 (enforced by Ruff)
- Use async/await for I/O operations
- Prefer composition over inheritance
- Write docstrings for public functions
- Use Pydantic for validation

### Git Commits

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add user authentication
fix: resolve memory leak in worker
docs: update API documentation
refactor: simplify database queries
test: add integration tests for health endpoint
chore: update dependencies
```

### Branch Naming

- `feature/short-description` - New features
- `fix/short-description` - Bug fixes
- `docs/short-description` - Documentation
- `refactor/short-description` - Code refactoring
- `test/short-description` - Test additions
- `chore/short-description` - Maintenance

## Testing Requirements

### Backend

```bash
cd apps/api
pytest -v --cov=openagent --cov-report=term-missing
```

- Unit tests for business logic
- Integration tests for API endpoints
- Minimum 80% coverage for new code

### Frontend

```bash
cd apps/web
pnpm test --coverage
```

- Component tests for UI components
- Integration tests for pages
- Minimum 70% coverage for new code

### Worker

```bash
cd apps/worker
pytest -v
```

- Unit tests for job processing
- Integration tests for queue operations

## Pull Request Checklist

Before submitting a PR, ensure:

- [ ] All tests pass (`pnpm test`)
- [ ] Linting passes (`pnpm lint`)
- [ ] Type checking passes (`pnpm typecheck`)
- [ ] Build succeeds (`pnpm build`)
- [ ] No new TypeScript `any` types
- [ ] No new Python `Any` types without justification
- [ ] Documentation updated if needed
- [ ] CHANGELOG.md updated (for significant changes)
- [ ] Commit messages follow conventional format
- [ ] Branch is up to date with `main`

## Review Process

1. Automated checks must pass (CI)
2. At least one maintainer review required
3. Address all review comments
4. Squash commits if requested
5. Merge after approval

## Release Process

Releases are managed by maintainers:

1. Version bump in `package.json` and `pyproject.toml` files
2. Update `CHANGELOG.md`
3. Create release tag
4. GitHub Actions builds and publishes artifacts
5. Announce release

## Getting Help

- **Documentation**: [docs.openagent.dev](https://docs.openagent.dev) (coming soon)
- **Discord**: [Join our community](https://discord.gg/openagent) (coming soon)
- **GitHub Discussions**: For questions and ideas
- **Email**: dev@openagent.dev

## Recognition

Contributors are recognized in:
- GitHub Contributors graph
- Release notes
- Annual contributor highlights

Thank you for contributing to OpenAgent!