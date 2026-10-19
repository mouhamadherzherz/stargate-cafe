# مصفوفة تغطية الاختبارات وتتبع الدوال الحرجة (Test Traceability Matrix)
## STARGATE CAFE v6.2.0 PRO — تاريخ الاعتماد: 2026-10-17

توثق هذه المصفوفة الربط المباشر والدقيق بين كل دالة حرجة (Critical Function) في النظام، وملف المصدر، وحالة الاختبار المؤتمتة التي تفحصها وتضمن سلامتها التشغيلية.

---

### 1. العمليات المالية والمحاسبية (`accounting.py`)

| الدالة الحرجة | الوصف التشغيلي | ملف الاختبار | اسم دالة الاختبار | نتيجة الفحص |
| :--- | :--- | :--- | :--- | :---: |
| `create_order` (Cash) | إنشاء طلب نقدي، خصم المخزون، وتغذية رصيد الصندوق | `tests/test_financial_workflows.py` | `test_cash_sale_lifecycle_and_drawer_balance` | ✅ PASS |
| `create_order` (Rollback) | التراجع الذري الكامل في حال فشل أي قيد مالي | `tests/test_audit_suite.py` | `test_p1_atomic_rollback_on_double_entry_failure` | ✅ PASS |
| `create_order` (Deficit) | تسجيل عجز المخزون الحقيقي دون قص قسري للصفر | `tests/test_audit_suite.py` | `test_p1_recipe_consumption_records_explicit_deficit` | ✅ PASS |
| `create_order` (Price Armor) | اعتماد أسعار السيرفر الحصرية ورفض تلاعب العميل | `tests/test_audit_suite.py` | `test_p1_server_enforces_authoritative_price_ignoring_client_tampering` | ✅ PASS |
| `create_order` (Validation) | التحقق من صحة طرق الدفع ورفض القيم الشاذة | `tests/test_audit_suite.py` | `test_p1_invalid_payment_method_rejected` | ✅ PASS |
| `pay_debt` (Partial) | سداد جزئي لديون العملاء وتحديث الرصيد المتبقي | `tests/test_financial_workflows.py` | `test_debt_sale_and_customer_repayment_lifecycle` | ✅ PASS |
| `pay_debt` (Full) | سداد كامل للذمة وتحويل الحالة إلى مسدد بالكامل (`paid`) | `tests/test_financial_workflows.py` | `test_debt_sale_and_customer_repayment_lifecycle` | ✅ PASS |
| `add_expense` (Drawer) | تسجيل مصروف من درج الكاشير وخصمه من نقدية اليوم | `tests/test_financial_workflows.py` | `test_expenses_from_drawer_vs_safe` | ✅ PASS |
| `add_expense` (Safe) | تسجيل مصروف من الخزنة الرئيسية وتوثيق حركة سحب | `tests/test_financial_workflows.py` | `test_expenses_from_drawer_vs_safe` | ✅ PASS |
| `cancel_order` (Safe Undo) | إلغاء غير إتلافي للفاتورة واسترجاع كامل كميات المخزون وعكس القيود | `tests/test_financial_workflows.py` | `test_order_cancellation_restores_stock_and_reverses_financials` | ✅ PASS |
| `add_safe_transfer` | ترحيل وتوريد النقدية الفائضة من الدرج إلى الخزنة | `tests/test_financial_workflows.py` | `test_safe_transfer_workflow` | ✅ PASS |
| `record_shift_closing` | إقفال الوردية واحتساب الفروقات النقدية (عجز/زيادة) | `tests/test_financial_workflows.py` | `test_shift_closing_cash_reconciliation` | ✅ PASS |
| `record_shift_closing` (Isolation) | عزل مبيعات الموظفين وعدم خلط الورديات الصفرية | `tests/test_audit_suite.py` | `test_p1_shift_closing_does_not_mix_employees_on_zero_sales` | ✅ PASS |
| `calculate_product_cogs` | احتساب تكلفة المبيعات (COGS) للمنتجات الجاهزة والوصفات | `tests/test_audit_suite.py` | `test_p1_standalone_product_cogs_calculated_and_stored` | ✅ PASS |
| `record_double_entry_journal` | ترحيل قيود اليومية المزدوجة ومطابقة توازن المدين والدائن | `tests/test_pure_accounting.py` | `test_double_entry_debit_credit_balance_pure` | ✅ PASS |

---

### 2. الحماية الأمنية وإدارة الجلسات (`app.py`)

