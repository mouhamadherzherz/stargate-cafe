# STARGATE CAFE — Function & Class Architecture Inventory

> Exhaustive static analysis inventory of all modules, classes, methods, and functions.

## Module: `app.py`
- **Total Functions:** 149
- **Total Classes:** 0

### Functions
| Function Name | Line | Decorators | Summary / Docstring |
| :--- | :--- | :--- | :--- |
| `_get_base_dir` | 28 | None | N/A |
| `_get_current_version` | 33 | None | N/A |
| `_version_tuple` | 45 | None | N/A |
| `_background_update_check` | 51 | None | يتحقق من التحديثات في الخلفية - HTTPS verified. |
| `_periodic_update_checker` | 122 | None | N/A |
| `generate_csrf_token` | 165 | None | N/A |
| `inject_global_helpers` | 171 | context_processor | N/A |
| `add_security_and_cache_headers` | 179 | after_request | N/A |
| `save_uploaded_item_image` | 195 | None | High-Definition Studio Image Processor: |
| `custom_serve_uploaded_file` | 312 | None | Explicitly serves uploaded product images with correct MIME type and strict path traversal protection. |
| `_load_or_create_secret_key` | 348 | None | Load persisted secret key or generate+save a new one. |
| `format_currency` | 375 | None | N/A |
| `to_usd` | 383 | None | N/A |
| `format_date` | 403 | None | N/A |
| `format_time_only` | 417 | None | N/A |
| `clean_phone_for_whatsapp` | 431 | None | N/A |
| `login_required` | 445 | None | Require any authenticated employee (admin or cashier). |
| `admin_required` | 457 | None | Require admin/owner level authentication. |
| `csrf_protect` | 477 | before_request | N/A |
| `ensure_default_session` | 520 | before_request | N/A |
| `inject_global_data` | 573 | context_processor | N/A |
| `dashboard_page` | 615 | login_required | Executive ERP Dashboard displaying KPIs, real P&L profit, Safe Balance, and charts. |
| `index` | 652 | None | Main Touch POS Screen with Drinks Grid, 1-Click GAMING, and Cashier Panel. |
| `order_create` | 700 | login_required | Create a new cafe order or pay an existing open customer tab. |
| `tab_save` | 808 | login_required | Save or update an open customer tab (الزبائن الجالسون). |
| `tab_delete` | 863 | login_required | Cancel / Delete an open customer tab with mandatory audit verification. |
| `api_spoilage_record` | 902 | login_required | تسجيل تالف / هدر لمادة أو منتج مع توثيق السبب والموظف وخصم المخزون. |
| `pc_single_click` | 935 | login_required | 1-Click Recording for Single Gaming PC. |
| `quick_custom_sale` | 950 | login_required | Instant manual sale with typed name and price. |
| `order_receipt` | 974 | login_required | Printable Thermal Receipt for Cafe. |
| `debts_page` | 986 | login_required | Customer Debts Ledger & Balance Tracking. |
| `debt_create_manual` | 1003 | login_required | Manually add a debt record for a customer. |
| `debt_pay_customer` | 1019 | login_required | Record payment for a customer balance. |
| `debt_pay_single` | 1034 | login_required | Record payment for a single debt record. |
| `debt_delete` | 1050 | admin_required | Delete / Cancel a debt record safely with full audit trail. |
| `admin_login` | 1064 | None | Admin Login Authentication supporting personal admin employee passwords/PINs. |
| `admin_logout` | 1125 | None | Admin Logout. |
| `admin_change_password` | 1134 | admin_required | Change Admin Password dynamically. |
| `admin_panel` | 1162 | admin_required | Daily Production & Financial Management Dashboard (Protected). |
| `print_daily` | 1206 | admin_required | Printable Daily Closing Audit Statement. |
| `expense_add` | 1229 | admin_required | N/A |
| `expense_quick_add` | 1263 | login_required | تسجيل مصروف سريع من درج الكاشير بواسطة الموظف أو الإدارة. |
| `coffee_hub` | 1323 | login_required | لوحة تتبع وإدارة حبوب القهوة، الفناجين المبيعة، التالف، ورسمال الفنجان. |
| `coffee_open_bag` | 1336 | login_required | فتح كيلو قهوة جديد للاستعمال مع إغلاق الكيلو السابق تلقائياً واحتساب إنتاجيته وأرباحه والتالف. |
| `coffee_close_bag` | 1380 | login_required | إنهاء وإغلاق الكيلو المفتوح وحساب الإنتاجية ورسمال الفنجان الدقيق وصافي الربح والتالف. |
| `coffee_log_waste` | 1404 | login_required | تسجيل فنجان تالف أثناء التحضير أو سكب. |
| `coffee_update_stock` | 1431 | login_required | تعديل رصيد حبوب القهوة (كم كيلو بن متوفر بالمخزن مع السعر الموحد بالدولار واللبناني). |
| `api_coffee_status` | 1467 | login_required | API لحظي للحصول على حالة الكيلو المفتوح ورصيد البن. |
| `expense_delete` | 1479 | admin_required | إلغاء مصروف بطريقة غير مدمرة (Non-Destructive) مع توثيق السبب. |
| `pc_log_delete` | 1493 | admin_required | N/A |
| `order_delete` | 1508 | admin_required | إلغاء فاتورة مع توثيق السبب واستعادة المخزون بشكل تدقيقي آمن. |
| `settings_update` | 1522 | admin_required | N/A |
| `telegram_test` | 1532 | admin_required | اختبار فوري لاتصال بوت التيليجرام وإرسال رسالة تجريبية. |
| `telegram_send_daily_report` | 1549 | admin_required | إرسال تقرير الإغلاق المالي الحالي إلى التيليجرام بضغطة زر واحدة. |
| `telegram_send_shift_report` | 1562 | login_required | إرسال تقرير وردية الموظف أو الكاشير إلى تيليجرام المدير فورياً بضغطة زر. |
| `ai_audit_api` | 1593 | login_required | فحص الذكاء الاصطناعي الشامل للعمليات والمخزون والصندوق والأخطاء. |
| `copilot_chat_api` | 1602 | login_required | المساعد الذكي التفاعلي المتكامل لمنظومة STARGATE CAFE. |
| `user_guide_page` | 1692 | login_required | صفحة دليل الاستخدام الشامل للمنظومة. |
| `categories_page` | 1700 | admin_required | صفحة إدارة الأقسام والتصنيفات وتنظيم شاشة الكاشير والربط بالبن. |
| `menu_category_add` | 1714 | admin_required | N/A |
| `menu_category_edit` | 1728 | admin_required | N/A |
| `menu_category_delete` | 1742 | admin_required | N/A |
| `category_reorder` | 1750 | admin_required | تحريك القسم لأعلى أو لأسفل لترتيب الأزرار في شاشة الكاشير. |
| `categories_reorder_all` | 1763 | admin_required | حفظ ترتيب جميع الأقسام المحددة بالترتيب الجديد. |
| `item_move_category` | 1775 | admin_required | نقل الصنف إلى قسم وتصنيف آخر. |
| `item_toggle_coffee_link` | 1804 | admin_required | تفعيل أو إلغاء ربط الصنف بخصم كيلو البن (كيس القهوة). |
| `item_reorder` | 1822 | login_required | تحريك الصنف للأمام أو للخلف على شاشة الكاشير لترتيب أماكن المنتجات. |
| `item_set_order` | 1836 | login_required | تحديد رقم ترتيب الصنف مباشرة. |
| `item_pin_top` | 1851 | login_required | تثبيت الصنف في مقدمة شاشة الكاشير كأول صنف. |
| `api_items_auto_sort_sales` | 1861 | login_required | ترتيب أصناف الكاشير تلقائياً حسب الأكثر طلباً ومبيعاً. |
| `api_items_set_position` | 1868 | login_required | نقل الصنف مباشرة لموضع محدد (مثل الموضع 1 أو 2 أو 5). |
| `api_top_selling_items` | 1877 | None | واجهة برمجية لجلب أكثر الأصناف مبيعاً وطلباً لشاشة الكاشير. |
| `menu_item_add` | 1886 | admin_required | N/A |
| `menu_item_edit` | 1907 | admin_required | N/A |
| `menu_item_delete` | 1942 | admin_required | N/A |
| `backup_download` | 1952 | admin_required | Download a full SQLite database backup file to user computer. |
| `backup_restore` | 1964 | admin_required | Upload and restore database from a user backup file. |
| `export_menu_json` | 1985 | admin_required | Download menu items & categories as JSON file. |
| `import_menu` | 1996 | admin_required | Import menu items & categories from uploaded JSON file. |
| `export_sales_csv_route` | 2021 | admin_required | Export complete sales, debts, and expenses to Excel CSV. |
| `export_system_json` | 2032 | admin_required | Download full system backup as JSON package. |
| `import_system_json` | 2043 | admin_required | Import full system backup from uploaded JSON file. |
| `admin_factory_reset` | 2069 | admin_required | Protected Factory Reset: requires admin PIN or password, auto-backup, and audit. |
| `inventory_page` | 2124 | admin_required | Dedicated Pro Inventory & Stock Management Page with Full Financial Valuation. |
| `export_inventory_csv_route` | 2231 | admin_required | Export current stock and inventory list to CSV (Excel compatible with UTF-8 BOM, NO wholesale). |
| `download_inventory_sample_template` | 2274 | admin_required | Download clean Arabic CSV template for bulk importing products without wholesale. |
| `import_inventory_csv_route` | 2293 | admin_required | Bulk import products and costs from uploaded CSV file. |
| `api_inventory_adjust` | 2324 | admin_required | Secure endpoint for all inventory stock adjustments, restock, waste, and audit counts. |
| `quick_update_item` | 2442 | admin_required | Ultra-fast AJAX inline update for item price, name, or stock. |
| `quick_add_item_inline` | 2462 | admin_required | Instant item creation directly from POS modal. |
| `employees_page` | 2490 | admin_required | Employee Management and Staff Performance Dashboard. |
| `add_employee_route` | 2514 | admin_required | Create new employee. |
| `edit_employee_route` | 2525 | admin_required | Update employee details. |
| `delete_employee_route` | 2536 | admin_required | Permanently delete employee account. |
| `switch_active_employee` | 2556 | None | Switch current active employee on POS using PIN or username/password. |
| `get_current_employee` | 2592 | None | Return currently active employee in session. |
| `setup_wizard` | 2624 | None | Initial setup wizard for fresh installation or full factory reset. |
| `employee_login` | 2712 | None | Employee shift login screen. |
| `employee_logout` | 2743 | None | Logout current employee and lock POS screen. |
| `employee_close_shift` | 2755 | login_required | Close employee shift, calculate sales, reconcile cash drawer, and handover to next employee. |
| `approve_shift_route` | 3003 | admin_required | اعتماد رسمي لإغلاق الوردية ومطابقة الصندوق من قبل الإدارة. |
| `favicon` | 3029 | None | N/A |
| `internal_server_error_handler` | 3033 | None | N/A |
| `safe_page` | 3065 | admin_required | صفحة الخزنة الخاصة مع البحث المتقدم عبر التاريخ ودعم الإيداع والسحب. |
| `safe_transfer` | 3150 | login_required | إضافة عملية إيداع أو سحب للخزنة مع دعم الليرة والدولار والتحقق من الصلاحيات. |
| `cancel_safe_transfer_route` | 3194 | admin_required | إلغاء حركة من الخزنة مع توثيق السبب وتحديث الأرصدة دون حذف فيزيائي. |
| `financial_ledger_page` | 3209 | admin_required | عرض سجل الحركة المالية المركزي (Audit Ledger) لمدير النظام. |
| `cancel_financial_ledger_route` | 3243 | admin_required | إلغاء قيد مالي محدد من السجل المركزي وتوثيق السبب في سجل التدقيق. |
| `financial_statements_page` | 3258 | admin_required | مركز القوائم المالية الختامية وإقفال السنة (ERP Financial Hub). |
| `financial_recalculate_route` | 3320 | admin_required | إعادة احتساب وتزامن كافة أرصدة شجرة الحسابات والمالية من واقع قيود اليومية. |
| `financial_year_end_close_route` | 3332 | admin_required | إقفال السنة المالية رسمياً وتدوير الأرباح. |
| `shift_open_float_route` | 3351 | login_required | تسجيل فكة وعهدة بداية الدوام للصندوق بقيد رسمي. |
| `print_safe_statement` | 3382 | admin_required | طباعة كشف حساب الخزنة للفترة المحددة. |
| `api_inventory_alerts` | 3421 | None | API: جلب عدد المنتجات المنخفضة أو النافدة من المخزون. |
| `api_item_quick_edit` | 3434 | admin_required | N/A |
| `api_item_quick_add` | 3543 | admin_required | N/A |
| `safe_quick_transfer` | 3573 | login_required | N/A |
| `reports_page` | 3640 | admin_required | صفحة التقارير اليومية وتفاصيل حركة المنتجات والأصناف. |
| `print_reports_page` | 3771 | admin_required | طباعة التقرير المالي وحركة الأصناف A4. |
| `export_reports_csv` | 3816 | admin_required | تصدير تقرير مبيعات الأصناف لملف CSV / Excel. |
| `safe_transfer_daily` | 3860 | admin_required | نقل وترحيل صافي نقدية اليوم إلى الخزنة الخاصة مباشرة بنقرة واحدة. |
| `safe_transfer_drawer_total` | 3889 | login_required | ترحيل كامل الرصيد النقدي المتراكم بالدرج إلى الخزنة الخاصة وتصفير رصيد الدرج إلى 0 ل.ل. |
| `api_safe_daily_status` | 3909 | admin_required | API لفحص حالة ترحيل اليوم والمبالغ المتبقية للترحيل. |
| `api_safe_balance` | 3917 | login_required | API لجلب رصيد الخزنة اللحظي. |
| `api_check_update` | 3933 | None | يُعيد حالة التحديث المتاح (JSON) مع الإصدار الحالي المثبت. |
| `api_force_check_update` | 3944 | None | إعادة الفحص الفوري من GitHub. |
| `api_do_update` | 3956 | login_required, admin_required | تنزيل وتثبيت التحديث مع التحقق الأمني والنسخ الاحتياطي (خاص بمدير النظام فقط). |
| `api_manual_update` | 4103 | login_required, admin_required | تطبيق تحديث يدوي إما برفع ملف ZIP أو من ملف موجود على سطح المكتب أو مجلد البرنامج (خاص بمدير النظام). |
| `download_hub_page` | 4208 | None | صفحة مركز التحميل والتحديثات المباشرة لجهاز الموظف. |
| `login_redirect` | 4214 | None | N/A |
| `pos_redirect` | 4220 | None | N/A |
| `download_update_zip` | 4228 | None | تنزيل مباشر لحزمة التحديث من السيرفر المحلي بسرعة الشبكة المحلية. |
| `download_installer_exe` | 4251 | None | تنزيل ملف التثبيت الرسمي الكامل v5.3.1 مباشرة لجهاز الموظف. |
| `download_employee_update_bat` | 4267 | None | ملف BAT ديناميكي يُحدّث جهاز الموظف مباشرة من سيرفر الكافيه المحلي. |
| `update_tool_page` | 4353 | None | صفحة ويب مباشرة ومبسطة لجهاز الموظف لتنزيل وتطبيق التحديث بنقرة واحدة مع إمكانية التحديث اليدوي برفع الملف. |
| `suppliers_page` | 4576 | admin_required | شاشة إدارة الموردين وفواتير الشراء. |
| `supplier_add` | 4592 | admin_required | إضافة مورد جديد. |
| `purchase_invoice_add` | 4605 | admin_required | تسجيل فاتورة شراء بضاعة ومواد خام وتغذية المخزون. |
| `supplier_pay_route` | 4640 | admin_required | سداد دفعة نقدية لحساب المورد. |
| `tables_page` | 4668 | login_required | شاشة إدارة طاولات وصالات الكافيه. |
| `table_add` | 4681 | admin_required | إضافة طاولة جديدة. |
| `api_backup_status` | 4702 | admin_required | عرض حالة آخر نسخة احتياطية. |
| `api_backup_now` | 4710 | admin_required | تنفيذ نسخة احتياطية فورية يدوياً. |
| `api_backup_integrity` | 4735 | admin_required | فحص سلامة قاعدة البيانات فوراً. |
| `api_maintenance_optimize` | 4750 | admin_required | تحسين وضغط فهارس قاعدة البيانات وسجلات WAL فوراً. |
| `start_background_scheduler` | 4766 | None | Unified lifecycle starter for the automatic backup scheduler (callable from app.py or desktop_app.py). |
| `handle_bad_request` | 4780 | None | N/A |
| `handle_not_found` | 4786 | None | N/A |
| `handle_internal_error` | 4794 | None | N/A |

