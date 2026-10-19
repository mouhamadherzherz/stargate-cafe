# STARGATE CAFE — Changelog

## [6.3.0 Enterprise Pro] — 2026-10-19

### 🛡️ Security Hardening & Vulnerability Fixes
- **Eliminated Employee Authentication Bypass (P0):**
  - Refactored `/employee/current` to strictly require an active authenticated employee session.
  - Eliminated automatic session assignment of cashier identity for unauthenticated visitors.
  - Enforced automatic session invalidation and HTTP 401 response if an employee account has been deactivated or deleted in the database.
- **Secured Global Safe Transfer & Balance Reset (P0):**
  - Upgraded `/safe/transfer_and_zero_all` and `/api/safe/transfer_and_zero_all` from `@login_required` to strict `@admin_required`.
  - Added server-side balance validation: rejected zero-balance transfers to prevent phantom ledger entries.
  - Implemented `idempotency_key` deduplication: prevented double-billing or redundant transfers caused by repeated client submissions.
- **Harden Setup Wizard Takeover Defense (P0):**
  - Wrapped setup wizard in atomic database transaction checks (`BEGIN IMMEDIATE`).
  - Added strict rejection if the system has already completed setup and an active administrator exists.
  - Enforced minimum length requirements for administrator passwords (min 6 characters) and PINs (min 4 digits).
- **Restricted Administrative Endpoints (P1):**
  - Promoted `/api/audit/logs`, `/api/ai/audit`, and `/api/safe/balance` to `@admin_required`.
  - Cashiers are strictly prevented from querying vault totals and systemic audit archives.
- **Server-Side Shift Report Validation (P1):**
  - Recomputed expected shift cash balances authoritatively on the server inside `/api/telegram/send-shift-report`.
  - Client-supplied totals and difference calculations are no longer trusted.
- **Protected Internal Data Endpoints (P2):**
  - Added `@login_required` to `/api/inventory/alerts` and `/api/items/top-selling`.
- **Eliminated Technical Exception Exposure (P3):**
  - Sanitized raw exception messages (`str(e)`) across setup, safe transfers, and inventory endpoints.
  - Replaced user-visible stack traces with secure logging via `logger.exception()`.
- **CSRF Defense Hardening (P1):**
  - Fixed cross-origin forgery defense to strictly reject requests from mismatched origins with HTTP 403 Forbidden.
  - Added `@app.route('/login', methods=['GET', 'POST'])` alias to support standard authentication forms.

### 💰 Accounting & Financial Integrity
- **Pure Double-Entry Transfer Posting:**
  - Removed raw SQL balance overwrites on account 1010 during safe zeroing.
  - All safe transfers now post balanced double-entry vouchers (Debit Account 1020 Safe, Credit Account 1010 Drawer Cash).
- **Zero-Balance Guard:**
  - Added checks preventing zero-amount transfers when drawer cash is already zero.

### 🚀 Production Packaging & Versioning
- **Dynamic Installer & Updater Versioning:**
  - Replaced hardcoded `v5.3.1` in updater batch files and installer download endpoints with dynamic versioning via `_get_current_version()`.
  - Replaced indiscriminate `taskkill /F /IM python.exe` in updater scripts with targeted process termination targeting STARGATE processes only.
- **Exclusion of Sensitive Files in Archives:**
  - Updated distribution packaging to strictly exclude `.secret_key`, active `.db` files, logs, and backups.

---

## [6.2.0 PRO] — 2026-10-17
- Enforced server-authoritative pricing on POS orders.
- Atomic transaction rollbacks for order creation and double-entry journals.
- Turkish coffee bean batch yield tracking.
- Emerald luxury theme and AI Insights engine.
