# STARGATE CAFE — Comprehensive Database Architecture Map
**Database Engine:** SQLite 3
**Total Business Tables:** 29

## 1. Entity Relational Summary & Row Counts

| Table Name | Active Row Count | Primary Key | Foreign Key References | Indexes |
| :--- | :--- | :--- | :--- | :--- |
| `accounts` | 18 | `id` | None | idx_accounts_type <br>idx_accounts_code <br>sqlite_autoindex_accounts_1 (UNIQUE) |
| `audit_log` | 1 | `id` | None | idx_audit_created <br>idx_audit_action <br>idx_audit_actor  |
| `cafe_categories` | 4 | `id` | None | sqlite_autoindex_cafe_categories_1 (UNIQUE) |
| `cafe_items` | 6 | `id` | category_id -> cafe_categories(id) | idx_items_coffee_link <br>idx_items_track_stock <br>idx_items_is_active <br>idx_items_category_id  |
| `cafe_order_items` | 1935 | `id` | order_id -> cafe_orders(id) | idx_order_items_order_item <br>idx_order_items_item_id <br>idx_order_items_order_id  |
| `cafe_orders` | 1927 | `id` | None | idx_orders_table_status <br>idx_orders_status_created <br>idx_orders_employee_id <br>idx_orders_is_tab <br>idx_orders_status <br>idx_orders_created_at <br>sqlite_autoindex_cafe_orders_1 (UNIQUE) |
| `coffee_bag_batches` | 7 | `id` | None | idx_coffee_batches_status <br>sqlite_autoindex_coffee_bag_batches_1 (UNIQUE) |
| `coffee_waste_logs` | 18 | `id` | batch_id -> coffee_bag_batches(id) | Default PK |
| `customer_debts` | 82 | `id` | order_id -> cafe_orders(id) | idx_debts_status_cust <br>idx_debts_status_rem <br>idx_debts_customer <br>idx_debts_status  |
| `debt_payments` | 3 | `id` | debt_id -> customer_debts(id) | Default PK |
| `dining_tables` | 10 | `id` | None | idx_dining_tables_status <br>sqlite_autoindex_dining_tables_1 (UNIQUE) |
| `employees` | 1 | `id` | None | sqlite_autoindex_employees_1 (UNIQUE) |
| `expenses` | 45 | `id` | None | idx_expenses_source_date <br>idx_expenses_created_at  |
| `financial_ledger` | 1977 | `id` | None | idx_ledger_ref <br>idx_ledger_source_dest <br>idx_ledger_status_date <br>idx_ledger_created <br>idx_ledger_status <br>idx_ledger_entry_type <br>idx_ledger_business_date  |
| `fiscal_year_closings` | 0 | `id` | None | sqlite_autoindex_fiscal_year_closings_1 (UNIQUE) |
| `inventory` | 1 | `id` | None | Default PK |
| `journal_entries` | 2056 | `id` | None | idx_journal_entries_date <br>sqlite_autoindex_journal_entries_1 (UNIQUE) |
| `journal_entry_lines` | 4196 | `id` | journal_entry_id -> journal_entries(id) | idx_journal_entry_lines_acc  |
| `pc_usage_logs` | 0 | `id` | None | idx_pc_usage_created_at  |
| `purchase_invoice_items` | 0 | `id` | invoice_id -> purchase_invoices(id) | Default PK |
| `purchase_invoices` | 0 | `id` | supplier_id -> suppliers(id) | idx_purchase_invoices_status_date <br>sqlite_autoindex_purchase_invoices_1 (UNIQUE) |
| `recipes` | 0 | `id` | inventory_id -> inventory(id)<br>cafe_item_id -> cafe_items(id) | Default PK |
| `safe_transfers` | 49 | `id` | None | idx_safe_transfers_status_date <br>idx_safe_transfers_created_at  |
| `settings` | 1 | `id` | None | Default PK |
| `shift_closings` | 94 | `id` | None | idx_shift_closings_status <br>idx_shift_closings_date  |
| `shift_logs` | 94 | `id` | None | Default PK |
| `stock_movements` | 8 | `id` | None | idx_stock_movements_ref <br>idx_stock_movements_created <br>idx_stock_movements_type <br>idx_stock_movements_item  |
| `supplier_payments` | 0 | `id` | supplier_id -> suppliers(id) | Default PK |
| `suppliers` | 2 | `id` | None | sqlite_autoindex_suppliers_1 (UNIQUE) |

## 2. Detailed Table Schemas

