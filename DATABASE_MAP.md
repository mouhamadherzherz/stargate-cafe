# STARGATE CAFE — Database Schema & Architecture Map

**Total Registered Tables:** 33

| Table Name | Row Count | Column Count | Primary Columns |
| :--- | :---: | :---: | :--- |
| `accounts` | 19 | 10 | id (INTEGER), code (TEXT), name (TEXT), name_ar (TEXT), account_type (TEXT), balance_lbp (REAL)... |
| `audit_log` | 12 | 10 | id (INTEGER), actor (TEXT), action (TEXT), table_name (TEXT), record_id (INTEGER), old_value (TEXT)... |
| `cafe_categories` | 4 | 4 | id (INTEGER), name (TEXT), icon (TEXT), sort_order (INTEGER) |
| `cafe_items` | 8 | 23 | id (INTEGER), category_id (INTEGER), name (TEXT), price_lbp (REAL), price_usd (REAL), icon (TEXT)... |
| `cafe_order_items` | 1942 | 15 | id (INTEGER), order_id (INTEGER), item_id (INTEGER), item_name (TEXT), item_type (TEXT), quantity (INTEGER)... |
| `cafe_orders` | 1934 | 34 | id (INTEGER), order_number (TEXT), subtotal_lbp (REAL), subtotal_usd (REAL), discount_lbp (REAL), discount_usd (REAL)... |
| `coffee_bag_batches` | 13 | 26 | id (INTEGER), batch_code (TEXT), bag_weight_grams (REAL), cost_per_kg_lbp (REAL), cost_per_kg_usd (REAL), opened_at (TIMESTAMP)... |
| `coffee_waste_logs` | 18 | 12 | id (INTEGER), batch_id (INTEGER), item_name (TEXT), qty (INTEGER), unit_cost_lbp (REAL), unit_cost_usd (REAL)... |
| `customer_debts` | 83 | 18 | id (INTEGER), customer_name (TEXT), phone (TEXT), order_id (INTEGER), order_number (TEXT), amount_lbp (REAL)... |
| `debt_payments` | 3 | 10 | id (INTEGER), debt_id (INTEGER), customer_name (TEXT), amount_lbp (REAL), amount_usd (REAL), payment_method (TEXT)... |
| `dining_tables` | 10 | 8 | id (INTEGER), table_number (TEXT), table_name (TEXT), section (TEXT), status (TEXT), current_order_id (INTEGER)... |
| `employees` | 1 | 11 | id (INTEGER), name (TEXT), username (TEXT), password (TEXT), pin (TEXT), role (TEXT)... |
| `expenses` | 45 | 15 | id (INTEGER), title (TEXT), amount_lbp (REAL), amount_usd (REAL), category (TEXT), notes (TEXT)... |
| `financial_ledger` | 1984 | 24 | id (INTEGER), entry_type (TEXT), source (TEXT), destination (TEXT), reference_table (TEXT), reference_id (INTEGER)... |
| `fiscal_year_closings` | 0 | 13 | id (INTEGER), fiscal_year (INTEGER), closing_date (TEXT), total_revenues_lbp (REAL), total_expenses_lbp (REAL), net_profit_lbp (REAL)... |
| `inventory` | 1 | 15 | id (INTEGER), name (TEXT), category (TEXT), unit (TEXT), stock_qty (REAL), cost_per_unit (REAL)... |
| `journal_entries` | 2067 | 11 | id (INTEGER), entry_number (TEXT), entry_date (TEXT), description (TEXT), reference_type (TEXT), reference_id (INTEGER)... |
| `journal_entry_lines` | 4218 | 10 | id (INTEGER), journal_entry_id (INTEGER), account_code (TEXT), account_name (TEXT), debit_lbp (REAL), credit_lbp (REAL)... |
| `owner_drawings` | 0 | 11 | id (INTEGER), amount_lbp (REAL), amount_usd (REAL), source (TEXT), drawing_type (TEXT), month_period (TEXT)... |
| `pc_usage_logs` | 0 | 7 | id (INTEGER), price_lbp (REAL), price_usd (REAL), note (TEXT), employee_id (INTEGER), employee_name (TEXT)... |
| `product_price_history` | 0 | 10 | id (INTEGER), item_id (INTEGER), item_name (TEXT), old_price_lbp (REAL), new_price_lbp (REAL), old_price_usd (REAL)... |
| `purchase_invoice_items` | 0 | 10 | id (INTEGER), invoice_id (INTEGER), inventory_id (INTEGER), item_name (TEXT), qty (REAL), unit (TEXT)... |
| `purchase_invoices` | 0 | 16 | id (INTEGER), invoice_number (TEXT), supplier_id (INTEGER), supplier_name (TEXT), total_usd (REAL), total_lbp (REAL)... |
| `recipes` | 0 | 5 | id (INTEGER), cafe_item_id (INTEGER), inventory_id (INTEGER), required_qty (REAL), unit (TEXT) |
| `safe_transfers` | 51 | 16 | id (INTEGER), amount_lbp (REAL), amount_usd (REAL), note (TEXT), transferred_by (TEXT), operation_type (TEXT)... |
| `settings` | 1 | 24 | id (INTEGER), company_name (TEXT), phone (TEXT), address (TEXT), receipt_footer_text (TEXT), currency (TEXT)... |
| `shift_closings` | 94 | 28 | id (INTEGER), business_date (TEXT), shift_number (INTEGER), employee_id (INTEGER), employee_name (TEXT), opened_at (TIMESTAMP)... |
| `shift_logs` | 94 | 9 | id (INTEGER), employee_id (INTEGER), employee_name (TEXT), date (TEXT), total_sales_lbp (REAL), cash_sales_lbp (REAL)... |
| `stock_movements` | 17 | 17 | id (INTEGER), movement_type (TEXT), item_type (TEXT), item_id (INTEGER), item_name (TEXT), quantity (REAL)... |
| `stocktaking_items` | 0 | 14 | id (INTEGER), session_id (INTEGER), item_type (TEXT), item_id (INTEGER), item_name (TEXT), unit (TEXT)... |
| `stocktaking_sessions` | 0 | 13 | id (INTEGER), session_code (TEXT), status (TEXT), notes (TEXT), conducted_by_id (INTEGER), conducted_by_name (TEXT)... |
| `supplier_payments` | 0 | 8 | id (INTEGER), supplier_id (INTEGER), amount_usd (REAL), amount_lbp (REAL), payment_method (TEXT), notes (TEXT)... |
| `suppliers` | 2 | 9 | id (INTEGER), name (TEXT), phone (TEXT), company (TEXT), balance_usd (REAL), balance_lbp (REAL)... |


