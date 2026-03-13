# Security Policy

## Supported versions

This project is currently maintained on the `main` branch.
Security fixes are applied to the latest code first.

## Reporting a vulnerability

Please report security issues privately and responsibly.

- Email: ramoliadk@gmail.com (replace with your real security contact)
- Subject: `[SECURITY] Car Vault vulnerability report`

Include:

1. Vulnerability description
2. Impact and affected areas
3. Reproduction steps / proof of concept
4. Suggested remediation (if available)

## Response timeline (target)

- Acknowledgement: within 72 hours
- Initial triage: within 7 days
- Fix plan / mitigation: based on severity

## Disclosure policy

- Please avoid public disclosure until a fix or mitigation is available.
- After resolution, we may publish a security note/changelog entry.

## Security best practices for contributors

- Never commit secrets (`SECRET_KEY`, DB password, SMTP credentials, API keys)
- Use `.env` for local config
- Validate/escape user input where needed
- Keep dependencies updated