### Table: `accounts` (18 records)
| Column Name | Type | Not Null | Default Value | PK |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | NO | `NULL` | YES |
| `code` | `TEXT` | YES | `NULL` | NO |
| `name` | `TEXT` | YES | `NULL` | NO |
| `name_ar` | `TEXT` | YES | `NULL` | NO |
| `account_type` | `TEXT` | YES | `NULL` | NO |
| `balance_lbp` | `REAL` | NO | `0.0` | NO |
| `balance_usd` | `REAL` | NO | `0.0` | NO |
| `description` | `TEXT` | NO | `''` | NO |
| `is_active` | `INTEGER` | NO | `1` | NO |
| `created_at` | `TIMESTAMP` | NO | `CURRENT_TIMESTAMP` | NO |

### Table: `audit_log` (1 records)
| Column Name | Type | Not Null | Default Value | PK |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | NO | `NULL` | YES |
| `actor` | `TEXT` | YES | `NULL` | NO |
| `action` | `TEXT` | YES | `NULL` | NO |
| `table_name` | `TEXT` | NO | `NULL` | NO |
| `record_id` | `INTEGER` | NO | `NULL` | NO |
| `old_value` | `TEXT` | NO | `NULL` | NO |
| `new_value` | `TEXT` | NO | `NULL` | NO |
| `reason` | `TEXT` | NO | `NULL` | NO |
| `ip_address` | `TEXT` | NO | `'127.0.0.1'` | NO |
| `created_at` | `TIMESTAMP` | NO | `CURRENT_TIMESTAMP` | NO |

### Table: `cafe_categories` (4 records)
| Column Name | Type | Not Null | Default Value | PK |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | NO | `NULL` | YES |
| `name` | `TEXT` | YES | `NULL` | NO |
| `icon` | `TEXT` | NO | `'☕'` | NO |
| `sort_order` | `INTEGER` | NO | `0` | NO |

### Table: `cafe_items` (6 records)
| Column Name | Type | Not Null | Default Value | PK |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | NO | `NULL` | YES |
| `category_id` | `INTEGER` | YES | `NULL` | NO |
| `name` | `TEXT` | YES | `NULL` | NO |
| `price_lbp` | `REAL` | YES | `0.0` | NO |
| `price_usd` | `REAL` | YES | `0.0` | NO |
| `icon` | `TEXT` | NO | `'☕'` | NO |
| `item_type` | `TEXT` | NO | `'cafe'` | NO |
| `sort_order` | `INTEGER` | NO | `0` | NO |
| `is_active` | `INTEGER` | NO | `1` | NO |
| `stock_qty` | `REAL` | NO | `0` | NO |
| `track_stock` | `INTEGER` | NO | `0` | NO |
| `low_stock_limit` | `REAL` | NO | `5` | NO |
| `image_path` | `TEXT` | NO | `NULL` | NO |
| `cost_price_lbp` | `REAL` | NO | `0.0` | NO |
| `cost_price_usd` | `REAL` | NO | `0.0` | NO |
| `wholesale_price_lbp` | `REAL` | NO | `0.0` | NO |
| `wholesale_price_usd` | `REAL` | NO | `0.0` | NO |
| `is_coffee_bean_linked` | `INTEGER` | NO | `0` | NO |

### Table: `cafe_order_items` (1935 records)
| Column Name | Type | Not Null | Default Value | PK |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | NO | `NULL` | YES |
| `order_id` | `INTEGER` | YES | `NULL` | NO |
| `item_id` | `INTEGER` | NO | `NULL` | NO |
| `item_name` | `TEXT` | YES | `NULL` | NO |
| `item_type` | `TEXT` | NO | `'cafe'` | NO |
| `quantity` | `INTEGER` | YES | `1` | NO |
| `unit_price_lbp` | `REAL` | YES | `0.0` | NO |
| `unit_price_usd` | `REAL` | YES | `0.0` | NO |
| `subtotal_lbp` | `REAL` | YES | `0.0` | NO |
| `subtotal_usd` | `REAL` | YES | `0.0` | NO |
| `created_at` | `TIMESTAMP` | NO | `CURRENT_TIMESTAMP` | NO |
| `unit_cost_lbp` | `REAL` | NO | `0.0` | NO |
| `unit_cost_usd` | `REAL` | NO | `0.0` | NO |
| `is_wholesale` | `INTEGER` | NO | `0` | NO |
| `coffee_batch_id` | `INTEGER` | NO | `NULL` | NO |

