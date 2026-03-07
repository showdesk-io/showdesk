# Contributing to Showdesk

Thank you for your interest in contributing to Showdesk! This document provides guidelines and conventions for contributing to the project.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Branch Conventions](#branch-conventions)
- [Commit Conventions](#commit-conventions)
- [Pull Request Process](#pull-request-process)
- [Development Setup](#development-setup)
- [Code Style](#code-style)
- [Testing](#testing)
- [Reporting Issues](#reporting-issues)

## Code of Conduct

By participating in this project, you agree to maintain a respectful, inclusive, and harassment-free environment for everyone. Be kind, constructive, and professional in all interactions.

## Getting Started

1. **Fork** the repository at [https://github.com/showdesk-io/showdesk](https://github.com/showdesk-io/showdesk)
2. **Clone** your fork locally
3. **Set up** the development environment (see [Development Setup](#development-setup))
4. **Create a branch** following our [branch conventions](#branch-conventions)
5. **Make your changes** with appropriate tests
6. **Submit a pull request** against the `develop` branch

## Branch Conventions

| Branch | Purpose |
|---|---|
| `main` | Stable, production-ready code. Only merged from `develop` after thorough testing. |
| `develop` | Integration branch. All feature and fix branches merge here first. |
| `feat/xxx` | New features (e.g., `feat/video-annotations`, `feat/bulk-actions`) |
| `fix/xxx` | Bug fixes (e.g., `fix/upload-timeout`, `fix/sla-calculation`) |
| `docs/xxx` | Documentation changes |
| `chore/xxx` | Maintenance tasks (dependency updates, CI changes, etc.) |
| `refactor/xxx` | Code refactoring without behavior changes |

### Rules

- Never push directly to `main` or `develop`
- Always create a pull request
- Branch from `develop`, not from `main`
- Keep branches focused and small — one feature or fix per branch

## Commit Conventions

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

### Types

| Type | Description |
|---|---|
| `feat` | A new feature |
| `fix` | A bug fix |
| `docs` | Documentation changes |
| `style` | Code style changes (formatting, no logic change) |
| `refactor` | Code refactoring (no feature or fix) |
| `test` | Adding or updating tests |
| `chore` | Maintenance tasks (deps, CI, build) |
| `perf` | Performance improvements |

### Scopes

Use the relevant module as scope: `backend`, `frontend`, `widget`, `docker`, `ci`

### Examples

```
feat(widget): add camera toggle to recording controls
fix(backend): handle expired video cleanup race condition
docs(readme): add widget integration examples
chore(docker): upgrade PostgreSQL to 17.1
test(backend): add ticket creation API tests
```

## Pull Request Process

1. **Title**: Use the same format as commit messages (`feat(scope): description`)
2. **Description**: Explain what changed, why, and how to test it
3. **Link issues**: Reference any related issues with `Closes #123` or `Fixes #456`
4. **Tests**: All new code must have tests. All tests must pass.
5. **Review**: At least one maintainer review is required
6. **CI**: All CI checks must pass before merging

### PR Checklist

- [ ] Code follows the project's style guidelines
- [ ] Self-reviewed the code
- [ ] Added tests for new functionality
- [ ] All tests pass locally
- [ ] Updated documentation if needed
- [ ] No console.log or debug statements left in code
- [ ] No new warnings introduced

## Development Setup

```bash
# Clone and setup
git clone https://github.com/showdesk-io/showdesk.git
cd showdesk
cp .env.example .env

# Start all services
make dev

# Run migrations
make migrate

# Create a superuser
make createsuperuser
```

See the [README](./README.md) for detailed setup instructions.

## Code Style

### Python (Backend)

- **Formatter/Linter**: [Ruff](https://github.com/astral-sh/ruff)
- **Type hints**: Required on all function signatures
- **Docstrings**: Required on all models and public functions
- **Naming**: snake_case for variables/functions, PascalCase for classes
- Run: `make lint` and `make format`

### TypeScript (Frontend & Widget)

- **Strict mode**: Always enabled, no `any` types
- **Naming**: camelCase for variables/functions, PascalCase for components/types
- **Imports**: Use path aliases (`@/` for frontend)
- Run: `make fe-lint`

### General

- All code, comments, variable names, and strings must be in **English**
- No French, no other languages in the codebase
- Keep functions small and focused
- Prefer composition over inheritance
- Write self-documenting code; add comments only for "why", not "what"

## Testing

### Backend

```bash
make test          # Run all tests
make test-cov      # Run with coverage report
```

- Use `pytest` with `pytest-django`
- Use `factory_boy` for test data
- Test both happy paths and error cases
- Mock external services (S3, FFmpeg) in tests

### Frontend

```bash
cd frontend && npm test
```

### Widget

The widget should be tested in a browser environment since it relies on DOM and MediaRecorder APIs.

## Reporting Issues

When reporting a bug, please include:

1. **Description**: Clear description of the issue
2. **Steps to reproduce**: Detailed steps to reproduce the behavior
3. **Expected behavior**: What you expected to happen
4. **Actual behavior**: What actually happened
5. **Environment**: OS, browser, Docker version, etc.
6. **Screenshots/Videos**: If applicable (use Showdesk! :smile:)

### Feature Requests

We welcome feature requests! Open an issue with:

1. **Problem**: What problem does this solve?
2. **Proposed solution**: How would you like it to work?
3. **Alternatives considered**: What other approaches did you think about?
4. **Additional context**: Mockups, examples, references

---

Thank you for contributing to Showdesk! Every contribution helps make support more human.
