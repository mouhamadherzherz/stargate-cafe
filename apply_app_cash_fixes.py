import sys
import os

app_path = r'd:\STARGATE\stargate_cafe_source\app.py'
with open(app_path, 'r', encoding='utf-8') as f:
    app_code = f.read()

# 1. Update ensure_default_session
old_default_session = """@app.before_request
def ensure_default_session():
    public_endpoints = ['employee_login', 'admin_login', 'static', 'favicon']
    if request.endpoint and any(ep in (request.endpoint or '') for ep in public_endpoints):
        return
    if 'employee_id' not in session and not session.get('admin_authenticated'):
        if request.endpoint and request.endpoint.startswith('api_'):
            pass
        elif request.endpoint and request.endpoint not in ('employee_login', 'admin_login'):
            pass"""

new_default_session = """@app.before_request
def ensure_default_session():
    public_endpoints = ['employee_login', 'admin_login', 'static', 'favicon']
    if request.endpoint and any(ep in (request.endpoint or '') for ep in public_endpoints):
        return
    if 'employee_id' not in session or not session.get('employee_id'):
        if session.get('admin_authenticated') or session.get('is_admin'):
            session['employee_id'] = session.get('user_id') or 1
            session['employee_name'] = session.get('user_name') or 'المدير العام'
            session['employee_role'] = 'admin'
        else:
            try:
                conn = database.get_db()
                c = conn.cursor()
                c.execute("SELECT id, name, role FROM employees WHERE role = 'cashier' AND is_active = 1 ORDER BY id ASC LIMIT 1")
                row = c.fetchone()
                if not row:
                    c.execute("SELECT id, name, role FROM employees WHERE is_active = 1 ORDER BY id ASC LIMIT 1")
                    row = c.fetchone()
                conn.close()
                if row:
                    session['employee_id'] = row['id']
                    session['employee_name'] = row['name']
                    session['employee_role'] = row['role']
                else:
                    session['employee_id'] = 1
                    session['employee_name'] = 'كاشير'
                    session['employee_role'] = 'cashier'
            except Exception:
                session['employee_id'] = 1
                session['employee_name'] = 'كاشير'
                session['employee_role'] = 'cashier'"""

assert old_default_session in app_code, "old_default_session not found"
app_code = app_code.replace(old_default_session, new_default_session, 1)
print("1. Replaced ensure_default_session")

# 2. Update order_create employee resolution
old_order_create_emp = """        order_data = {
            'customer_name': customer_name,
            'notes': notes,
            'payment_method': payment_method,
            'phone': phone,
            'employee_id': session.get('employee_id'),
            'employee_name': session.get('employee_name', 'كاشير')
        }"""

new_order_create_emp = """        emp_id = session.get('employee_id')
        emp_name = session.get('employee_name')
        if not emp_id:
            try:
                conn = database.get_db()
                r_emp = conn.execute("SELECT id, name FROM employees WHERE role='cashier' AND is_active=1 ORDER BY id ASC LIMIT 1").fetchone()
                if not r_emp:
                    r_emp = conn.execute("SELECT id, name FROM employees WHERE is_active=1 ORDER BY id ASC LIMIT 1").fetchone()
                conn.close()
                if r_emp:
                    emp_id = r_emp['id']
                    emp_name = r_emp['name']
                else:
                    emp_id = 1
                    emp_name = 'كاشير'
            except Exception:
                emp_id = 1
                emp_name = 'كاشير'
            session['employee_id'] = emp_id
            session['employee_name'] = emp_name

        order_data = {
            'customer_name': customer_name,
            'notes': notes,
            'payment_method': payment_method,
            'phone': phone,
            'employee_id': emp_id,
            'employee_name': emp_name or 'كاشير'
        }"""

assert old_order_create_emp in app_code, "old_order_create_emp not found"
app_code = app_code.replace(old_order_create_emp, new_order_create_emp, 1)
print("2. Replaced order_create employee resolution")

# 3. Update employee_close_shift calculation
target_close_marker = "def employee_close_shift():"
assert target_close_marker in app_code, "employee_close_shift not found"

# Find the start of function
idx_start = app_code.find(target_close_marker)
# Find the line: if request.method == 'POST':
idx_post = app_code.find("if request.method == 'POST':", idx_start)
assert idx_post > idx_start, "if request.method == 'POST' not found after employee_close_shift"

old_shift_calc = app_code[idx_start:idx_post]