### Table: `cafe_orders` (1927 records)
| Column Name | Type | Not Null | Default Value | PK |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | NO | `NULL` | YES |
| `order_number` | `TEXT` | YES | `NULL` | NO |
| `subtotal_lbp` | `REAL` | NO | `0.0` | NO |
| `subtotal_usd` | `REAL` | NO | `0.0` | NO |
| `discount_lbp` | `REAL` | NO | `0.0` | NO |
| `discount_usd` | `REAL` | NO | `0.0` | NO |
| `discount_percent` | `REAL` | NO | `0.0` | NO |
| `discount_reason` | `TEXT` | NO | `''` | NO |
| `total_lbp` | `REAL` | YES | `0.0` | NO |
| `total_usd` | `REAL` | YES | `0.0` | NO |
| `paid_amount` | `REAL` | YES | `0.0` | NO |
| `payment_method` | `TEXT` | NO | `'cash'` | NO |
| `customer_name` | `TEXT` | NO | `'زبون كاش'` | NO |
| `notes` | `TEXT` | NO | `NULL` | NO |
| `status` | `TEXT` | NO | `'paid'` | NO |
| `is_tab` | `INTEGER` | NO | `0` | NO |
| `employee_id` | `INTEGER` | NO | `NULL` | NO |
| `employee_name` | `TEXT` | NO | `'كاشير'` | NO |
| `created_at` | `TIMESTAMP` | NO | `CURRENT_TIMESTAMP` | NO |
| `updated_at` | `TIMESTAMP` | NO | `CURRENT_TIMESTAMP` | NO |
| `ledger_id` | `INTEGER` | NO | `NULL` | NO |
| `cancelled_by` | `TEXT` | NO | `NULL` | NO |
| `cancelled_at` | `TIMESTAMP` | NO | `NULL` | NO |
| `cancel_reason` | `TEXT` | NO | `NULL` | NO |
| `dining_table_id` | `INTEGER` | NO | `NULL` | NO |
| `dining_table_name` | `TEXT` | NO | `''` | NO |
| `exchange_rate_used` | `REAL` | NO | `89500.0` | NO |
| `total_cost_lbp` | `REAL` | NO | `0.0` | NO |
| `total_cost_usd` | `REAL` | NO | `0.0` | NO |
| `is_wholesale` | `INTEGER` | NO | `0` | NO |

### Table: `coffee_bag_batches` (7 records)
| Column Name | Type | Not Null | Default Value | PK |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | NO | `NULL` | YES |
| `batch_code` | `TEXT` | YES | `NULL` | NO |
| `bag_weight_grams` | `REAL` | NO | `1000.0` | NO |
| `cost_per_kg_lbp` | `REAL` | YES | `0.0` | NO |
| `cost_per_kg_usd` | `REAL` | YES | `0.0` | NO |
| `opened_at` | `TIMESTAMP` | NO | `CURRENT_TIMESTAMP` | NO |
| `opened_by` | `TEXT` | NO | `'كاشير'` | NO |
| `status` | `TEXT` | NO | `'active'` | NO |
| `closed_at` | `TIMESTAMP` | NO | `NULL` | NO |
| `closed_by` | `TEXT` | NO | `NULL` | NO |
| `cups_sold` | `INTEGER` | NO | `0` | NO |
| `cups_damaged` | `INTEGER` | NO | `0` | NO |
| `total_cups` | `INTEGER` | NO | `0` | NO |
| `cost_per_cup_lbp` | `REAL` | NO | `0.0` | NO |
| `cost_per_cup_usd` | `REAL` | NO | `0.0` | NO |
| `total_revenue_lbp` | `REAL` | NO | `0.0` | NO |
| `total_revenue_usd` | `REAL` | NO | `0.0` | NO |
| `net_profit_lbp` | `REAL` | NO | `0.0` | NO |
| `net_profit_usd` | `REAL` | NO | `0.0` | NO |
| `prev_batch_id` | `INTEGER` | NO | `NULL` | NO |
| `prev_batch_code` | `TEXT` | NO | `NULL` | NO |
| `prev_batch_cups` | `INTEGER` | NO | `0` | NO |
| `expected_cups_yield` | `REAL` | NO | `0.0` | NO |
| `initial_cup_cost_lbp` | `REAL` | NO | `0.0` | NO |
| `initial_cup_cost_usd` | `REAL` | NO | `0.0` | NO |
| `notes` | `TEXT` | NO | `''` | NO |