## Detailed Table Specifications

### `accounts`
- **Row Count:** 19
- **Columns:**
  - `id (INTEGER)`
  - `code (TEXT)`
  - `name (TEXT)`
  - `name_ar (TEXT)`
  - `account_type (TEXT)`
  - `balance_lbp (REAL)`
  - `balance_usd (REAL)`
  - `description (TEXT)`
  - `is_active (INTEGER)`
  - `created_at (TIMESTAMP)`

### `audit_log`
- **Row Count:** 12
- **Columns:**
  - `id (INTEGER)`
  - `actor (TEXT)`
  - `action (TEXT)`
  - `table_name (TEXT)`
  - `record_id (INTEGER)`
  - `old_value (TEXT)`
  - `new_value (TEXT)`
  - `reason (TEXT)`
  - `ip_address (TEXT)`
  - `created_at (TIMESTAMP)`

### `cafe_categories`
- **Row Count:** 4
- **Columns:**
  - `id (INTEGER)`
  - `name (TEXT)`
  - `icon (TEXT)`
  - `sort_order (INTEGER)`

### `cafe_items`
- **Row Count:** 8
- **Columns:**
  - `id (INTEGER)`
  - `category_id (INTEGER)`
  - `name (TEXT)`
  - `price_lbp (REAL)`
  - `price_usd (REAL)`
  - `icon (TEXT)`
  - `item_type (TEXT)`
  - `sort_order (INTEGER)`
  - `is_active (INTEGER)`
  - `stock_qty (REAL)`
  - `track_stock (INTEGER)`
  - `low_stock_limit (REAL)`
  - `image_path (TEXT)`
  - `cost_price_lbp (REAL)`
  - `cost_price_usd (REAL)`
  - `wholesale_price_lbp (REAL)`
  - `wholesale_price_usd (REAL)`
  - `is_coffee_bean_linked (INTEGER)`
  - `sku (TEXT)`
  - `barcode (TEXT)`
  - `unit (TEXT)`
  - `supplier_id (INTEGER)`
  - `min_order_qty (REAL)`