new_shift_calc = """def employee_close_shift():
    \"\"\"Close employee shift, calculate sales, reconcile cash drawer, and handover to next employee.\"\"\"
    emp_id = session.get('employee_id')
    emp_name = session.get('employee_name')
    if not emp_name:
        emp_name = 'كاشير'

    today_str = accounting.get_business_date()
    settings = accounting.get_settings()
    exchange_rate = float(settings.get('exchange_rate') or 89500.0)
    company_name = settings.get('company_name', 'STARGATE CAFE')

    # 1. مبيعات الموظف والدرج لليوم (شاملة كل الطلبات بدون استثناء وبدون أي حد)
    conn = accounting.get_db()
    c = conn.cursor()

    if emp_id:
        c.execute(\"\"\"
            SELECT o.* 
            FROM cafe_orders o
            WHERE (DATE(datetime(o.created_at, '-5 hours')) = DATE(?) OR DATE(o.created_at) = DATE(?))
              AND (o.status = 'paid' OR o.status IS NULL OR o.status = '')
              AND (o.employee_id = ? OR o.employee_id IS NULL)
            ORDER BY o.id DESC
        \"\"\", (today_str, today_str, emp_id))
    else:
        c.execute(\"\"\"
            SELECT o.* 
            FROM cafe_orders o
            WHERE (DATE(datetime(o.created_at, '-5 hours')) = DATE(?) OR DATE(o.created_at) = DATE(?))
              AND (o.status = 'paid' OR o.status IS NULL OR o.status = '')
            ORDER BY o.id DESC
        \"\"\", (today_str, today_str))
    emp_orders = [dict(r) for r in c.fetchall()]

    total_sales_lbp = sum(float(o.get('total_lbp', 0)) for o in emp_orders)
    total_sales_usd = sum(float(o.get('total_usd', 0)) for o in emp_orders)
    cash_sales_lbp = sum(float(o.get('total_lbp', 0)) for o in emp_orders if o.get('payment_method') == 'cash')
    debt_sales_lbp = sum(float(o.get('total_lbp', 0)) for o in emp_orders if o.get('payment_method') == 'debt')

    # 2. حركة الكاش الشاملة للصندوق (تحصيل ديون، مصاريف الدرج، تحويلات الخزنة السابقة، عهدة افتتاحية)
    # سدادات ديون مستلمة اليوم
    if emp_id:
        c.execute(\"\"\"
            SELECT COALESCE(SUM(amount_lbp), 0)
            FROM debt_payments
            WHERE (DATE(datetime(created_at, '-5 hours')) = DATE(?) OR DATE(created_at) = DATE(?))
              AND (employee_id = ? OR employee_id IS NULL)
        \"\"\", (today_str, today_str, emp_id))
    else:
        c.execute(\"\"\"
            SELECT COALESCE(SUM(amount_lbp), 0)
            FROM debt_payments
            WHERE (DATE(datetime(created_at, '-5 hours')) = DATE(?) OR DATE(created_at) = DATE(?))
        \"\"\", (today_str, today_str))
    debt_collected_lbp = float(c.fetchone()[0] or 0.0)

    # مصاريف مدفوعة من الدرج اليوم
    if emp_id:
        c.execute(\"\"\"
            SELECT COALESCE(SUM(amount_lbp), 0)
            FROM expenses
            WHERE (DATE(datetime(created_at, '-5 hours')) = DATE(?) OR DATE(created_at) = DATE(?))
              AND (source != 'safe' OR source IS NULL)
              AND (employee_id = ? OR employee_id IS NULL)
        \"\"\", (today_str, today_str, emp_id))
    else:
        c.execute(\"\"\"
            SELECT COALESCE(SUM(amount_lbp), 0)
            FROM expenses
            WHERE (DATE(datetime(created_at, '-5 hours')) = DATE(?) OR DATE(created_at) = DATE(?))
              AND (source != 'safe' OR source IS NULL)
        \"\"\", (today_str, today_str))
    shift_expenses_lbp = float(c.fetchone()[0] or 0.0)

    # مبالغ تم توريدها للخزنة مسبقاً خلال الوردية
    if emp_id:
        c.execute(\"\"\"
            SELECT COALESCE(SUM(amount_lbp), 0)
            FROM safe_transfers
            WHERE (DATE(datetime(created_at, '-5 hours')) = DATE(?) OR DATE(created_at) = DATE(?) OR note LIKE ?)
              AND operation_type = 'deposit'
              AND (source != 'external' OR source IS NULL)
              AND (employee_id = ? OR employee_id IS NULL)
        \"\"\", (today_str, today_str, f"%{today_str}%", emp_id))
    else:
        c.execute(\"\"\"
            SELECT COALESCE(SUM(amount_lbp), 0)
            FROM safe_transfers
            WHERE (DATE(datetime(created_at, '-5 hours')) = DATE(?) OR DATE(created_at) = DATE(?) OR note LIKE ?)
              AND operation_type = 'deposit'
              AND (source != 'external' OR source IS NULL)
        \"\"\", (today_str, today_str, f"%{today_str}%"))
    prior_safe_transfers_lbp = float(c.fetchone()[0] or 0.0)
    conn.close()

    # عهدة افتتاحية للدرج إن وجدت (أو المتبقي النقدي من الأمس في الصندوق تلقائياً)
    drawer_stat = accounting.get_drawer_cash_status()
    past_untransferred = float(drawer_stat.get('past_untransferred_lbp') or 0.0)
    opening_float = float(session.get('opening_cash_lbp') or session.get('handover_actual_cash') or past_untransferred or 0.0)

    # رصيد الكاش المتوقع في الدرج بدقة متناهية
    # الكاش المتوقع = (عهدة افتتاحية + مبيعات كاش + تحصيل ديون) - (مصاريف الصندوق + توريدات الخزنة السابقة)
    expected_cash_lbp = max(0.0, opening_float + cash_sales_lbp + debt_collected_lbp - shift_expenses_lbp - prior_safe_transfers_lbp)

    """

app_code = app_code[:idx_start] + new_shift_calc + app_code[idx_post:]
print("3. Replaced employee_close_shift calculation")

with open(app_path, 'w', encoding='utf-8') as f:
    f.write(app_code)

print("Saved app.py successfully.")