### Table: `coffee_waste_logs` (18 records)
| Column Name | Type | Not Null | Default Value | PK |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | NO | `NULL` | YES |
| `batch_id` | `INTEGER` | NO | `NULL` | NO |
| `item_name` | `TEXT` | NO | `'فنجان قهوة'` | NO |
| `qty` | `INTEGER` | NO | `1` | NO |
| `unit_cost_lbp` | `REAL` | NO | `0.0` | NO |
| `unit_cost_usd` | `REAL` | NO | `0.0` | NO |
| `loss_cost_lbp` | `REAL` | NO | `0.0` | NO |
| `loss_cost_usd` | `REAL` | NO | `0.0` | NO |
| `reason` | `TEXT` | NO | `'تلف أثناء التحضير'` | NO |
| `employee_name` | `TEXT` | NO | `'كاشير'` | NO |
| `notes` | `TEXT` | NO | `''` | NO |
| `created_at` | `TIMESTAMP` | NO | `CURRENT_TIMESTAMP` | NO |

### Table: `customer_debts` (82 records)
| Column Name | Type | Not Null | Default Value | PK |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | NO | `NULL` | YES |
| `customer_name` | `TEXT` | YES | `NULL` | NO |
| `phone` | `TEXT` | NO | `''` | NO |
| `order_id` | `INTEGER` | NO | `NULL` | NO |
| `order_number` | `TEXT` | NO | `''` | NO |
| `amount_lbp` | `REAL` | YES | `0.0` | NO |
| `amount_usd` | `REAL` | YES | `0.0` | NO |
| `paid_lbp` | `REAL` | YES | `0.0` | NO |
| `paid_usd` | `REAL` | YES | `0.0` | NO |
| `remaining_lbp` | `REAL` | YES | `0.0` | NO |
| `remaining_usd` | `REAL` | YES | `0.0` | NO |
| `status` | `TEXT` | NO | `'unpaid'` | NO |
| `notes` | `TEXT` | NO | `''` | NO |
| `created_at` | `TIMESTAMP` | NO | `CURRENT_TIMESTAMP` | NO |
| `updated_at` | `TIMESTAMP` | NO | `CURRENT_TIMESTAMP` | NO |
| `cancelled_by` | `TEXT` | NO | `NULL` | NO |
| `cancelled_at` | `TIMESTAMP` | NO | `NULL` | NO |
| `cancel_reason` | `TEXT` | NO | `NULL` | NO |

### Table: `debt_payments` (3 records)
| Column Name | Type | Not Null | Default Value | PK |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | NO | `NULL` | YES |
| `debt_id` | `INTEGER` | YES | `NULL` | NO |
| `customer_name` | `TEXT` | YES | `NULL` | NO |
| `amount_lbp` | `REAL` | YES | `0.0` | NO |
| `amount_usd` | `REAL` | YES | `0.0` | NO |
| `payment_method` | `TEXT` | NO | `'cash'` | NO |
| `notes` | `TEXT` | NO | `''` | NO |
| `employee_id` | `INTEGER` | NO | `NULL` | NO |
| `employee_name` | `TEXT` | NO | `'كاشير'` | NO |
| `created_at` | `TIMESTAMP` | NO | `CURRENT_TIMESTAMP` | NO |

### Table: `dining_tables` (10 records)
| Column Name | Type | Not Null | Default Value | PK |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | NO | `NULL` | YES |
| `table_number` | `TEXT` | YES | `NULL` | NO |
| `table_name` | `TEXT` | NO | `''` | NO |
| `section` | `TEXT` | NO | `'الصالة الرئيسية'` | NO |
| `status` | `TEXT` | NO | `'available'` | NO |
| `current_order_id` | `INTEGER` | NO | `NULL` | NO |
| `seats` | `INTEGER` | NO | `4` | NO |
| `created_at` | `TIMESTAMP` | NO | `CURRENT_TIMESTAMP` | NO |

### Table: `employees` (1 records)
| Column Name | Type | Not Null | Default Value | PK |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | NO | `NULL` | YES |
| `name` | `TEXT` | YES | `NULL` | NO |
| `username` | `TEXT` | NO | `NULL` | NO |
| `password` | `TEXT` | YES | `NULL` | NO |
| `pin` | `TEXT` | NO | `NULL` | NO |
| `role` | `TEXT` | NO | `'cashier'` | NO |
| `phone` | `TEXT` | NO | `NULL` | NO |
| `is_active` | `INTEGER` | NO | `1` | NO |
| `password_is_hashed` | `INTEGER` | NO | `0` | NO |
| `created_at` | `TIMESTAMP` | NO | `CURRENT_TIMESTAMP` | NO |

