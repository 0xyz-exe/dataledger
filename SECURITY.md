# Security Policy

## Supported Versions

DataLedger is currently in MVP phase. Security fixes are applied to the latest version.

## Reporting a Vulnerability

Report security vulnerabilities by opening a GitHub issue tagged `security` (for non-sensitive issues) or by emailing the maintainers directly (see GitHub profile).

**Please do not report security vulnerabilities in public issues.**

## Current Security Controls

- **Authentication**: JWT tokens with configurable expiry; bcrypt password hashing
- **Authorization**: Role-based access control (Owner/Admin/Analyst/Viewer) enforced server-side
- **Workspace isolation**: Every resource is workspace-scoped; IDOR prevention via server-side checks
- **File upload**: Max size 50 MB, allowed extensions whitelist, safe internal filenames, path traversal protection
- **Input validation**: All inputs validated via Pydantic schemas
- **SQL injection**: SQLAlchemy ORM with parameterized queries
- **CSV formula injection**: Export values are sanitized
- **Error responses**: Stack traces are never exposed to clients in production
- **Audit logging**: Key events recorded per workspace; sensitive fields sanitized

## Known Limitations / Security Debt

- Token storage: Access token stored in localStorage (XSS-accessible). Production deployments should consider HttpOnly cookies + CSRF protection.
- No rate limiting on login endpoint (planned for Phase 2).
- No email verification (planned; currently any email can be registered).
- No refresh token rotation.
- Export download uses URL-based auth (token in query for file download links) — consider signed download URLs for production.
- Tailwind CSS loaded from CDN in frontend dev build — use bundled Tailwind for production.

## Production Hardening Checklist

- [ ] Set `APP_SECRET_KEY` to a strong random value (32+ chars)
- [ ] Set `DATABASE_URL` to PostgreSQL
- [ ] Set `APP_ENV=production` (disables debug error responses)
- [ ] Configure `CORS_ORIGINS` to your specific domain
- [ ] Deploy behind HTTPS
- [ ] Review `UPLOAD_DIR` permissions
- [ ] Enable and test backup for the database
