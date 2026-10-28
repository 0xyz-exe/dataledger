# Contributing to DataLedger

Thank you for your interest in contributing!

## Development Setup

1. Fork the repository
2. Clone your fork: `git clone https://github.com/your-username/dataledger.git`
3. Set up backend: see README.md Quick Start
4. Set up frontend: see README.md Quick Start

## Running Tests

```bash
cd apps/api
python -m pytest tests/ -v --cov=app --cov-report=term-missing
```

## Code Style

Backend:
```bash
cd apps/api
../../.venv/Scripts/ruff check app/ tests/
```

Frontend:
```bash
cd apps/web
npm run lint
npm run typecheck
```

## Pull Request Process

1. Open an issue first for significant changes
2. Create a feature branch: `git checkout -b feat/your-feature`
3. Write tests for new functionality
4. Ensure all existing tests pass
5. Update documentation if needed
6. Submit a PR with a clear description

## Code of Conduct

Be respectful, constructive, and inclusive. We follow the [Contributor Covenant](https://www.contributor-covenant.org/).

## Architecture Decisions

- Reconciliation engine (`app/reconciliation/engine.py`) must remain deterministic and independently testable without a database
- All monetary values use `Decimal`, never `float`
- Authorization is always enforced server-side — never trust frontend-only checks
- Audit events must never block business operations (catch exceptions silently)