### Table: `expenses` (45 records)
| Column Name | Type | Not Null | Default Value | PK |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | NO | `NULL` | YES |
| `title` | `TEXT` | YES | `NULL` | NO |
| `amount_lbp` | `REAL` | YES | `0.0` | NO |
| `amount_usd` | `REAL` | YES | `0.0` | NO |
| `category` | `TEXT` | NO | `'مصاريف عامة'` | NO |
| `notes` | `TEXT` | NO | `NULL` | NO |
| `source` | `TEXT` | NO | `'drawer'` | NO |
| `employee_id` | `INTEGER` | NO | `NULL` | NO |
| `employee_name` | `TEXT` | NO | `'كاشير'` | NO |
| `created_at` | `TIMESTAMP` | NO | `CURRENT_TIMESTAMP` | NO |
| `status` | `TEXT` | NO | `'active'` | NO |
| `cancelled_by` | `TEXT` | NO | `NULL` | NO |
| `cancelled_at` | `TIMESTAMP` | NO | `NULL` | NO |
| `cancel_reason` | `TEXT` | NO | `NULL` | NO |
| `ledger_id` | `INTEGER` | NO | `NULL` | NO |

### Table: `financial_ledger` (1977 records)
| Column Name | Type | Not Null | Default Value | PK |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | NO | `NULL` | YES |
| `entry_type` | `TEXT` | YES | `NULL` | NO |
| `source` | `TEXT` | YES | `NULL` | NO |
| `destination` | `TEXT` | YES | `NULL` | NO |
| `reference_table` | `TEXT` | NO | `NULL` | NO |
| `reference_id` | `INTEGER` | NO | `NULL` | NO |
| `amount_lbp` | `REAL` | YES | `0.0` | NO |
| `amount_usd` | `REAL` | YES | `0.0` | NO |
| `exchange_rate` | `REAL` | YES | `89500.0` | NO |
| `drawer_balance_before` | `REAL` | NO | `0.0` | NO |
| `drawer_balance_after` | `REAL` | NO | `0.0` | NO |
| `safe_balance_lbp_before` | `REAL` | NO | `0.0` | NO |
| `safe_balance_lbp_after` | `REAL` | NO | `0.0` | NO |
| `safe_balance_usd_before` | `REAL` | NO | `0.0` | NO |
| `safe_balance_usd_after` | `REAL` | NO | `0.0` | NO |
| `user_id` | `INTEGER` | NO | `NULL` | NO |
| `user_name` | `TEXT` | NO | `'النظام'` | NO |
| `status` | `TEXT` | NO | `'active'` | NO |
| `cancelled_by` | `TEXT` | NO | `NULL` | NO |
| `cancelled_at` | `TIMESTAMP` | NO | `NULL` | NO |
| `cancel_reason` | `TEXT` | NO | `NULL` | NO |
| `notes` | `TEXT` | NO | `''` | NO |
| `business_date` | `TEXT` | YES | `NULL` | NO |
| `created_at` | `TIMESTAMP` | NO | `CURRENT_TIMESTAMP` | NO |

### Table: `fiscal_year_closings` (0 records)
| Column Name | Type | Not Null | Default Value | PK |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | NO | `NULL` | YES |
| `fiscal_year` | `INTEGER` | YES | `NULL` | NO |
| `closing_date` | `TEXT` | YES | `NULL` | NO |
| `total_revenues_lbp` | `REAL` | YES | `0.0` | NO |
| `total_expenses_lbp` | `REAL` | YES | `0.0` | NO |
| `net_profit_lbp` | `REAL` | YES | `0.0` | NO |
| `total_revenues_usd` | `REAL` | YES | `0.0` | NO |
| `total_expenses_usd` | `REAL` | YES | `0.0` | NO |
| `net_profit_usd` | `REAL` | YES | `0.0` | NO |
| `journal_entry_id` | `INTEGER` | NO | `NULL` | NO |
| `closed_by` | `TEXT` | YES | `NULL` | NO |
| `notes` | `TEXT` | NO | `NULL` | NO |
| `created_at` | `TIMESTAMP` | NO | `CURRENT_TIMESTAMP` | NO |

### Table: `inventory` (1 records)
| Column Name | Type | Not Null | Default Value | PK |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | NO | `NULL` | YES |
| `name` | `TEXT` | YES | `NULL` | NO |
| `category` | `TEXT` | NO | `'عام'` | NO |
| `unit` | `TEXT` | NO | `'قطعة'` | NO |
| `stock_qty` | `REAL` | NO | `0.0` | NO |
| `cost_per_unit` | `REAL` | NO | `0.0` | NO |
| `low_stock_limit` | `REAL` | NO | `5.0` | NO |
| `notes` | `TEXT` | NO | `''` | NO |
| `created_at` | `TIMESTAMP` | NO | `CURRENT_TIMESTAMP` | NO |
| `updated_at` | `TIMESTAMP` | NO | `CURRENT_TIMESTAMP` | NO |
| `item_name` | `TEXT` | NO | `NULL` | NO |
| `current_stock` | `REAL` | NO | `0.0` | NO |
| `safety_stock` | `REAL` | NO | `5.0` | NO |
| `cost_price` | `REAL` | NO | `0.0` | NO |
| `selling_price` | `REAL` | NO | `0.0` | NO |