### `cafe_order_items`
- **Row Count:** 1942
- **Columns:**
  - `id (INTEGER)`
  - `order_id (INTEGER)`
  - `item_id (INTEGER)`
  - `item_name (TEXT)`
  - `item_type (TEXT)`
  - `quantity (INTEGER)`
  - `unit_price_lbp (REAL)`
  - `unit_price_usd (REAL)`
  - `subtotal_lbp (REAL)`
  - `subtotal_usd (REAL)`
  - `created_at (TIMESTAMP)`
  - `unit_cost_lbp (REAL)`
  - `unit_cost_usd (REAL)`
  - `is_wholesale (INTEGER)`
  - `coffee_batch_id (INTEGER)`

### `cafe_orders`
- **Row Count:** 1934
- **Columns:**
  - `id (INTEGER)`
  - `order_number (TEXT)`
  - `subtotal_lbp (REAL)`
  - `subtotal_usd (REAL)`
  - `discount_lbp (REAL)`
  - `discount_usd (REAL)`
  - `discount_percent (REAL)`
  - `discount_reason (TEXT)`
  - `total_lbp (REAL)`
  - `total_usd (REAL)`
  - `paid_amount (REAL)`
  - `payment_method (TEXT)`
  - `customer_name (TEXT)`
  - `notes (TEXT)`
  - `status (TEXT)`
  - `is_tab (INTEGER)`
  - `employee_id (INTEGER)`
  - `employee_name (TEXT)`
  - `created_at (TIMESTAMP)`
  - `updated_at (TIMESTAMP)`
  - `ledger_id (INTEGER)`
  - `cancelled_by (TEXT)`
  - `cancelled_at (TIMESTAMP)`
  - `cancel_reason (TEXT)`
  - `dining_table_id (INTEGER)`
  - `dining_table_name (TEXT)`
  - `exchange_rate_used (REAL)`
  - `total_cost_lbp (REAL)`
  - `total_cost_usd (REAL)`
  - `is_wholesale (INTEGER)`
  - `order_type (TEXT)`
  - `table_number (TEXT)`
  - `idempotency_key (TEXT)`
  - `tracking_number (TEXT)`

### `coffee_bag_batches`
- **Row Count:** 13
- **Columns:**
  - `id (INTEGER)`
  - `batch_code (TEXT)`
  - `bag_weight_grams (REAL)`
  - `cost_per_kg_lbp (REAL)`
  - `cost_per_kg_usd (REAL)`
  - `opened_at (TIMESTAMP)`
  - `opened_by (TEXT)`
  - `status (TEXT)`
  - `closed_at (TIMESTAMP)`
  - `closed_by (TEXT)`
  - `cups_sold (INTEGER)`
  - `cups_damaged (INTEGER)`
  - `total_cups (INTEGER)`
  - `cost_per_cup_lbp (REAL)`
  - `cost_per_cup_usd (REAL)`
  - `total_revenue_lbp (REAL)`
  - `total_revenue_usd (REAL)`
  - `net_profit_lbp (REAL)`
  - `net_profit_usd (REAL)`
  - `prev_batch_id (INTEGER)`
  - `prev_batch_code (TEXT)`
  - `prev_batch_cups (INTEGER)`
  - `expected_cups_yield (REAL)`
  - `initial_cup_cost_lbp (REAL)`
  - `initial_cup_cost_usd (REAL)`
  - `notes (TEXT)`