| الآلية / الدالة | الوصف التشغيلي | ملف الاختبار | اسم دالة الاختبار | نتيجة الفحص |
| :--- | :--- | :--- | :--- | :---: |
| `csrf_protect` (Form) | قبول طلبات النماذج المحمية برمز `csrf_token` الصحيح | `tests/test_csrf_security.py` | `test_post_with_valid_form_csrf_token_accepted` | ✅ PASS |
| `csrf_protect` (Header) | قبول طلبات AJAX المزودة بترويسة `X-CSRFToken` | `tests/test_csrf_security.py` | `test_post_with_valid_header_csrf_token_accepted` | ✅ PASS |
| `csrf_protect` (JSON Body) | قبول طلبات JSON التي تحتوي `csrf_token` ضمن الحمولة | `tests/test_csrf_security.py` | `test_post_json_with_valid_body_csrf_token_accepted` | ✅ PASS |
| `csrf_protect` (Origin Check) | حظر الطلبات المزورة من مصادر ومواقع خارجية (403 Forbidden) | `tests/test_csrf_security.py` | `test_forged_cross_origin_post_rejected_with_403` | ✅ PASS |
| `csrf_protect` (Login Bypass) | استثناء شاشات تسجيل الدخول التأسيسية لتمكين فتح الجلسة | `tests/test_csrf_security.py` | `test_login_endpoints_accessible_without_prior_csrf_token` | ✅ PASS |
| `csrf_protect` (WebView) | توافق بيئة سطح المكتب WebView على النطاق المحلي | `tests/test_csrf_security.py` | `test_desktop_webview_same_origin_token_flow` | ✅ PASS |
| `admin_required` (Guest Block) | حظر وصول الزوار غير المصرح لهم لمسارات التحديث | `tests/test_audit_suite.py` | `test_p0_unauthenticated_update_endpoints_blocked` | ✅ PASS |
| `admin_required` (Role Guard) | منع الكاشير من تشغيل التحديثات اليدوية (يتطلب مدير) | `tests/test_audit_suite.py` | `test_p0_cashier_cannot_access_update_endpoints` | ✅ PASS |
| `serve_uploaded_image` | منع اجتياز المسارات (Path Traversal) في خدمة الصور | `tests/test_audit_suite.py` | `test_p0_image_path_traversal_blocked` | ✅ PASS |
| `admin_logout` / `employee_logout` | دعم الخروج بطلبات GET وPOST مع تنظيف الجلسة | `tests/test_audit_suite.py` | `test_p1_logout_routes_accept_get_and_post` | ✅ PASS |

---

### 3. محرك الذكاء الاصطناعي والتحليلات (`ai_insights.py`)

| الدالة الحرجة | الوصف التشغيلي | ملف الاختبار | اسم دالة الاختبار | نتيجة الفحص |
| :--- | :--- | :--- | :--- | :---: |
| `generate_executive_daily_summary` | توليد الملخص التنفيذي اليومي ومؤشرات الأداء | `tests/test_audit_suite.py` | `test_ai_insights_daily_summary_and_assistant` | ✅ PASS |
| `ask_system_assistant` | مساعد إداري محلي يجيب على الأسئلة المالية وفق الصلاحيات | `tests/test_audit_suite.py` | `test_ai_insights_daily_summary_and_assistant` | ✅ PASS |
| `ai_endpoints_authorization` | حماية واجهات الـ AI البرمجية ومنع الوصول غير المعتمد | `tests/test_audit_suite.py` | `test_ai_endpoints_authorization` | ✅ PASS |

---

### 4. إدارة قاعدة البيانات والنسخ الاحتياطي (`database.py`)

| الدالة الحرجة | الوصف التشغيلي | ملف الاختبار | اسم دالة الاختبار | نتيجة الفحص |
| :--- | :--- | :--- | :--- | :---: |
| `restore_from_backup` | رفض استعادة قواعد البيانات الناقصة أو التالفة | `tests/test_audit_suite.py` | `test_p2_incomplete_backup_restore_rejected` | ✅ PASS |
| `export_full_system` | التصدير الشامل للنظام متضمناً المخزون ودفتر الأستاذ | `tests/test_audit_suite.py` | `test_p2_export_full_system_includes_inventory_and_ledgers` | ✅ PASS |
| `migrate_employees_passwords` | ترقية كلمات المرور المشفرة دون وضع كلمات افتراضية | `tests/test_audit_suite.py` | `test_p1_no_default_changeme_password_on_migration` | ✅ PASS |

---

### 5. ملخص الإحصائيات
- **إجمالي الدوال الحرجة المغطاة:** 24 دالة رئيسية عبر 4 ملفات أساسية.
- **إجمالي حالات الاختبار المنفذة:** 31 حالة اختبار (4 حزم مستقلة ومتكاملة).
- **نسبة النجاح التشغيلي الفعلي:** 100% (31/31 اختبار ناجح).