### Table: `journal_entries` (2056 records)
| Column Name | Type | Not Null | Default Value | PK |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | NO | `NULL` | YES |
| `entry_number` | `TEXT` | YES | `NULL` | NO |
| `entry_date` | `TEXT` | YES | `NULL` | NO |
| `description` | `TEXT` | YES | `NULL` | NO |
| `reference_type` | `TEXT` | NO | `NULL` | NO |
| `reference_id` | `INTEGER` | NO | `NULL` | NO |
| `total_amount_lbp` | `REAL` | YES | `0.0` | NO |
| `total_amount_usd` | `REAL` | YES | `0.0` | NO |
| `user_name` | `TEXT` | NO | `'النظام'` | NO |
| `status` | `TEXT` | NO | `'posted'` | NO |
| `created_at` | `TIMESTAMP` | NO | `CURRENT_TIMESTAMP` | NO |

### Table: `journal_entry_lines` (4196 records)
| Column Name | Type | Not Null | Default Value | PK |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | NO | `NULL` | YES |
| `journal_entry_id` | `INTEGER` | YES | `NULL` | NO |
| `account_code` | `TEXT` | YES | `NULL` | NO |
| `account_name` | `TEXT` | YES | `NULL` | NO |
| `debit_lbp` | `REAL` | YES | `0.0` | NO |
| `credit_lbp` | `REAL` | YES | `0.0` | NO |
| `debit_usd` | `REAL` | YES | `0.0` | NO |
| `credit_usd` | `REAL` | YES | `0.0` | NO |
| `memo` | `TEXT` | NO | `''` | NO |
| `created_at` | `TIMESTAMP` | NO | `CURRENT_TIMESTAMP` | NO |

### Table: `pc_usage_logs` (0 records)
| Column Name | Type | Not Null | Default Value | PK |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | NO | `NULL` | YES |
| `price_lbp` | `REAL` | YES | `100000.0` | NO |
| `price_usd` | `REAL` | YES | `1.10` | NO |
| `note` | `TEXT` | NO | `'استخدام كمبيوتر GAMING'` | NO |
| `employee_id` | `INTEGER` | NO | `NULL` | NO |
| `employee_name` | `TEXT` | NO | `'كاشير'` | NO |
| `created_at` | `TIMESTAMP` | NO | `CURRENT_TIMESTAMP` | NO |

### Table: `purchase_invoice_items` (0 records)
| Column Name | Type | Not Null | Default Value | PK |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | NO | `NULL` | YES |
| `invoice_id` | `INTEGER` | YES | `NULL` | NO |
| `inventory_id` | `INTEGER` | NO | `NULL` | NO |
| `item_name` | `TEXT` | YES | `NULL` | NO |
| `qty` | `REAL` | YES | `1.0` | NO |
| `unit` | `TEXT` | NO | `'قطعة'` | NO |
| `cost_unit_usd` | `REAL` | NO | `0.0` | NO |
| `cost_unit_lbp` | `REAL` | NO | `0.0` | NO |
| `total_usd` | `REAL` | NO | `0.0` | NO |
| `total_lbp` | `REAL` | NO | `0.0` | NO |

### Table: `purchase_invoices` (0 records)
| Column Name | Type | Not Null | Default Value | PK |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | NO | `NULL` | YES |
| `invoice_number` | `TEXT` | NO | `NULL` | NO |
| `supplier_id` | `INTEGER` | NO | `NULL` | NO |
| `supplier_name` | `TEXT` | NO | `''` | NO |
| `total_usd` | `REAL` | NO | `0.0` | NO |
| `total_lbp` | `REAL` | NO | `0.0` | NO |
| `paid_usd` | `REAL` | NO | `0.0` | NO |
| `paid_lbp` | `REAL` | NO | `0.0` | NO |
| `payment_source` | `TEXT` | NO | `'safe'` | NO |
| `status` | `TEXT` | NO | `'completed'` | NO |
| `cancelled_by` | `TEXT` | NO | `NULL` | NO |
| `cancelled_at` | `TIMESTAMP` | NO | `NULL` | NO |
| `cancel_reason` | `TEXT` | NO | `NULL` | NO |
| `notes` | `TEXT` | NO | `''` | NO |
| `created_by` | `TEXT` | NO | `'المدير'` | NO |
| `created_at` | `TIMESTAMP` | NO | `CURRENT_TIMESTAMP` | NO |