### `coffee_waste_logs`
- **Row Count:** 18
- **Columns:**
  - `id (INTEGER)`
  - `batch_id (INTEGER)`
  - `item_name (TEXT)`
  - `qty (INTEGER)`
  - `unit_cost_lbp (REAL)`
  - `unit_cost_usd (REAL)`
  - `loss_cost_lbp (REAL)`
  - `loss_cost_usd (REAL)`
  - `reason (TEXT)`
  - `employee_name (TEXT)`
  - `notes (TEXT)`
  - `created_at (TIMESTAMP)`

### `customer_debts`
- **Row Count:** 83
- **Columns:**
  - `id (INTEGER)`
  - `customer_name (TEXT)`
  - `phone (TEXT)`
  - `order_id (INTEGER)`
  - `order_number (TEXT)`
  - `amount_lbp (REAL)`
  - `amount_usd (REAL)`
  - `paid_lbp (REAL)`
  - `paid_usd (REAL)`
  - `remaining_lbp (REAL)`
  - `remaining_usd (REAL)`
  - `status (TEXT)`
  - `notes (TEXT)`
  - `created_at (TIMESTAMP)`
  - `updated_at (TIMESTAMP)`
  - `cancelled_by (TEXT)`
  - `cancelled_at (TIMESTAMP)`
  - `cancel_reason (TEXT)`

### `debt_payments`
- **Row Count:** 3
- **Columns:**
  - `id (INTEGER)`
  - `debt_id (INTEGER)`
  - `customer_name (TEXT)`
  - `amount_lbp (REAL)`
  - `amount_usd (REAL)`
  - `payment_method (TEXT)`
  - `notes (TEXT)`
  - `employee_id (INTEGER)`
  - `employee_name (TEXT)`
  - `created_at (TIMESTAMP)`

### `dining_tables`
- **Row Count:** 10
- **Columns:**
  - `id (INTEGER)`
  - `table_number (TEXT)`
  - `table_name (TEXT)`
  - `section (TEXT)`
  - `status (TEXT)`
  - `current_order_id (INTEGER)`
  - `seats (INTEGER)`
  - `created_at (TIMESTAMP)`

### `employees`
- **Row Count:** 1
- **Columns:**
  - `id (INTEGER)`
  - `name (TEXT)`
  - `username (TEXT)`
  - `password (TEXT)`
  - `pin (TEXT)`
  - `role (TEXT)`
  - `phone (TEXT)`
  - `is_active (INTEGER)`
  - `password_is_hashed (INTEGER)`
  - `created_at (TIMESTAMP)`
  - `custom_permissions (TEXT)`

### `expenses`
- **Row Count:** 45
- **Columns:**
  - `id (INTEGER)`
  - `title (TEXT)`
  - `amount_lbp (REAL)`
  - `amount_usd (REAL)`
  - `category (TEXT)`
  - `notes (TEXT)`
  - `source (TEXT)`
  - `employee_id (INTEGER)`
  - `employee_name (TEXT)`
  - `created_at (TIMESTAMP)`
  - `status (TEXT)`
  - `cancelled_by (TEXT)`
  - `cancelled_at (TIMESTAMP)`
  - `cancel_reason (TEXT)`
  - `ledger_id (INTEGER)`

