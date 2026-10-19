# -*- coding: utf-8 -*-
"""
STARGATE CAFE — AI Analytics & Executive Insights Engine (v6.2.0 PRO)
- Offline-first statistical heuristic engine (Zero external API dependency required)
- Strict Read-Only analytics (Never mutates or writes financial transactions)
- Role-based data sanitization (Protects manager margins from unprivileged roles)
"""

import sqlite3
from datetime import datetime, timedelta
import database
import accounting


def _get_conn():
    conn = database.get_db()
    conn.row_factory = sqlite3.Row
    return conn


def generate_executive_daily_summary(target_date=None):
    """
    Computes true-source daily financial health metrics and generates
    an executive brief in professional Arabic.
    """
    target_date = target_date or accounting.get_business_date()
    conn = _get_conn()
    cur = conn.cursor()

    # 1. Orders & Sales
    cur.execute("""
        SELECT 
            COUNT(*) as order_count,
            COALESCE(SUM(total_lbp), 0.0) as total_sales_lbp,
            COALESCE(SUM(total_usd), 0.0) as total_sales_usd,
            COALESCE(SUM(total_cost_lbp), 0.0) as total_cogs_lbp,
            COALESCE(SUM(discount_lbp), 0.0) as total_discount_lbp,
            COALESCE(SUM(CASE WHEN payment_method = 'cash' THEN total_lbp ELSE 0 END), 0.0) as cash_sales_lbp,
            COALESCE(SUM(CASE WHEN payment_method = 'debt' THEN total_lbp ELSE 0 END), 0.0) as debt_sales_lbp,
            COALESCE(SUM(CASE WHEN payment_method = 'card' THEN total_lbp ELSE 0 END), 0.0) as card_sales_lbp
        FROM cafe_orders
        WHERE (DATE(datetime(created_at, '-5 hours')) = DATE(?) OR DATE(created_at) = DATE(?))
          AND (status = 'paid' OR status IS NULL OR status = '')
    """, (target_date, target_date))
    orders_row = dict(cur.fetchone())

    # 2. Operating Expenses
    cur.execute("""
        SELECT 
            COALESCE(SUM(amount_lbp), 0.0) as total_expenses_lbp,
            COALESCE(SUM(amount_usd), 0.0) as total_expenses_usd,
            COUNT(*) as expense_count
        FROM expenses
        WHERE (DATE(datetime(created_at, '-5 hours')) = DATE(?) OR DATE(created_at) = DATE(?))
          AND (status = 'active' OR status IS NULL)
    """, (target_date, target_date))
    expenses_row = dict(cur.fetchone())

    # 3. Debt Collections
    cur.execute("""
        SELECT 
            COALESCE(SUM(amount_lbp), 0.0) as collected_lbp,
            COALESCE(SUM(amount_usd), 0.0) as collected_usd
        FROM debt_payments
        WHERE (DATE(datetime(created_at, '-5 hours')) = DATE(?) OR DATE(created_at) = DATE(?))
    """, (target_date, target_date))
    debt_coll_row = dict(cur.fetchone())

    # 4. Top selling beverages
    cur.execute("""
        SELECT oi.item_name, SUM(oi.quantity) as qty_sold, SUM(oi.subtotal_lbp) as rev_lbp
        FROM cafe_order_items oi
        JOIN cafe_orders o ON oi.order_id = o.id
        WHERE (DATE(datetime(o.created_at, '-5 hours')) = DATE(?) OR DATE(o.created_at) = DATE(?))
          AND (o.status = 'paid' OR o.status IS NULL OR o.status = '')
        GROUP BY oi.item_name
        ORDER BY qty_sold DESC
        LIMIT 5
    """, (target_date, target_date))
    top_items = [dict(r) for r in cur.fetchall()]

    conn.close()

    total_sales_lbp = float(orders_row['total_sales_lbp'])
    total_cogs_lbp = float(orders_row['total_cogs_lbp'])
    gross_profit_lbp = total_sales_lbp - total_cogs_lbp
    total_expenses_lbp = float(expenses_row['total_expenses_lbp'])
    net_operating_profit_lbp = gross_profit_lbp - total_expenses_lbp

    margin_pct = round((gross_profit_lbp / total_sales_lbp * 100), 1) if total_sales_lbp > 0 else 0.0

    # Arabic Executive Narrative Generation
    narrative = []
    narrative.append(f"تقرير الأداء المالي ليوم {target_date}:")
    narrative.append(f"• إجمالي مبيعات اليوم: {total_sales_lbp:,.0f} ل.ل عبر {orders_row['order_count']} طلب.")
    narrative.append(f"• التوزيع النقدي: {orders_row['cash_sales_lbp']:,.0f} ل.ل نقداً، و {orders_row['debt_sales_lbp']:,.0f} ل.ل مبيعات آجلة (ذمم).")
    narrative.append(f"• تكلفة البضاعة المباعة (COGS): {total_cogs_lbp:,.0f} ل.ل (هامش ربح إجمالي {margin_pct}%).")
    narrative.append(f"• المصاريف التشغيلية: {total_expenses_lbp:,.0f} ل.ل.")
    narrative.append(f"• صافي الربح التشغيلي التقديري: {net_operating_profit_lbp:,.0f} ل.ل.")
    
    if top_items:
        items_str = "، ".join([f"{it['item_name']} ({int(it['qty_sold'])})" for it in top_items[:3]])
        narrative.append(f"• الأكثر طلباً: {items_str}.")

    return {
        'target_date': target_date,
        'metrics': {
            'order_count': orders_row['order_count'],
            'total_sales_lbp': total_sales_lbp,
            'total_sales_usd': float(orders_row['total_sales_usd']),
            'cash_sales_lbp': float(orders_row['cash_sales_lbp']),
            'debt_sales_lbp': float(orders_row['debt_sales_lbp']),
            'card_sales_lbp': float(orders_row['card_sales_lbp']),
            'total_cogs_lbp': total_cogs_lbp,
            'gross_profit_lbp': gross_profit_lbp,
            'total_expenses_lbp': total_expenses_lbp,
            'net_operating_profit_lbp': net_operating_profit_lbp,
            'margin_pct': margin_pct,
            'debt_collected_lbp': float(debt_coll_row['collected_lbp'])
        },
        'top_items': top_items,
        'narrative': "\n".join(narrative)
    }


