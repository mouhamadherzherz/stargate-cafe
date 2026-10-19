# STARGATE CAFE — Changelog

## [6.3.1 NextGen Pro] — 2026-10-19

### 🛡️ Role-Based Access Control (RBAC 7 Roles)
- **Granular Server-Side Authorization:**
  - Implemented 7 distinct operational roles: `owner`, `admin`, `shift_manager`, `accountant`, `cashier`, `inventory_keeper`, `auditor`.
  - Added 30 granular permission flags covering POS, orders, discounts, safe, shifts, stocktaking, purchases, expenses, and audit logs.
  - Added server-side `@permission_required(perm)` and `@role_required(*roles)` decorators, preventing unauthorized client-side bypasses.

### 📦 Physical Stocktaking & Inventory Overhaul
- **Periodic Physical Stocktaking (الجرد الدوري الفعلي):**
  - Added `stocktaking_sessions` and `stocktaking_items` database tables.
  - Implemented snapshot capture of theoretical book stock for cafe items and raw inventory.
  - Supported actual physical count entry, automatic variance calculation, and mandatory variance reasoning.
  - Automated inventory adjustment upon manager approval with immutable `stock_movements` record (`STOCKTAKE_ADJUSTMENT`).
- **Product Price History Tracking:**
  - Added `product_price_history` table and `log_price_change()` function to record price modifications with timestamp, old/new prices, changed_by, and reason.
- **Barcode & SKU Instant Lookup:**
  - Added `barcode`, `sku`, `unit`, and `supplier_id` columns to `cafe_items` with SQLite B-Tree indexes for fast POS scanning.
  - Implemented `/api/items/barcode-lookup` endpoint.

### 🧠 AI Analytics & Business Assistant Engine
- **Intelligent Analytical Assistant:**
  - Implemented `/api/ai/assistant/query` answering operational queries (top selling items, reorder alerts, customer debt aging, shift discrepancies, and anomaly detection) based strictly on live database queries.
  - Non-destructive guarantee: AI operates exclusively in analytical and assistive mode, with zero authorization to execute transfers or alter ledger records.

### 📊 20 Core Comprehensive Reports Hub
- **Unified Reporting Architecture:**
  - Aggregated 20 core reports covering sales, payment methods, cancellations, operating expenses, customer debts, stocktaking discrepancies, and P&L statements with gross/net profit margins.

---

## [6.3.0 Enterprise Pro] — 2026-10-19
- Eliminated Employee Authentication Bypass in `/employee/current`.
- Secured Global Safe Transfer & Balance Reset under strict `@admin_required`.
- Hardened Setup Wizard against unauthorized re-initialization.
- Restricted administrative endpoints (`/api/audit/logs`, `/api/ai/audit`, `/api/safe/balance`).
- Server-authoritative shift report verification.
- Pure double-entry transfer posting (Debit 1020, Credit 1010).

---

## [6.2.0 PRO] — 2026-10-17
- Enforced server-authoritative pricing on POS orders.
- Atomic transaction rollbacks for order creation and double-entry journals.
- Turkish coffee bean batch yield tracking.
- Emerald luxury theme and AI Insights engine.