### `financial_ledger`
- **Row Count:** 1984
- **Columns:**
  - `id (INTEGER)`
  - `entry_type (TEXT)`
  - `source (TEXT)`
  - `destination (TEXT)`
  - `reference_table (TEXT)`
  - `reference_id (INTEGER)`
  - `amount_lbp (REAL)`
  - `amount_usd (REAL)`
  - `exchange_rate (REAL)`
  - `drawer_balance_before (REAL)`
  - `drawer_balance_after (REAL)`
  - `safe_balance_lbp_before (REAL)`
  - `safe_balance_lbp_after (REAL)`
  - `safe_balance_usd_before (REAL)`
  - `safe_balance_usd_after (REAL)`
  - `user_id (INTEGER)`
  - `user_name (TEXT)`
  - `status (TEXT)`
  - `cancelled_by (TEXT)`
  - `cancelled_at (TIMESTAMP)`
  - `cancel_reason (TEXT)`
  - `notes (TEXT)`
  - `business_date (TEXT)`
  - `created_at (TIMESTAMP)`

### `fiscal_year_closings`
- **Row Count:** 0
- **Columns:**
  - `id (INTEGER)`
  - `fiscal_year (INTEGER)`
  - `closing_date (TEXT)`
  - `total_revenues_lbp (REAL)`
  - `total_expenses_lbp (REAL)`
  - `net_profit_lbp (REAL)`
  - `total_revenues_usd (REAL)`
  - `total_expenses_usd (REAL)`
  - `net_profit_usd (REAL)`
  - `journal_entry_id (INTEGER)`
  - `closed_by (TEXT)`
  - `notes (TEXT)`
  - `created_at (TIMESTAMP)`

### `inventory`
- **Row Count:** 1
- **Columns:**
  - `id (INTEGER)`
  - `name (TEXT)`
  - `category (TEXT)`
  - `unit (TEXT)`
  - `stock_qty (REAL)`
  - `cost_per_unit (REAL)`
  - `low_stock_limit (REAL)`
  - `notes (TEXT)`
  - `created_at (TIMESTAMP)`
  - `updated_at (TIMESTAMP)`
  - `item_name (TEXT)`
  - `current_stock (REAL)`
  - `safety_stock (REAL)`
  - `cost_price (REAL)`
  - `selling_price (REAL)`

### `journal_entries`
- **Row Count:** 2067
- **Columns:**
  - `id (INTEGER)`
  - `entry_number (TEXT)`
  - `entry_date (TEXT)`
  - `description (TEXT)`
  - `reference_type (TEXT)`
  - `reference_id (INTEGER)`
  - `total_amount_lbp (REAL)`
  - `total_amount_usd (REAL)`
  - `user_name (TEXT)`
  - `status (TEXT)`
  - `created_at (TIMESTAMP)`

### `journal_entry_lines`
- **Row Count:** 4218
- **Columns:**
  - `id (INTEGER)`
  - `journal_entry_id (INTEGER)`
  - `account_code (TEXT)`
  - `account_name (TEXT)`
  - `debit_lbp (REAL)`
  - `credit_lbp (REAL)`
  - `debit_usd (REAL)`
  - `credit_usd (REAL)`
  - `memo (TEXT)`
  - `created_at (TIMESTAMP)`

### `owner_drawings`
- **Row Count:** 0
- **Columns:**
  - `id (INTEGER)`
  - `amount_lbp (REAL)`
  - `amount_usd (REAL)`
  - `source (TEXT)`
  - `drawing_type (TEXT)`
  - `month_period (TEXT)`
  - `drawn_by (TEXT)`
  - `notes (TEXT)`
  - `exchange_rate (REAL)`
  - `status (TEXT)`
  - `created_at (TIMESTAMP)`

### `pc_usage_logs`
- **Row Count:** 0
- **Columns:**
  - `id (INTEGER)`
  - `price_lbp (REAL)`
  - `price_usd (REAL)`
  - `note (TEXT)`
  - `employee_id (INTEGER)`
  - `employee_name (TEXT)`
  - `created_at (TIMESTAMP)`

### `product_price_history`
- **Row Count:** 0
- **Columns:**
  - `id (INTEGER)`
  - `item_id (INTEGER)`
  - `item_name (TEXT)`
  - `old_price_lbp (REAL)`
  - `new_price_lbp (REAL)`
  - `old_price_usd (REAL)`
  - `new_price_usd (REAL)`
  - `changed_by (TEXT)`
  - `reason (TEXT)`
  - `created_at (TIMESTAMP)`