---

## Module: `accounting.py`
- **Total Functions:** 137
- **Total Classes:** 1

### Classes
- **Class `ProductSalesResult`** (Line 2)
  - Methods: __init__, __getitem__, get, keys, items, values

### Functions
| Function Name | Line | Decorators | Summary / Docstring |
| :--- | :--- | :--- | :--- |
| `round_money` | 39 | None | Unified central currency rounding: |
| `calculate_order_totals` | 56 | None | Single source of truth for calculating order totals. |
| `get_local_now` | 105 | None | N/A |
| `get_business_date` | 110 | None | N/A |
| `generate_order_number` | 121 | None | توليد رقم فاتورة غير قابل للتكرار إطلاقاً: |
| `get_settings` | 152 | None | N/A |
| `record_financial_ledger_entry` | 171 | None | سجل الحركة المالية المركزي المزدوج (Immutable Financial Ledger). |
| `get_financial_ledger_entries` | 292 | None | جلب سجل الحركات المالية المركزي مع الفلاتر ودعم التاريخ والنوع. |
| `cancel_financial_ledger_entry` | 318 | None | إلغاء قيد مالي مع تسجيل بيانات الإلغاء وتعديل الأرصدة. |
| `record_shift_closing` | 350 | None | تسجيل إغلاق ومطابقة الوردية في سجل shift_closings المحاسبي. |
| `approve_shift_closing` | 456 | None | اعتماد رسمي لإغلاق الوردية ومطابقة الصندوق من قبل المدير أو المالك (Approval Flow). |
| `get_shift_closings` | 488 | None | جلب سجلات إغلاق ومطابقة الورديات. |
| `get_admin_password_hash` | 505 | None | Retrieve hashed admin password from DB. |
| `get_admin_password` | 520 | None | N/A |
| `verify_admin_password` | 523 | None | Verify entered password against hashed admin password. |
| `verify_manager_or_admin_pin` | 532 | None | Verify PIN/Password against system admin password OR any active manager/admin employee. |
| `update_admin_password` | 557 | None | Update admin password (hashed). |
| `update_settings` | 575 | None | N/A |
| `get_categories` | 624 | None | N/A |
| `add_category` | 638 | None | N/A |
| `update_category` | 660 | None | N/A |
| `delete_category` | 681 | None | N/A |
| `reorder_category` | 693 | None | تحريك القسم لأعلى أو لأسفل لتغيير ترتيب أزرار الكاشير. |
| `save_categories_order` | 729 | None | حفظ ترتيب جميع الأقسام دفعة واحدة. |
| `move_item_to_category` | 747 | None | نقل صنف من قسم إلى قسم آخر. |
| `reorder_item` | 764 | None | تحريك الصنف للأمام أو للخلف في شاشة الكاشير. |
| `set_item_sort_order` | 816 | None | تحديد رقم ترتيب الصنف مباشرة. |
| `pin_item_to_top` | 829 | None | تثبيت الصنف في أول شاشة الكاشير في الموضع رقم 1 (المفضلة والأكثر مبيعاً). |
| `auto_sort_items_by_sales` | 850 | None | ترتيب أصناف الكاشير تلقائياً حسب الأكثر طلباً ومبيعاً لوضعها في متناول يد الموظف مباشرة. |
| `set_item_exact_position` | 873 | None | نقل الصنف لموضع محدد بدقة (مثلاً الموضع 1 أو 2 أو 5). |
| `get_top_selling_items` | 899 | None | جلب أكثر الأصناف طلباً ومبيعاً تلقائياً لوضعها في متناول يد الكاشير. |
| `toggle_coffee_bean_link` | 918 | None | تبديل حالة ربط الصنف بكيلو البن (يخصم / لا يخصم من كيس البن). |
| `get_categories_with_items` | 941 | None | جلب جميع الأقسام مع الأصناف التابعة لها لإدارة التصنيفات. |
| `get_item` | 972 | None | Fetch a single item by its ID with category metadata. |
| `get_items` | 986 | None | N/A |
| `normalize_arabic_coffee_text` | 1011 | None | N/A |
| `is_coffee_item` | 1019 | None | Check if an item deducts from the coffee beans (kilo bag). |
| `add_item` | 1063 | None | N/A |
| `update_item` | 1123 | None | N/A |
| `delete_item` | 1228 | None | N/A |
| `create_order` | 1238 | None | Create a paid or debt order or checkout & pay an existing open customer tab. |
| `save_customer_tab` | 1683 | None | Save or update an open customer tab (الزبائن الجالسون بالمحل) including discounts. |
| `get_open_tabs` | 1848 | None | Get all open seated customer tabs currently in the cafe. |
| `log_shift_close` | 1870 | None | تسجيل إغلاق وردية الموظف مع ملاحظات الإنتاج. |
| `get_shift_logs` | 1903 | None | جلب سجلات إغلاق الورديات. |
| `get_low_stock_items` | 1943 | None | جلب المنتجات التي وصل مخزونها للحد الأدنى أو نفد. |
| `get_inventory_alerts_count` | 1963 | None | عدد المنتجات التي نفدت أو على وشك النفاد. |
| `delete_tab` | 1971 | None | إلغاء طاولة/حساب زبون مع توثيق رقابي إلزامي ومسار تدقيق، مع خيار توثيق الأصناف التالفة. |
| `record_spoilage_waste` | 2036 | None | تسجيل بضاعة تالفة أو مهدورة وخصمها من المخزون مع توثيق إلزامي في السجل الرقابي. |
| `get_orders` | 2099 | None | N/A |
| `get_product_sales_breakdown` | 2128 | None | Return detailed sales breakdown of each sold product (name, category, qty, revenue, pct). |
| `get_order_details` | 2232 | None | N/A |
| `cancel_order` | 2248 | None | إلغاء فاتورة بطريقة محاسبية آمنة (Non-Destructive Cancellation): |
| `delete_order` | 2359 | None | حذف/إلغاء فاتورة مع استرجاع المخزون تلقائياً وإلغاء أي ذمة مرتبطة (legacy wrapper → cancel_order). |
| `log_single_pc_click` | 2366 | None | N/A |
| `get_pc_logs` | 2390 | None | N/A |
| `delete_pc_log` | 2419 | None | N/A |
| `add_expense` | 2424 | None | تسجيل مصروف جديد مع تحديد مصدر الدفع: |
| `get_expenses` | 2504 | None | جلب سجل المصاريف مع دعم التصفية باليوم ومصدر السداد. |
| `cancel_expense` | 2525 | None | إلغاء مصروف بطريقة محاسبية آمنة: |
| `delete_expense` | 2593 | None | حذف مصروف وإلغاء أثره المحاسبي (legacy wrapper → cancel_expense). |
| `get_daily_summary` | 2602 | None | Professional Accounting Breakdown: |
| `get_weekly_trend` | 2888 | None | N/A |
| `factory_reset` | 2905 | None | Reset system to factory default or clear transactions. |
| `add_manual_debt` | 3033 | None | Record a manual customer debt. |
| `get_debts_summary` | 3062 | None | Get aggregated summary of all outstanding and settled debts. |
| `get_customers_debt_balances` | 3100 | None | Get grouped balances per customer with remaining debts. |
| `get_all_debts` | 3127 | None | Get full list of individual debt records with order details. |
| `pay_debt` | 3159 | None | Record payment for a specific debt record. |
| `pay_customer_balance` | 3248 | None | Pay off customer debts across multiple records (oldest first). |
| `delete_debt` | 3280 | None | إلغاء دين بطريقة محاسبية آمنة (Non-Destructive Soft Cancel): |
| `export_menu_data` | 3347 | None | Export all categories and items as a clean dictionary. |
| `import_menu_data` | 3371 | None | Import categories and items from JSON dictionary. |
| `export_full_system_data` | 3454 | None | Export complete system data (Settings, Categories, Menu, Debts, Expenses, Orders, Inventory, Ledger, Journals) as JSON dictionary. |
| `import_full_system_data` | 3517 | None | Safely restore all system data from full JSON dictionary. |
| `export_sales_csv` | 3648 | None | Export sales, debts, and expenses to standard UTF-8 CSV string for Excel. |
| `quick_update_item_field` | 3736 | None | Ultra-fast inline edit for item price (LBP or USD), name, or stock quantity with movement logging. |
| `get_inventory_stock` | 3830 | None | Retrieve all items with their stock information, category name, cost, and wholesale prices. |
| `get_all_employees` | 3867 | None | Return list of all active/inactive employees. |
| `add_employee` | 3880 | None | Add new employee with hashed password and PIN. |
| `update_employee` | 3915 | None | Update employee details (hashes new password/PIN if provided). |
| `delete_employee` | 3959 | None | Permanently delete employee. |
| `authenticate_employee` | 3977 | None | Authenticate employee by username+password OR by quick PIN. |
| `_auto_upgrade_pin` | 4014 | None | If PIN was stored as plain text, upgrade to hash silently. |
| `_auto_upgrade_password` | 4030 | None | If password was stored as plain text, upgrade to hash silently. |
| `get_employee_performance_summary` | 4045 | None | Return breakdown of orders count and revenue generated by each employee (daily or all-time). |
| `add_safe_transfer` | 4097 | None | نقل أو سحب مبلغ من/إلى الخزنة الخاصة مع التمييز الدقيق بين مصادر النقدية والوجهات وتوثيقه في السجل المالي. |
| `cancel_safe_transfer` | 4229 | None | إلغاء حركة خزنة خاصة مع الحفاظ التام على السجل وتوثيق سبب الإلغاء ومنع الحذف النهائي. |
| `get_safe_transfers` | 4272 | None | جلب سجل عمليات الخزنة مع البحث بالتواريخ (يوم محدد أو فترة من - إلى) والبحث النصي والحالة. |
| `get_safe_balance` | 4317 | None | حساب الرصيد الإجمالي الحقيقي للخزنة اعتماداً على سجل الحركة المالية المركزي المزدوج (financial_ledger): |
| `get_safe_daily_summary` | 4402 | None | ملخص حركة الخزنة لفترة محددة (اليوم أو نطاق زمني) مع استبعاد الحركات الملغاة. |
| `delete_safe_transfer` | 4458 | None | حذف عملية خزنة. |
| `get_safe_weekly_summary` | 4469 | None | ملخص الخزنة للأيام الـ 7 الأخيرة. |
| `get_drawer_cash_status` | 4493 | None | حساب وضع الكاش الفعلي في درج الكاشير بصورة تراكمية: |
| `check_daily_safe_transfer_status` | 4594 | None | يفحص ما إذا كان كاش اليوم أو تاريخ محدد قد تم ترحيله إلى الخزنة الخاصة بالفعل أم لا، |
| `transfer_daily_net_to_safe` | 4696 | None | ترحيل صافي مبيعات يوم محدد ونقلها مباشرة للخزنة الخاصة. |
| `transfer_drawer_total_to_safe` | 4754 | None | ترحيل كامل الرصيد النقدي المتراكم في درج الكاشير إلى الخزنة الخاصة (صندوق المالك). |
| `get_hourly_sales_distribution` | 4788 | None | جلب توزيع المبيعات على ساعات اليوم لمعرفة ساعات الذروة. |
| `get_category_sales_distribution` | 4809 | None | جلب نسبة مبيعات كل قسم وتصنيف (مشروبات ساخنة، باردة، مأكولات، ألعاب...). |
| `get_suppliers` | 4845 | None | جلب قائمة الموردين مع أرصدتهم الحالية. |
| `add_supplier` | 4858 | None | إضافة مورد جديد أو تحديث بياناته. |
| `get_supplier` | 4884 | None | جلب بيانات مورد محدد بواسطة المعرف. |
| `record_purchase_invoice` | 4893 | None | تسجيل فاتورة شراء بضاعة / مواد خام: |
| `record_supplier_payment` | 5053 | None | سداد دفعة نقدية لحساب مورد من الخزنة أو الصندوق. |
| `get_dining_tables` | 5147 | None | جلب جميع طاولات الكافيه مع حالتها وحساب الطلب الحالي إن وجد. |
| `add_dining_table` | 5161 | None | إضافة طاولة جديدة للكافيه. |
| `get_comprehensive_financial_statement` | 5179 | None | بيان الدخل والأرباح والخسائر الشامل (P&L Income Statement): |
| `get_chart_of_accounts` | 5309 | None | جلب شجرة الحسابات المحاسبية كاملة مع أرصدتها وحالتها وفق القواعد المحاسبية الدقيقة (Normal Balance). |
| `record_double_entry_journal` | 5342 | None | إنشاء قيد محاسبي مزدوج (Double-Entry Journal Entry): |
| `recalculate_all_account_balances` | 5441 | None | إعادة احتساب وتزامن كافة أرصدة شجرة الحسابات (Accounts) بدقة متناهية من واقع قيود اليومية المعتمدة (Posted). |
| `get_journal_entries` | 5488 | None | جلب القيود المحاسبية المزدوجة مع بنود القيد (Lines) وتفاصيل المدين والدائن. |
| `record_shift_opening_float` | 5513 | None | تسجيل العهدة الافتتاحية للصندوق (فكة بداية الدوام) بقيد محاسبي مزدوج وسجل مالي رسمي: |
| `get_trial_balance` | 5572 | None | توليد ميزان المراجعة المحاسبي (Trial Balance): |
| `get_income_statement` | 5648 | None | قائمة الدخل والأرباح والخسائر (Income Statement / Profit & Loss): |
| `get_balance_sheet` | 5755 | None | الميزانية العمومية والمركز المالي (Balance Sheet): |
| `close_fiscal_year` | 5862 | None | إقفال السنة المالية رسمياً وتصفير الحسابات المؤقتة وترحيل صافي الربح إلى الأرباح المدورة: |
| `get_fiscal_closings` | 5997 | None | جلب سجل إقفالات السنوات المالية المسجلة. |
| `record_stock_movement` | 6014 | None | تسجيل حركة مخزون دقيقة وموثقة في سجل stock_movements. |
| `get_stock_movements` | 6045 | None | جلب سجل حركات المخزون التفصيلية مع أسماء المستخدمين والأسباب. |
| `get_recipes_for_item` | 6062 | None | جلب مكونات ومعادلة تصنيع صنف معين. |
| `calculate_item_cogs` | 6077 | None | حساب تكلفة إنتاج صنف الكافيه (COGS) بدقة بناءً على مكونات الـ recipes وتكلفة المواد في المخزون: |
| `import_inventory_from_csv` | 6105 | None | Import and bulk upsert products and inventory items from CSV. |
| `generate_coffee_batch_code` | 6253 | None | توليد كود فريد للكيلو ومقاوم للتكرار 100%: BAG-YYYYMMDD-XX |
| `get_coffee_beans_stock` | 6284 | None | الحصول على رصيد حبوب القهوة (البن) المتوفر بالمحل بالكيلو وسعره بالدولار واللبناني وفق سعر الصرف. |
| `update_coffee_beans_stock` | 6333 | None | تعديل أو زيادة رصيد حبوب القهوة بالكيلو وسعر شراء الكيلو الموحد بالدولار واللبناني: |
| `get_last_closed_coffee_batch` | 6388 | None | جلب آخر كيلو قهوة تم إغلاقه مع عدد الفناجين التي أنتجها فعلياً. |
| `get_active_coffee_batch` | 6418 | None | جلب الكيلو المفتوح حالياً للتشغيل مع حسابات الفنجان والربح والخسارة بالتفصيل: |
| `open_coffee_bag` | 6529 | None | تسجيل فتح كيلو قهوة جديد للاستعمال (1000 جرام): |
| `record_coffee_cups_sold` | 6658 | None | تحديث فوري لعداد فناجين القهوة المبيعة للكيلو المفتوح حالياً. |
| `record_coffee_waste` | 6697 | None | تسجيل فنجان تالف (تلف): |
| `close_coffee_bag` | 6776 | None | إنهاء وإغلاق الكيلو: |
| `get_coffee_dashboard_summary` | 6856 | None | كشف إحصائي وتحليلي شامل لنظام القهوة والبن مع تقييم واضح لنتائج كل كيلو. |
| `get_coffee_period_stats` | 6953 | None | جلب إحصائيات القهوة والتوالف والإنتاجية لأي فترة أو تاريخ محدد للتقارير الشاملة. |
| `ai_audit_system` | 7085 | None | مساعد و خبير تدقيق مالي ذكي بالكامل: |
| `send_telegram_message` | 7344 | None | إرسال رسالة نصية أو تقرير ذكي عبر Telegram Bot API مباشرة. |
| `send_daily_closing_telegram_report` | 7379 | None | إنشاء وإرسال ملخص تقرير الإغلاق المالي الذكي لليوم إلى حساب تيليجرام المحدد. |
| `send_shift_closing_telegram_report` | 7421 | None | إرسال تقرير إغلاق الوردية الخاص بالموظف فورياً إلى تيليجرام المدير. |