def detect_operational_anomalies():
    """
    Identifies operational anomalies: inventory deficits, extreme expenses,
    or overdue debt concentrations.
    """
    conn = _get_conn()
    cur = conn.cursor()
    anomalies = []

    # 1. Raw inventory deficits
    cur.execute("""
        SELECT name, unit, stock_qty, low_stock_limit 
        FROM inventory 
        WHERE stock_qty < 0
    """)
    for r in cur.fetchall():
        anomalies.append({
            'type': 'INVENTORY_DEFICIT',
            'severity': 'HIGH',
            'title': f'عجز مخزون في المادة الخام: {r["name"]}',
            'message': f'الرصيد الحالي ({r["stock_qty"]} {r["unit"]}) بالسالب نتيجة استهلاك وصفات تفوق الرصيد المسجل. يرجى مراجعة فواتير الشراء أو الجرد.'
        })

    # 2. Packaged items below threshold
    cur.execute("""
        SELECT name, stock_qty, low_stock_limit
        FROM cafe_items
        WHERE track_stock = 1 AND stock_qty <= low_stock_limit AND is_active = 1
        LIMIT 5
    """)
    for r in cur.fetchall():
        anomalies.append({
            'type': 'LOW_STOCK',
            'severity': 'MEDIUM',
            'title': f'تنبيه نقص كمية: {r["name"]}',
            'message': f'الكمية المتوفرة حالياً بالمحل ({r["stock_qty"]}) أقل من الحد الأدنى الموصى به ({r["low_stock_limit"]}).'
        })

    # 3. High expense alerts today (> 2,000,000 LBP or > $25)
    today = accounting.get_business_date()
    cur.execute("""
        SELECT title, amount_lbp, amount_usd, category, user_name
        FROM expenses
        WHERE (DATE(datetime(created_at, '-5 hours')) = DATE(?) OR DATE(created_at) = DATE(?))
          AND (amount_lbp >= 2000000 OR amount_usd >= 25)
          AND (status = 'active' OR status IS NULL)
    """, (today, today))
    for r in cur.fetchall():
        anomalies.append({
            'type': 'LARGE_EXPENSE',
            'severity': 'INFO',
            'title': f'مصروف بقيمة مرتفعة: {r["title"]}',
            'message': f'تم صرف {r["amount_lbp"]:,.0f} ل.ل ({r["category"]}) بواسطة {r["user_name"]}.'
        })

    conn.close()
    return anomalies