### `purchase_invoice_items`
- **Row Count:** 0
- **Columns:**
  - `id (INTEGER)`
  - `invoice_id (INTEGER)`
  - `inventory_id (INTEGER)`
  - `item_name (TEXT)`
  - `qty (REAL)`
  - `unit (TEXT)`
  - `cost_unit_usd (REAL)`
  - `cost_unit_lbp (REAL)`
  - `total_usd (REAL)`
  - `total_lbp (REAL)`

### `purchase_invoices`
- **Row Count:** 0
- **Columns:**
  - `id (INTEGER)`
  - `invoice_number (TEXT)`
  - `supplier_id (INTEGER)`
  - `supplier_name (TEXT)`
  - `total_usd (REAL)`
  - `total_lbp (REAL)`
  - `paid_usd (REAL)`
  - `paid_lbp (REAL)`
  - `payment_source (TEXT)`
  - `status (TEXT)`
  - `cancelled_by (TEXT)`
  - `cancelled_at (TIMESTAMP)`
  - `cancel_reason (TEXT)`
  - `notes (TEXT)`
  - `created_by (TEXT)`
  - `created_at (TIMESTAMP)`

### `recipes`
- **Row Count:** 0
- **Columns:**
  - `id (INTEGER)`
  - `cafe_item_id (INTEGER)`
  - `inventory_id (INTEGER)`
  - `required_qty (REAL)`
  - `unit (TEXT)`

### `safe_transfers`
- **Row Count:** 51
- **Columns:**
  - `id (INTEGER)`
  - `amount_lbp (REAL)`
  - `amount_usd (REAL)`
  - `note (TEXT)`
  - `transferred_by (TEXT)`
  - `operation_type (TEXT)`
  - `source (TEXT)`
  - `target (TEXT)`
  - `employee_id (INTEGER)`
  - `employee_name (TEXT)`
  - `created_at (TIMESTAMP)`
  - `status (TEXT)`
  - `cancelled_by (TEXT)`
  - `cancelled_at (TIMESTAMP)`
  - `cancel_reason (TEXT)`
  - `ledger_id (INTEGER)`

### `settings`
- **Row Count:** 1
- **Columns:**
  - `id (INTEGER)`
  - `company_name (TEXT)`
  - `phone (TEXT)`
  - `address (TEXT)`
  - `receipt_footer_text (TEXT)`
  - `currency (TEXT)`
  - `secondary_currency (TEXT)`
  - `exchange_rate (REAL)`
  - `pc_price_per_click_lbp (REAL)`
  - `admin_password (TEXT)`
  - `default_delivery_fee (REAL)`
  - `default_driver_commission (REAL)`
  - `default_return_fee (REAL)`
  - `whatsapp_gateway_enabled (INTEGER)`
  - `whatsapp_provider (TEXT)`
  - `whatsapp_instance_id (TEXT)`
  - `whatsapp_token (TEXT)`
  - `whatsapp_api_url (TEXT)`
  - `is_seeded (INTEGER)`
  - `setup_complete (INTEGER)`
  - `updated_at (TIMESTAMP)`
  - `telegram_enabled (INTEGER)`
  - `telegram_bot_token (TEXT)`
  - `telegram_chat_id (TEXT)`