---

## Module: `database.py`
- **Total Functions:** 19
- **Total Classes:** 0

### Functions
| Function Name | Line | Decorators | Summary / Docstring |
| :--- | :--- | :--- | :--- |
| `get_db_dir` | 19 | None | N/A |
| `get_db` | 49 | None | N/A |
| `hash_password` | 71 | None | Hash a plain-text password/PIN using werkzeug pbkdf2. |
| `verify_password` | 76 | None | Verify plain text against a stored hash OR plain-text legacy value. |
| `_needs_hash_upgrade` | 91 | None | N/A |
| `init_db` | 98 | None | Initialize database – create tables, run migrations, zero defaults. |
| `_run_migrations` | 661 | None | Add missing columns to existing databases (idempotent). |
| `_create_indexes` | 782 | None | Create performance indexes (idempotent). |
| `optimize_db` | 838 | None | Run SQLite maintenance, write-ahead log checkpoint and query planner optimization. |
| `_seed_chart_of_accounts` | 850 | None | Seed standard Chart of Accounts for Cafe & Gaming ERP. |
| `_migrate_passwords` | 907 | None | One-time migration: convert plain-text employee passwords/PINs to hashes. |
| `_needs_hash_upgrade` | 942 | None | N/A |
| `write_audit_log` | 949 | None | Write structured audit entry to DB. Accepts both positional and keyword variants. |
| `seed_default_sample_menu` | 985 | None | Seed default cafe categories and items – only on first run. |
| `reset_operational_data` | 1053 | None | Reset daily transactions without touching menu or settings. |
| `_prune_old_backups` | 1070 | None | Keep the latest N backups in a directory and safely delete older ones. |
| `create_backup_copy` | 1090 | None | Create a consistent sqlite backup, verify integrity, replicate to safe locations, and return (path, filename). |
| `restore_from_backup` | 1141 | None | Safely restore database from uploaded backup file with rollback on failure. |
| `_safe_remove` | 1221 | None | N/A |