### Table: `recipes` (0 records)
| Column Name | Type | Not Null | Default Value | PK |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | NO | `NULL` | YES |
| `cafe_item_id` | `INTEGER` | YES | `NULL` | NO |
| `inventory_id` | `INTEGER` | YES | `NULL` | NO |
| `required_qty` | `REAL` | YES | `1.0` | NO |
| `unit` | `TEXT` | NO | `'g'` | NO |

### Table: `safe_transfers` (49 records)
| Column Name | Type | Not Null | Default Value | PK |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | NO | `NULL` | YES |
| `amount_lbp` | `REAL` | YES | `0.0` | NO |
| `amount_usd` | `REAL` | YES | `0.0` | NO |
| `note` | `TEXT` | NO | `''` | NO |
| `transferred_by` | `TEXT` | NO | `'المدير'` | NO |
| `operation_type` | `TEXT` | NO | `'deposit'` | NO |
| `source` | `TEXT` | NO | `'drawer'` | NO |
| `target` | `TEXT` | NO | `'safe'` | NO |
| `employee_id` | `INTEGER` | NO | `NULL` | NO |
| `employee_name` | `TEXT` | NO | `'المدير'` | NO |
| `created_at` | `TIMESTAMP` | NO | `CURRENT_TIMESTAMP` | NO |
| `status` | `TEXT` | NO | `'active'` | NO |
| `cancelled_by` | `TEXT` | NO | `NULL` | NO |
| `cancelled_at` | `TIMESTAMP` | NO | `NULL` | NO |
| `cancel_reason` | `TEXT` | NO | `NULL` | NO |
| `ledger_id` | `INTEGER` | NO | `NULL` | NO |

### Table: `settings` (1 records)
| Column Name | Type | Not Null | Default Value | PK |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | NO | `NULL` | YES |
| `company_name` | `TEXT` | NO | `'STARGATE'` | NO |
| `phone` | `TEXT` | NO | `''` | NO |
| `address` | `TEXT` | NO | `''` | NO |
| `receipt_footer_text` | `TEXT` | NO | `''` | NO |
| `currency` | `TEXT` | NO | `'ل.ل'` | NO |
| `secondary_currency` | `TEXT` | NO | `'$'` | NO |
| `exchange_rate` | `REAL` | NO | `89500.0` | NO |
| `pc_price_per_click_lbp` | `REAL` | NO | `100000.0` | NO |
| `admin_password` | `TEXT` | NO | `''` | NO |
| `default_delivery_fee` | `REAL` | NO | `268500.0` | NO |
| `default_driver_commission` | `REAL` | NO | `30000.0` | NO |
| `default_return_fee` | `REAL` | NO | `89500.0` | NO |
| `whatsapp_gateway_enabled` | `INTEGER` | NO | `0` | NO |
| `whatsapp_provider` | `TEXT` | NO | `'ultramsg'` | NO |
| `whatsapp_instance_id` | `TEXT` | NO | `''` | NO |
| `whatsapp_token` | `TEXT` | NO | `''` | NO |
| `whatsapp_api_url` | `TEXT` | NO | `'https://api.ultramsg.com'` | NO |
| `is_seeded` | `INTEGER` | NO | `0` | NO |
| `setup_complete` | `INTEGER` | NO | `0` | NO |
| `updated_at` | `TIMESTAMP` | NO | `CURRENT_TIMESTAMP` | NO |
| `telegram_enabled` | `INTEGER` | NO | `0` | NO |
| `telegram_bot_token` | `TEXT` | NO | `''` | NO |
| `telegram_chat_id` | `TEXT` | NO | `''` | NO |

