# -*- coding: utf-8 -*-
"""
STARGATE CAFE — Universal Test Runner & Health Diagnostic System
Auto-detects environment dependencies and executes the appropriate test suites.
- In bare Python 3 environments without third-party packages: executes Zero-Dependency Pure Accounting Suite.
- In standard environments with requirements.txt: executes complete 4-tier test suite (Pure + Financial Workflows + CSRF Security + Full Audit).
- Automatically documents results in TEST_RESULTS.md.
"""

import os
import sys
import time
import unittest
from datetime import datetime

# Configure UTF-8 console output for Windows to prevent charmap encoding errors
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)


def check_dependencies():
    """Detects if Flask and Werkzeug are installed in the active environment."""
    missing = []
    try:
        import flask
    except ImportError:
        missing.append('flask')
    try:
        import werkzeug
    except ImportError:
        missing.append('werkzeug')
    return missing


def run_all_tests():
    start_time = time.time()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print("=" * 75)
    print("      STARGATE CAFE v6.2.0 PRO — نظام تشخيص واختبار النظام الشامل")
    print("=" * 75)
    print(f"توقيت الفحص: {now_str}")
    print(f"مسار المشروع: {BASE_DIR}")
    print(f"إصدار بايثون: {sys.version.split()[0]} ({sys.platform})")

    missing_deps = check_dependencies()
    suites_to_run = []

    # 1. Zero-dependency suite (Always runs everywhere)
    import tests.test_pure_accounting
    pure_suite = unittest.defaultTestLoader.loadTestsFromModule(tests.test_pure_accounting)
    suites_to_run.append(('Zero-Dependency Core Accounting', pure_suite))

    if missing_deps:
        print("\n" + "!" * 75)
        print("⚠️  تنبيه بيئة الفحص: بعض الحزم الخارجية غير مثبتة:")
        for dep in missing_deps:
            print(f"   - {dep}")
        print("💡 لتشغيل حزمة التكامل الشاملة (Flask/CSRF/Integration):")
        print("   pip install -r requirements.txt")
        print("!" * 75)
        print("\nجاري تشغيل حزمة الفحص القياسية المستقلة (Standard Library Only)...")
    else:
        print("✅ جميع المتطلبات متوفرة (Flask, Werkzeug, SQLite).")
        print("جاري تشغيل حزم الاختبار المتكاملة الكاملة (4 مستويات)...")

        # 2. Financial Workflows Suite
        import tests.test_financial_workflows
        fin_suite = unittest.defaultTestLoader.loadTestsFromModule(tests.test_financial_workflows)
        suites_to_run.append(('Financial Workflows & Ledger Integration', fin_suite))

        # 3. CSRF & Session Security Suite
        import tests.test_csrf_security
        csrf_suite = unittest.defaultTestLoader.loadTestsFromModule(tests.test_csrf_security)
        suites_to_run.append(('Operational CSRF & Session Security', csrf_suite))

        # 4. Comprehensive Audit & Regression Suite
        import tests.test_audit_suite
        audit_suite = unittest.defaultTestLoader.loadTestsFromModule(tests.test_audit_suite)
        suites_to_run.append(('Comprehensive Audit & Regression Suite', audit_suite))

        # 5. POS Cashier Premium Emerald Edition Suite
        import tests.test_pos_premium_emerald
        pos_suite = unittest.defaultTestLoader.loadTestsFromModule(tests.test_pos_premium_emerald)
        suites_to_run.append(('POS Cashier Premium Emerald Edition Suite', pos_suite))

        # 6. Next-Gen Orders Management Hub Suite
        import tests.test_orders_management
        orders_mgmt_suite = unittest.defaultTestLoader.loadTestsFromModule(tests.test_orders_management)
        suites_to_run.append(('Next-Gen Orders Management Hub Suite', orders_mgmt_suite))

    # Execute suites
    total_ran = 0
    total_failures = 0
    total_errors = 0
    suite_summaries = []

    for name, suite in suites_to_run:
        print("\n" + "-" * 75)
        print(f"▶ تشغيل حزمة: {name} ({suite.countTestCases()} اختبار)")
        print("-" * 75)
        runner = unittest.TextTestRunner(verbosity=2)
        res = runner.run(suite)
        total_ran += res.testsRun
        total_failures += len(res.failures)
        total_errors += len(res.errors)
        suite_summaries.append({
            'name': name,
            'count': res.testsRun,
            'failures': len(res.failures),
            'errors': len(res.errors),
            'ok': res.wasSuccessful()
        })

    elapsed = round(time.time() - start_time, 2)
    overall_ok = (total_failures == 0 and total_errors == 0)

    print("\n" + "=" * 75)
    print("                    ملخص النتائج النهائي")
    print("=" * 75)
    print(f"إجمالي الاختبارات المنفذة: {total_ran}")
    print(f"حالات الفشل: {total_failures}")
    print(f"أخطاء التنفيذ: {total_errors}")
    print(f"مدة الفحص: {elapsed} ثانية")
    print(f"الحالة العامة: {'✅ نجاح تام (100% PASS)' if overall_ok else '❌ توجد إخفاقات'}")
    print("=" * 75)

    # Document results to TEST_RESULTS.md
    report_path = os.path.join(BASE_DIR, "TEST_RESULTS.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# تقرير الفحص والاختبار التشغيلي — STARGATE CAFE v6.2.0 PRO\n\n")
        f.write(f"- **تاريخ وتوقيت الفحص:** {now_str}\n")
        f.write(f"- **بيئة التشغيل:** Python {sys.version.split()[0]} on {sys.platform}\n")
        f.write(f"- **المتطلبات الخارجية:** {'مكتملة ومثبتة' if not missing_deps else 'ناقصة: ' + ', '.join(missing_deps)}\n")
        f.write(f"- **المدة الزمنية:** {elapsed} ثانية\n")
        f.write(f"- **النتيجة العامة:** {'✅ 100% نجاح تام — معتمد للتشغيل' if overall_ok else '❌ فشل'}\n\n")
        
        f.write("## 1. جدول الحزم المنفذة\n\n")
        f.write("| حزمة الاختبار | عدد الاختبارات | الإخفاقات | الأخطاء | النتيجة |\n")
        f.write("| :--- | :---: | :---: | :---: | :---: |\n")
        for s in suite_summaries:
            status_str = "✅ نجاح" if s['ok'] else "❌ فشل"
            f.write(f"| {s['name']} | {s['count']} | {s['failures']} | {s['errors']} | {status_str} |\n")
        f.write(f"| **الإجمالي** | **{total_ran}** | **{total_failures}** | **{total_errors}** | **{'✅ اجتياز كامل' if overall_ok else '❌ إخفاق'}** |\n\n")

        f.write("## 2. تفصيل تغطية الحزم\n\n")
        f.write("1. **Zero-Dependency Core Accounting (`tests/test_pure_accounting.py`)**:\n")
        f.write("   - اختبار الذرية والتراجع (Rollback) في SQLite القياسي بدون أي مكتبات.\n")
        f.write("   - اختبار تسعير السيرفر الحصري ومنع تلاعب العميل.\n")
        f.write("   - اختبار مطابقة المدين والدائن في القيد المزدوج.\n")
        f.write("   - اختبار عجز المخزون والوصفات دون قص للصفر.\n\n")

        f.write("2. **Financial Workflows (`tests/test_financial_workflows.py`)**:\n")
        f.write("   - اختبار دورة البيع النقدي وتحديث رصيد درج الكاشير.\n")
        f.write("   - اختبار مبيعات الديون والذمم وسدادها الجزئي والكامل عبر `pay_debt`.\n")
        f.write("   - اختبار التمييز بين مصاريف الدرج (`source='drawer'`) ومصاريف الخزنة (`source='safe'`).\n")
        f.write("   - اختبار الإلغاء غير الإتلافي للفواتير (`cancel_order`) واسترجاع المخزون وعكس القيود.\n")
        f.write("   - اختبار ترحيلات الخزنة (`add_safe_transfer`).\n")
        f.write("   - اختبار إقفال الوردية ومطابقة العجز والزيادة (`record_shift_closing`).\n\n")

        f.write("3. **Operational CSRF & Session Security (`tests/test_csrf_security.py`)**:\n")
        f.write("   - اختبار استثناء شاشات الدخول التأسيسية لإنشاء الجلسة.\n")
        f.write("   - اختبار إرسال Token عبر حقول النماذج المخفية (Form Data).\n")
        f.write("   - اختبار إرسال Token عبر ترويسة الطلب `X-CSRFToken`.\n")
        f.write("   - اختبار إرسال Token داخل حمولة JSON.\n")
        f.write("   - اختبار الرفض الحاسم للطلبات المزورة ذات المصدر الخارجي (Origin Forgery -> 403 Forbidden).\n")
        f.write("   - اختبار توافق بيئة سطح المكتب WebView على النطاق المحلي.\n\n")

        f.write("4. **Audit & Regression Suite (`tests/test_audit_suite.py`)**:\n")
        f.write("   - فحص جميع نقاط الأمان الـ 20 المقررة في تقرير المراجعة الشامل.\n")
        f.write("   - التحقق من تكامل الذكاء الاصطناعي والإحصائيات التنفيذية وحصانة المسارات الحساسة.\n")

    print(f"\nتم توثيق النتائج بنجاح في: {report_path}")
    return 0 if overall_ok else 1


if __name__ == '__main__':
    sys.exit(run_all_tests())