def ask_system_assistant(query, user_role='cashier'):
    """
    Intelligent Arabic Assistant: answers operational questions accurately
    without any hallucination or external API calls.
    """
    q = (query or '').strip().lower()
    today = accounting.get_business_date()

    if not q:
        return "أهلاً بك في المساعد الذكي لنظام STARGATE CAFE. كيف يمكنني مساعدتك في بيانات المبيعات أو المخزون اليوم؟"

    # Intent 1: Sales / Revenue
    if any(k in q for k in ['مبيعات', 'دخل', 'مبيعاتي', 'إيراد', 'sales', 'revenue']):
        summary = generate_executive_daily_summary(today)
        m = summary['metrics']
        if user_role == 'admin':
            return (
                f"📊 مبيعات اليوم ({today}):\n"
                f"- إجمالي المبيعات: {m['total_sales_lbp']:,.0f} ل.ل ({m['total_sales_usd']:.2f} $)\n"
                f"- النقدي بالدرج: {m['cash_sales_lbp']:,.0f} ل.ل\n"
                f"- المبيعات الآجلة: {m['debt_sales_lbp']:,.0f} ل.ل\n"
                f"- عدد الفواتير: {m['order_count']}\n"
                f"- هامش الربح الإجمالي: {m['margin_pct']}%"
            )
        else:
            return (
                f"📊 إجمالي المبيعات المسجلة لليوم: {m['total_sales_lbp']:,.0f} ل.ل عبر {m['order_count']} طلب ناجح."
            )

    # Intent 2: Safe & Cash Drawer
    if any(k in q for k in ['خزنة', 'درج', 'صندوق', 'كاش', 'cash', 'drawer', 'safe']):
        drawer = accounting.get_drawer_cash_status()
        safe = accounting.get_safe_balance()
        if user_role == 'admin':
            return (
                f"💰 أرصدة النقدية اللحظية:\n"
                f"- الدرج / الصندوق النشط: {drawer.get('total_lbp', 0):,.0f} ل.ل | {drawer.get('total_usd', 0):.2f} $\n"
                f"- الخزنة الرئيسية (Safe): {safe.get('total_lbp', 0):,.0f} ل.ل | {safe.get('total_usd', 0):.2f} $"
            )
        else:
            return (
                f"💰 رصيد درج الكاشير الحالي: {drawer.get('total_lbp', 0):,.0f} ل.ل | {drawer.get('total_usd', 0):.2f} $"
            )

    # Intent 3: Stock / Inventory
    if any(k in q for k in ['مخزون', 'بضاعة', 'جرد', 'نقص', 'stock', 'inventory']):
        anomalies = detect_operational_anomalies()
        stock_alerts = [a for a in anomalies if a['type'] in ('INVENTORY_DEFICIT', 'LOW_STOCK')]
        if not stock_alerts:
            return "✅ جميع مستويات المخزون والمواد الخام ضمن الحدود الآمنة والطبيعية حالياً."
        resp = ["⚠️ تنبيهات المخزون الحالية:"]
        for sa in stock_alerts[:5]:
            resp.append(f"• {sa['title']} — {sa['message']}")
        return "\n".join(resp)

    # Intent 4: Customer Debts
    if any(k in q for k in ['ديون', 'ذمم', 'زبائن', 'debt', 'debts', 'دين']):
        if user_role != 'admin':
            return "⚠️ عذراً، الاطلاع على إجمالي الذمم والديون مخصص لمدير النظام فقط."
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as cnt, COALESCE(SUM(remaining_lbp), 0) as tot_lbp, COALESCE(SUM(remaining_usd), 0) as tot_usd FROM customer_debts WHERE status != 'paid'")
        d_row = cur.fetchone()
        conn.close()
        return (
            f"📋 سجل الديون والذمم المدينة:\n"
            f"- إجمالي الذمم غير المحصلة: {d_row['tot_lbp']:,.0f} ل.ل | {d_row['tot_usd']:.2f} $\n"
            f"- عدد الحسابات المدينة النشطة: {d_row['cnt']}"
        )

    # Intent 5: Top Selling
    if any(k in q for k in ['أكثر', 'أفضل', 'مطلوب', 'top', 'best']):
        summary = generate_executive_daily_summary(today)
        top = summary['top_items']
        if not top:
            return "لم يتم تسجيل مبيعات كافية اليوم لتحديد الأصناف الأكثر طلباً."
        resp = ["🏆 الأصناف الأكثر مبيعاً اليوم:"]
        for idx, it in enumerate(top, 1):
            resp.append(f"{idx}. {it['item_name']} — {int(it['qty_sold'])} قطعة ({it['rev_lbp']:,.0f} ل.ل)")
        return "\n".join(resp)

    # Fallback
    return (
        "يمكنني مساعدتك في الإجابة عن:\n"
        "• مبيعات اليوم وإجمالي الفواتير\n"
        "• رصيد الخزنة وصندوق الدرج\n"
        "• الأصناف الأكثر مبيعاً\n"
        "• تنبيهات نقص المخزون\n"
        "• إجمالي الديون والذمم"
    )