---

## Module: `backup.py`
- **Total Functions:** 7
- **Total Classes:** 0

### Functions
| Function Name | Line | Decorators | Summary / Docstring |
| :--- | :--- | :--- | :--- |
| `_get_base_dir` | 29 | None | N/A |
| `get_backup_dir` | 35 | None | N/A |
| `perform_backup` | 41 | None | نسخة احتياطية بالـ SQLite Online Backup API - لا يوقف السيرفر. |
| `perform_integrity_check` | 80 | None | فحص سلامة قاعدة البيانات أسبوعياً. |
| `_fallback_backup_loop` | 97 | None | حلقة احتياطية تعمل بخيط منفصل في حال عدم توفر مكتبة APScheduler. |
| `start_backup_scheduler` | 117 | None | جدولة نسخ احتياطي يومي الساعة 3 صباحاً + فحص أسبوعي. |
| `get_backup_status` | 151 | None | معلومات آخر نسخة احتياطية. |

---

## Module: `logger.py`
- **Total Functions:** 6
- **Total Classes:** 0

### Functions
| Function Name | Line | Decorators | Summary / Docstring |
| :--- | :--- | :--- | :--- |
| `_get_base_dir` | 11 | None | N/A |
| `_make_handler` | 28 | None | N/A |
| `_make_console_handler` | 42 | None | N/A |
| `get_app_logger` | 51 | None | General application logger → logs/app.log |
| `get_audit_logger` | 71 | None | Audit logger → logs/audit.log  (immutable records) |
| `log_audit` | 95 | None | Write a structured audit entry. |

---

## Module: `desktop_app.py`
- **Total Functions:** 5
- **Total Classes:** 0

### Functions
| Function Name | Line | Decorators | Summary / Docstring |
| :--- | :--- | :--- | :--- |
| `log` | 19 | None | N/A |
| `find_free_port` | 45 | None | N/A |
| `run_flask` | 58 | None | N/A |
| `wait_for_server` | 73 | None | N/A |
| `launch_desktop_gui` | 86 | None | N/A |

---