### `shift_closings`
- **Row Count:** 94
- **Columns:**
  - `id (INTEGER)`
  - `business_date (TEXT)`
  - `shift_number (INTEGER)`
  - `employee_id (INTEGER)`
  - `employee_name (TEXT)`
  - `opened_at (TIMESTAMP)`
  - `closed_at (TIMESTAMP)`
  - `opening_float_lbp (REAL)`
  - `opening_float_usd (REAL)`
  - `cash_sales_lbp (REAL)`
  - `cash_sales_usd (REAL)`
  - `debt_sales_lbp (REAL)`
  - `debt_collected_lbp (REAL)`
  - `expenses_lbp (REAL)`
  - `safe_transfers_lbp (REAL)`
  - `expected_cash_lbp (REAL)`
  - `actual_cash_lbp (REAL)`
  - `difference_lbp (REAL)`
  - `difference_note (TEXT)`
  - `orders_count (INTEGER)`
  - `status (TEXT)`
  - `handover_to_employee_id (INTEGER)`
  - `handover_to_employee_name (TEXT)`
  - `created_at (TIMESTAMP)`
  - `approved_by (TEXT)`
  - `approved_at (TIMESTAMP)`
  - `approval_status (TEXT)`
  - `approval_notes (TEXT)`

### `shift_logs`
- **Row Count:** 94
- **Columns:**
  - `id (INTEGER)`
  - `employee_id (INTEGER)`
  - `employee_name (TEXT)`
  - `date (TEXT)`
  - `total_sales_lbp (REAL)`
  - `cash_sales_lbp (REAL)`
  - `production_note (TEXT)`
  - `closed_at (TEXT)`
  - `created_at (TEXT)`

### `stock_movements`
- **Row Count:** 17
- **Columns:**
  - `id (INTEGER)`
  - `movement_type (TEXT)`
  - `item_type (TEXT)`
  - `item_id (INTEGER)`
  - `item_name (TEXT)`
  - `quantity (REAL)`
  - `qty_before (REAL)`
  - `qty_after (REAL)`
  - `unit_cost_lbp (REAL)`
  - `unit_cost_usd (REAL)`
  - `total_cost_lbp (REAL)`
  - `total_cost_usd (REAL)`
  - `reference_type (TEXT)`
  - `reference_id (INTEGER)`
  - `user_name (TEXT)`
  - `notes (TEXT)`
  - `created_at (TIMESTAMP)`

### `stocktaking_items`
- **Row Count:** 0
- **Columns:**
  - `id (INTEGER)`
  - `session_id (INTEGER)`
  - `item_type (TEXT)`
  - `item_id (INTEGER)`
  - `item_name (TEXT)`
  - `unit (TEXT)`
  - `theoretical_qty (REAL)`
  - `actual_counted_qty (REAL)`
  - `difference_qty (REAL)`
  - `unit_cost_lbp (REAL)`
  - `variance_cost_lbp (REAL)`
  - `difference_reason (TEXT)`
  - `adjusted (INTEGER)`
  - `created_at (TIMESTAMP)`

### `stocktaking_sessions`
- **Row Count:** 0
- **Columns:**
  - `id (INTEGER)`
  - `session_code (TEXT)`
  - `status (TEXT)`
  - `notes (TEXT)`
  - `conducted_by_id (INTEGER)`
  - `conducted_by_name (TEXT)`
  - `approved_by_id (INTEGER)`
  - `approved_by_name (TEXT)`
  - `total_items_counted (INTEGER)`
  - `total_discrepancy_items (INTEGER)`
  - `total_variance_cost_lbp (REAL)`
  - `started_at (TIMESTAMP)`
  - `completed_at (TIMESTAMP)`

### `supplier_payments`
- **Row Count:** 0
- **Columns:**
  - `id (INTEGER)`
  - `supplier_id (INTEGER)`
  - `amount_usd (REAL)`
  - `amount_lbp (REAL)`
  - `payment_method (TEXT)`
  - `notes (TEXT)`
  - `created_by (TEXT)`
  - `created_at (TIMESTAMP)`

### `suppliers`
- **Row Count:** 2
- **Columns:**
  - `id (INTEGER)`
  - `name (TEXT)`
  - `phone (TEXT)`
  - `company (TEXT)`
  - `balance_usd (REAL)`
  - `balance_lbp (REAL)`
  - `notes (TEXT)`
  - `is_active (INTEGER)`
  - `created_at (TIMESTAMP)`

