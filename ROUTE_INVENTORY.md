# STARGATE CAFE — Route & API Endpoint Inventory
**Total Endpoints Identified:** 123

| Endpoint | Rule (URL) | HTTP Methods | Line | Security / Decorators | Purpose / Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `custom_serve_uploaded_file` | `/static/uploads/<path:filename>` | `GET` | 312 | None (Public / Default Session) | Explicitly serves uploaded product images with correct MIME type and strict path traversal protection. |
| `dashboard_page` | `/dashboard` | `GET` | 615 | login_required | Executive ERP Dashboard displaying KPIs, real P&L profit, Safe Balance, and charts. |
| `index` | `/` | `GET` | 652 | None (Public / Default Session) | Main Touch POS Screen with Drinks Grid, 1-Click GAMING, and Cashier Panel. |
| `order_create` | `/api/checkout` | `POST` | 700 | login_required | Create a new cafe order or pay an existing open customer tab. |
| `tab_save` | `/tab/save` | `POST` | 808 | login_required | Save or update an open customer tab (الزبائن الجالسون). |
| `tab_delete` | `/tab/<int:tab_id>/delete` | `POST` | 863 | login_required | Cancel / Delete an open customer tab with mandatory audit verification. |
| `api_spoilage_record` | `/spoilage/add` | `POST` | 902 | login_required | تسجيل تالف / هدر لمادة أو منتج مع توثيق السبب والموظف وخصم المخزون. |
| `pc_single_click` | `/pc/click` | `POST` | 935 | login_required | 1-Click Recording for Single Gaming PC. |
| `quick_custom_sale` | `/sale/quick` | `POST` | 950 | login_required | Instant manual sale with typed name and price. |
| `order_receipt` | `/order/<int:order_id>/receipt` | `GET` | 974 | login_required | Printable Thermal Receipt for Cafe. |
| `debts_page` | `/debts` | `GET` | 986 | login_required | Customer Debts Ledger & Balance Tracking. |
| `debt_create_manual` | `/debt/create/manual` | `POST` | 1003 | login_required | Manually add a debt record for a customer. |
| `debt_pay_customer` | `/debt/pay/customer` | `POST` | 1019 | login_required | Record payment for a customer balance. |
| `debt_pay_single` | `/debt/pay/single` | `POST` | 1034 | login_required | Record payment for a single debt record. |
| `debt_delete` | `/debt/<int:debt_id>/cancel` | `POST` | 1050 | admin_required | Delete / Cancel a debt record safely with full audit trail. |
| `admin_login` | `/admin/login` | `GET, POST` | 1064 | None (Public / Default Session) | Admin Login Authentication supporting personal admin employee passwords/PINs. |
| `admin_logout` | `/admin/logout` | `GET, POST` | 1125 | None (Public / Default Session) | Admin Logout. |
| `admin_change_password` | `/admin/change-password` | `POST` | 1134 | admin_required | Change Admin Password dynamically. |
| `admin_panel` | `/admin` | `GET` | 1162 | admin_required | Daily Production & Financial Management Dashboard (Protected). |
| `print_daily` | `/print/daily` | `GET` | 1206 | admin_required | Printable Daily Closing Audit Statement. |
| `expense_add` | `/expense/add` | `POST` | 1229 | admin_required | N/A |
| `expense_quick_add` | `/expense/quick_add` | `POST` | 1263 | login_required | تسجيل مصروف سريع من درج الكاشير بواسطة الموظف أو الإدارة. |
| `coffee_hub` | `/coffee-hub` | `GET` | 1323 | login_required | لوحة تتبع وإدارة حبوب القهوة، الفناجين المبيعة، التالف، ورسمال الفنجان. |
| `coffee_open_bag` | `/coffee/open-bag` | `POST` | 1336 | login_required | فتح كيلو قهوة جديد للاستعمال مع إغلاق الكيلو السابق تلقائياً واحتساب إنتاجيته وأرباحه والتالف. |
| `coffee_close_bag` | `/coffee/close-bag` | `POST` | 1380 | login_required | إنهاء وإغلاق الكيلو المفتوح وحساب الإنتاجية ورسمال الفنجان الدقيق وصافي الربح والتالف. |
| `coffee_log_waste` | `/coffee/log-waste` | `POST` | 1404 | login_required | تسجيل فنجان تالف أثناء التحضير أو سكب. |
| `coffee_update_stock` | `/coffee/update-stock` | `POST` | 1431 | login_required | تعديل رصيد حبوب القهوة (كم كيلو بن متوفر بالمخزن مع السعر الموحد بالدولار واللبناني). |
| `api_coffee_status` | `/api/coffee/status` | `GET` | 1467 | login_required | API لحظي للحصول على حالة الكيلو المفتوح ورصيد البن. |
| `expense_delete` | `/expense/<int:expense_id>/delete` | `POST` | 1479 | admin_required | إلغاء مصروف بطريقة غير مدمرة (Non-Destructive) مع توثيق السبب. |
| `pc_log_delete` | `/pc/log/<int:log_id>/delete` | `POST` | 1493 | admin_required | N/A |
| `order_delete` | `/order/<int:order_id>/delete` | `POST` | 1508 | admin_required | إلغاء فاتورة مع توثيق السبب واستعادة المخزون بشكل تدقيقي آمن. |
| `settings_update` | `/settings/update` | `POST` | 1522 | admin_required | N/A |
| `telegram_test` | `/api/telegram/test` | `POST` | 1532 | admin_required | اختبار فوري لاتصال بوت التيليجرام وإرسال رسالة تجريبية. |
| `telegram_send_daily_report` | `/api/telegram/send-daily-report` | `POST` | 1549 | admin_required | إرسال تقرير الإغلاق المالي الحالي إلى التيليجرام بضغطة زر واحدة. |
| `telegram_send_shift_report` | `/api/telegram/send-shift-report` | `POST` | 1562 | login_required | إرسال تقرير وردية الموظف أو الكاشير إلى تيليجرام المدير فورياً بضغطة زر. |
| `ai_audit_api` | `/api/ai/audit` | `GET` | 1593 | login_required | فحص الذكاء الاصطناعي الشامل للعمليات والمخزون والصندوق والأخطاء. |
| `copilot_chat_api` | `/api/copilot/chat` | `POST` | 1602 | login_required | المساعد الذكي التفاعلي المتكامل لمنظومة STARGATE CAFE. |
| `user_guide_page` | `/user_guide` | `GET` | 1692 | login_required | صفحة دليل الاستخدام الشامل للمنظومة. |
| `categories_page` | `/categories` | `GET` | 1700 | admin_required | صفحة إدارة الأقسام والتصنيفات وتنظيم شاشة الكاشير والربط بالبن. |
| `menu_category_add` | `/categories/add` | `POST` | 1714 | admin_required | N/A |
| `menu_category_edit` | `/categories/<int:cat_id>/edit` | `POST` | 1728 | admin_required | N/A |
| `menu_category_delete` | `/categories/<int:cat_id>/delete` | `POST` | 1742 | admin_required | N/A |
| `category_reorder` | `/categories/reorder/<int:cat_id>/<direction>` | `POST` | 1750 | admin_required | تحريك القسم لأعلى أو لأسفل لترتيب الأزرار في شاشة الكاشير. |
| `categories_reorder_all` | `/categories/reorder-all` | `POST` | 1763 | admin_required | حفظ ترتيب جميع الأقسام المحددة بالترتيب الجديد. |
| `item_move_category` | `/item/<int:item_id>/move-category` | `POST` | 1775 | admin_required | نقل الصنف إلى قسم وتصنيف آخر. |
| `item_toggle_coffee_link` | `/item/<int:item_id>/toggle-coffee-link` | `POST` | 1804 | admin_required | تفعيل أو إلغاء ربط الصنف بخصم كيلو البن (كيس القهوة). |
| `item_reorder` | `/item/<int:item_id>/reorder/<direction>` | `POST` | 1822 | login_required | تحريك الصنف للأمام أو للخلف على شاشة الكاشير لترتيب أماكن المنتجات. |
| `item_set_order` | `/item/<int:item_id>/set-order` | `POST` | 1836 | login_required | تحديد رقم ترتيب الصنف مباشرة. |
| `item_pin_top` | `/item/<int:item_id>/pin-top` | `POST` | 1851 | login_required | تثبيت الصنف في مقدمة شاشة الكاشير كأول صنف. |
| `api_items_auto_sort_sales` | `/api/items/auto-sort-sales` | `POST` | 1861 | login_required | ترتيب أصناف الكاشير تلقائياً حسب الأكثر طلباً ومبيعاً. |
| `api_items_set_position` | `/api/items/set-position` | `POST` | 1868 | login_required | نقل الصنف مباشرة لموضع محدد (مثل الموضع 1 أو 2 أو 5). |
| `api_top_selling_items` | `/api/items/top-selling` | `GET` | 1877 | None (Public / Default Session) | واجهة برمجية لجلب أكثر الأصناف مبيعاً وطلباً لشاشة الكاشير. |
| `menu_item_add` | `/menu/item/add` | `POST` | 1886 | admin_required | N/A |
| `menu_item_edit` | `/menu/item/<int:item_id>/edit` | `POST` | 1907 | admin_required | N/A |
| `menu_item_delete` | `/menu/item/<int:item_id>/delete` | `POST` | 1942 | admin_required | N/A |
| `backup_download` | `/backup/download` | `GET` | 1952 | admin_required | Download a full SQLite database backup file to user computer. |
| `backup_restore` | `/backup/restore` | `POST` | 1964 | admin_required | Upload and restore database from a user backup file. |
| `export_menu_json` | `/export/menu/json` | `GET` | 1985 | admin_required | Download menu items & categories as JSON file. |
| `import_menu` | `/import/menu` | `POST` | 1996 | admin_required | Import menu items & categories from uploaded JSON file. |
| `export_sales_csv_route` | `/export/sales/csv` | `GET` | 2021 | admin_required | Export complete sales, debts, and expenses to Excel CSV. |
| `export_system_json` | `/export/system/json` | `GET` | 2032 | admin_required | Download full system backup as JSON package. |
| `import_system_json` | `/import/system/json` | `POST` | 2043 | admin_required | Import full system backup from uploaded JSON file. |
| `admin_factory_reset` | `/reset/data` | `POST` | 2069 | admin_required | Protected Factory Reset: requires admin PIN or password, auto-backup, and audit. |
| `inventory_page` | `/inventory` | `GET` | 2124 | admin_required | Dedicated Pro Inventory & Stock Management Page with Full Financial Valuation. |
| `export_inventory_csv_route` | `/export/inventory-csv` | `GET` | 2231 | admin_required | Export current stock and inventory list to CSV (Excel compatible with UTF-8 BOM, NO wholesale). |
| `download_inventory_sample_template` | `/inventory/sample-template` | `GET` | 2274 | admin_required | Download clean Arabic CSV template for bulk importing products without wholesale. |
| `import_inventory_csv_route` | `/inventory/import/csv` | `POST` | 2293 | admin_required | Bulk import products and costs from uploaded CSV file. |
| `api_inventory_adjust` | `/api/inventory/adjust` | `POST` | 2324 | admin_required | Secure endpoint for all inventory stock adjustments, restock, waste, and audit counts. |
| `quick_update_item` | `/item/quick-update` | `POST` | 2442 | admin_required | Ultra-fast AJAX inline update for item price, name, or stock. |
| `quick_add_item_inline` | `/item/quick-add` | `POST` | 2462 | admin_required | Instant item creation directly from POS modal. |
| `employees_page` | `/employees` | `GET` | 2490 | admin_required | Employee Management and Staff Performance Dashboard. |
| `add_employee_route` | `/employee/add` | `POST` | 2514 | admin_required | Create new employee. |
| `edit_employee_route` | `/employee/<int:emp_id>/edit` | `POST` | 2525 | admin_required | Update employee details. |
| `delete_employee_route` | `/employee/<int:emp_id>/delete` | `POST` | 2536 | admin_required | Permanently delete employee account. |
| `switch_active_employee` | `/employee/switch` | `POST` | 2556 | None (Public / Default Session) | Switch current active employee on POS using PIN or username/password. |
| `get_current_employee` | `/employee/current` | `GET` | 2592 | None (Public / Default Session) | Return currently active employee in session. |
| `setup_wizard` | `/setup` | `GET, POST` | 2624 | None (Public / Default Session) | Initial setup wizard for fresh installation or full factory reset. |
| `employee_login` | `/employee/login` | `GET, POST` | 2712 | None (Public / Default Session) | Employee shift login screen. |
| `employee_logout` | `/employee/logout` | `GET, POST` | 2743 | None (Public / Default Session) | Logout current employee and lock POS screen. |
| `employee_close_shift` | `/employee/close-shift` | `GET, POST` | 2755 | login_required | Close employee shift, calculate sales, reconcile cash drawer, and handover to next employee. |
| `approve_shift_route` | `/shift/<int:shift_id>/approve` | `POST` | 3003 | admin_required | اعتماد رسمي لإغلاق الوردية ومطابقة الصندوق من قبل الإدارة. |
| `safe_page` | `/safe` | `GET` | 3065 | admin_required | صفحة الخزنة الخاصة مع البحث المتقدم عبر التاريخ ودعم الإيداع والسحب. |
| `safe_transfer` | `/safe/transfer` | `POST` | 3150 | login_required | إضافة عملية إيداع أو سحب للخزنة مع دعم الليرة والدولار والتحقق من الصلاحيات. |
| `cancel_safe_transfer_route` | `/safe/transfer/<int:transfer_id>/delete` | `POST` | 3194 | admin_required | إلغاء حركة من الخزنة مع توثيق السبب وتحديث الأرصدة دون حذف فيزيائي. |
| `financial_ledger_page` | `/financial-ledger` | `GET` | 3209 | admin_required | عرض سجل الحركة المالية المركزي (Audit Ledger) لمدير النظام. |
| `cancel_financial_ledger_route` | `/financial/ledger/<int:ledger_id>/cancel` | `POST` | 3243 | admin_required | إلغاء قيد مالي محدد من السجل المركزي وتوثيق السبب في سجل التدقيق. |
| `financial_statements_page` | `/financial-statements` | `GET` | 3258 | admin_required | مركز القوائم المالية الختامية وإقفال السنة (ERP Financial Hub). |
| `financial_recalculate_route` | `/financial/recalculate` | `POST` | 3320 | admin_required | إعادة احتساب وتزامن كافة أرصدة شجرة الحسابات والمالية من واقع قيود اليومية. |
| `financial_year_end_close_route` | `/financial/year-end-close` | `POST` | 3332 | admin_required | إقفال السنة المالية رسمياً وتدوير الأرباح. |
| `shift_open_float_route` | `/shift/open-float` | `POST` | 3351 | login_required | تسجيل فكة وعهدة بداية الدوام للصندوق بقيد رسمي. |
| `print_safe_statement` | `/print/safe-statement` | `GET` | 3382 | admin_required | طباعة كشف حساب الخزنة للفترة المحددة. |
| `api_inventory_alerts` | `/api/inventory/alerts` | `GET` | 3421 | None (Public / Default Session) | API: جلب عدد المنتجات المنخفضة أو النافدة من المخزون. |
| `api_item_quick_edit` | `/api/item/quick_edit` | `POST` | 3434 | admin_required | N/A |
| `api_item_quick_add` | `/api/item/quick_add` | `POST` | 3543 | admin_required | N/A |
| `safe_quick_transfer` | `/safe/quick_transfer` | `POST` | 3573 | login_required | N/A |
| `reports_page` | `/reports/daily` | `GET` | 3640 | admin_required | صفحة التقارير اليومية وتفاصيل حركة المنتجات والأصناف. |
| `print_reports_page` | `/reports/print` | `GET` | 3771 | admin_required | طباعة التقرير المالي وحركة الأصناف A4. |
| `export_reports_csv` | `/reports/export-csv` | `GET` | 3816 | admin_required | تصدير تقرير مبيعات الأصناف لملف CSV / Excel. |
| `safe_transfer_daily` | `/safe/transfer_daily` | `POST` | 3860 | admin_required | نقل وترحيل صافي نقدية اليوم إلى الخزنة الخاصة مباشرة بنقرة واحدة. |
| `safe_transfer_drawer_total` | `/safe/transfer_drawer_total` | `POST` | 3889 | login_required | ترحيل كامل الرصيد النقدي المتراكم بالدرج إلى الخزنة الخاصة وتصفير رصيد الدرج إلى 0 ل.ل. |
| `api_safe_daily_status` | `/api/safe/daily_status` | `GET` | 3909 | admin_required | API لفحص حالة ترحيل اليوم والمبالغ المتبقية للترحيل. |
| `api_safe_balance` | `/api/safe/balance` | `GET` | 3917 | login_required | API لجلب رصيد الخزنة اللحظي. |
| `api_check_update` | `/api/check_update` | `GET, POST` | 3933 | None (Public / Default Session) | يُعيد حالة التحديث المتاح (JSON) مع الإصدار الحالي المثبت. |
| `api_force_check_update` | `/api/force_check_update` | `GET, POST` | 3944 | None (Public / Default Session) | إعادة الفحص الفوري من GitHub. |
| `api_do_update` | `/api/do_update` | `POST` | 3956 | login_required, admin_required | تنزيل وتثبيت التحديث مع التحقق الأمني والنسخ الاحتياطي (خاص بمدير النظام فقط). |
| `api_manual_update` | `/api/manual_update` | `POST` | 4103 | login_required, admin_required | تطبيق تحديث يدوي إما برفع ملف ZIP أو من ملف موجود على سطح المكتب أو مجلد البرنامج (خاص بمدير النظام). |
| `download_hub_page` | `/download/hub` | `GET` | 4208 | None (Public / Default Session) | صفحة مركز التحميل والتحديثات المباشرة لجهاز الموظف. |
| `login_redirect` | `/login` | `GET` | 4214 | None (Public / Default Session) | N/A |
| `pos_redirect` | `/cashier` | `GET` | 4220 | None (Public / Default Session) | N/A |
| `download_update_zip` | `/update` | `GET` | 4228 | None (Public / Default Session) | تنزيل مباشر لحزمة التحديث من السيرفر المحلي بسرعة الشبكة المحلية. |
| `download_installer_exe` | `/setup.exe` | `GET` | 4251 | None (Public / Default Session) | تنزيل ملف التثبيت الرسمي الكامل v5.3.1 مباشرة لجهاز الموظف. |
| `download_employee_update_bat` | `/download/update_employee.bat` | `GET` | 4267 | None (Public / Default Session) | ملف BAT ديناميكي يُحدّث جهاز الموظف مباشرة من سيرفر الكافيه المحلي. |
| `update_tool_page` | `/update-tool` | `GET` | 4353 | None (Public / Default Session) | صفحة ويب مباشرة ومبسطة لجهاز الموظف لتنزيل وتطبيق التحديث بنقرة واحدة مع إمكانية التحديث اليدوي برفع الملف. |
| `suppliers_page` | `/suppliers` | `GET` | 4576 | admin_required | شاشة إدارة الموردين وفواتير الشراء. |
| `supplier_add` | `/supplier/add` | `POST` | 4592 | admin_required | إضافة مورد جديد. |
| `purchase_invoice_add` | `/purchase/add` | `POST` | 4605 | admin_required | تسجيل فاتورة شراء بضاعة ومواد خام وتغذية المخزون. |
| `supplier_pay_route` | `/supplier/<int:supplier_id>/pay` | `POST` | 4640 | admin_required | سداد دفعة نقدية لحساب المورد. |
| `tables_page` | `/tables` | `GET` | 4668 | login_required | شاشة إدارة طاولات وصالات الكافيه. |
| `table_add` | `/table/add` | `POST` | 4681 | admin_required | إضافة طاولة جديدة. |
| `api_backup_status` | `/api/backup/status` | `GET` | 4702 | admin_required | عرض حالة آخر نسخة احتياطية. |
| `api_backup_now` | `/api/backup/now` | `POST` | 4710 | admin_required | تنفيذ نسخة احتياطية فورية يدوياً. |
| `api_backup_integrity` | `/api/backup/integrity` | `POST` | 4735 | admin_required | فحص سلامة قاعدة البيانات فوراً. |
| `api_maintenance_optimize` | `/api/maintenance/optimize` | `POST` | 4750 | admin_required | تحسين وضغط فهارس قاعدة البيانات وسجلات WAL فوراً. |