### Table: `shift_closings` (94 records)
| Column Name | Type | Not Null | Default Value | PK |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | NO | `NULL` | YES |
| `business_date` | `TEXT` | YES | `NULL` | NO |
| `shift_number` | `INTEGER` | NO | `1` | NO |
| `employee_id` | `INTEGER` | NO | `NULL` | NO |
| `employee_name` | `TEXT` | YES | `NULL` | NO |
| `opened_at` | `TIMESTAMP` | NO | `CURRENT_TIMESTAMP` | NO |
| `closed_at` | `TIMESTAMP` | NO | `NULL` | NO |
| `opening_float_lbp` | `REAL` | NO | `0.0` | NO |
| `opening_float_usd` | `REAL` | NO | `0.0` | NO |
| `cash_sales_lbp` | `REAL` | NO | `0.0` | NO |
| `cash_sales_usd` | `REAL` | NO | `0.0` | NO |
| `debt_sales_lbp` | `REAL` | NO | `0.0` | NO |
| `debt_collected_lbp` | `REAL` | NO | `0.0` | NO |
| `expenses_lbp` | `REAL` | NO | `0.0` | NO |
| `safe_transfers_lbp` | `REAL` | NO | `0.0` | NO |
| `expected_cash_lbp` | `REAL` | NO | `0.0` | NO |
| `actual_cash_lbp` | `REAL` | NO | `0.0` | NO |
| `difference_lbp` | `REAL` | NO | `0.0` | NO |
| `difference_note` | `TEXT` | NO | `''` | NO |
| `orders_count` | `INTEGER` | NO | `0` | NO |
| `status` | `TEXT` | NO | `'closed'` | NO |
| `handover_to_employee_id` | `INTEGER` | NO | `NULL` | NO |
| `handover_to_employee_name` | `TEXT` | NO | `NULL` | NO |
| `created_at` | `TIMESTAMP` | NO | `CURRENT_TIMESTAMP` | NO |
| `approved_by` | `TEXT` | NO | `NULL` | NO |
| `approved_at` | `TIMESTAMP` | NO | `NULL` | NO |
| `approval_status` | `TEXT` | NO | `'pending'` | NO |
| `approval_notes` | `TEXT` | NO | `''` | NO |

### Table: `shift_logs` (94 records)
| Column Name | Type | Not Null | Default Value | PK |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | NO | `NULL` | YES |
| `employee_id` | `INTEGER` | NO | `NULL` | NO |
| `employee_name` | `TEXT` | NO | `NULL` | NO |
| `date` | `TEXT` | NO | `NULL` | NO |
| `total_sales_lbp` | `REAL` | NO | `0` | NO |
| `cash_sales_lbp` | `REAL` | NO | `0` | NO |
| `production_note` | `TEXT` | NO | `NULL` | NO |
| `closed_at` | `TEXT` | NO | `NULL` | NO |
| `created_at` | `TEXT` | NO | `CURRENT_TIMESTAMP` | NO |

### Table: `stock_movements` (8 records)
| Column Name | Type | Not Null | Default Value | PK |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | NO | `NULL` | YES |
| `movement_type` | `TEXT` | YES | `NULL` | NO |
| `item_type` | `TEXT` | NO | `'inventory'` | NO |
| `item_id` | `INTEGER` | YES | `NULL` | NO |
| `item_name` | `TEXT` | YES | `NULL` | NO |
| `quantity` | `REAL` | YES | `NULL` | NO |
| `qty_before` | `REAL` | YES | `0.0` | NO |
| `qty_after` | `REAL` | YES | `0.0` | NO |
| `unit_cost_lbp` | `REAL` | NO | `0.0` | NO |
| `unit_cost_usd` | `REAL` | NO | `0.0` | NO |
| `total_cost_lbp` | `REAL` | NO | `0.0` | NO |
| `total_cost_usd` | `REAL` | NO | `0.0` | NO |
| `reference_type` | `TEXT` | NO | `NULL` | NO |
| `reference_id` | `INTEGER` | NO | `NULL` | NO |
| `user_name` | `TEXT` | NO | `'النظام'` | NO |
| `notes` | `TEXT` | NO | `''` | NO |
| `created_at` | `TIMESTAMP` | NO | `CURRENT_TIMESTAMP` | NO |

### Table: `supplier_payments` (0 records)
| Column Name | Type | Not Null | Default Value | PK |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | NO | `NULL` | YES |
| `supplier_id` | `INTEGER` | YES | `NULL` | NO |
| `amount_usd` | `REAL` | NO | `0.0` | NO |
| `amount_lbp` | `REAL` | NO | `0.0` | NO |
| `payment_method` | `TEXT` | NO | `'safe'` | NO |
| `notes` | `TEXT` | NO | `''` | NO |
| `created_by` | `TEXT` | NO | `'المدير'` | NO |
| `created_at` | `TIMESTAMP` | NO | `CURRENT_TIMESTAMP` | NO |

### Table: `suppliers` (2 records)
| Column Name | Type | Not Null | Default Value | PK |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | NO | `NULL` | YES |
| `name` | `TEXT` | YES | `NULL` | NO |
| `phone` | `TEXT` | NO | `''` | NO |
| `company` | `TEXT` | NO | `''` | NO |
| `balance_usd` | `REAL` | NO | `0.0` | NO |
| `balance_lbp` | `REAL` | NO | `0.0` | NO |
| `notes` | `TEXT` | NO | `''` | NO |
| `is_active` | `INTEGER` | NO | `1` | NO |
| `created_at` | `TIMESTAMP` | NO | `CURRENT_TIMESTAMP` | NO |
