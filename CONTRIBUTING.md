# Contributing to Car Vault (Vehicle Vault)

Thanks for your interest in contributing 🎉

## Before you start

- Read `README.md` for project setup and workflow.
- Keep changes focused (one feature/fix per PR).
- Open an issue first for large changes.

## Development setup

1. Create and activate a virtual environment.
2. Install dependencies from `requirements.txt`.
3. Configure `.env` values.
4. Run migrations.
5. Start the development server.

## Branching strategy

- Create branches from `main`.
- Suggested branch names:
  - `feat/<short-description>`
  - `fix/<short-description>`
  - `docs/<short-description>`

## Commit guidelines

Use clear, descriptive commits:

- `feat(auth): add resend OTP cooldown`
- `fix(listings): block non-owner listing updates`
- `docs(readme): update setup instructions`

## Pull request checklist

Before opening a PR, please ensure:

- [ ] Code runs locally without errors
- [ ] Relevant tests pass (`python manage.py test`)
- [ ] New logic is covered by tests where practical
- [ ] No secrets or credentials are committed
- [ ] Documentation is updated if behavior changed

## Code style

- Follow existing Django/Python style in this repository.
- Keep functions and views readable and single-purpose.
- Prefer explicit names over short/ambiguous names.

## Reporting bugs

Please use the bug issue template and include:

- Steps to reproduce
- Expected behavior
- Actual behavior
- Environment details (OS, Python version, DB)

## Feature requests

Please use the feature request template and include:

- Problem statement
- Proposed solution
- Alternatives considered
- Any UI/API impact

## Security

For vulnerabilities, **do not** open a public issue.
Please follow `SECURITY.md` for responsible disclosure.
