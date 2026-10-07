import sys
import os

acc_path = r'd:\STARGATE\stargate_cafe_source\accounting.py'
with open(acc_path, 'r', encoding='utf-8') as f:
    acc_code = f.read()

# 1. Update get_orders
old_get_orders = """def get_orders(target_date=None, limit=100, employee_id=None):
    conn = get_db()
    cursor = conn.cursor()
    query = \"\"\"
    SELECT 
        o.*,
        COUNT(i.id) as items_count,
        COALESCE(SUM(i.quantity), 0) as total_cups,
        GROUP_CONCAT(i.item_name || ' (x' || i.quantity || ')', ' + ') as items_summary
    FROM cafe_orders o
    LEFT JOIN cafe_order_items i ON o.id = i.order_id
    WHERE (o.status = 'paid' OR o.status IS NULL OR o.status = '')
    \"\"\"
    params = []
    if target_date:
        query += \" AND DATE(datetime(o.created_at, '-5 hours')) = DATE(?)\"
        params.append(target_date)
    if employee_id is not None:
        query += \" AND o.employee_id = ?\"
        params.append(employee_id)"""

new_get_orders = """def get_orders(target_date=None, limit=5000, employee_id=None):
    conn = get_db()
    cursor = conn.cursor()
    query = \"\"\"
    SELECT 
        o.*,
        COUNT(i.id) as items_count,
        COALESCE(SUM(i.quantity), 0) as total_cups,
        GROUP_CONCAT(i.item_name || ' (x' || i.quantity || ')', ' + ') as items_summary
    FROM cafe_orders o
    LEFT JOIN cafe_order_items i ON o.id = i.order_id
    WHERE (o.status = 'paid' OR o.status IS NULL OR o.status = '')
    \"\"\"
    params = []
    if target_date:
        query += \" AND (DATE(datetime(o.created_at, '-5 hours')) = DATE(?) OR DATE(o.created_at) = DATE(?))\"
        params.extend([target_date, target_date])
    if employee_id is not None:
        query += \" AND (o.employee_id = ? OR o.employee_id IS NULL)\"
        params.append(employee_id)"""

assert old_get_orders in acc_code, "old_get_orders not found"
acc_code = acc_code.replace(old_get_orders, new_get_orders, 1)
print("1. Replaced get_orders")

# 2. Update log_single_pc_click
old_pc_click = """def log_single_pc_click(price_lbp=None, note='استخدام كمبيوتر GAMING'):
    settings = get_settings()
    rate = float(settings.get('exchange_rate') or 89500.0)
    p_lbp = float(price_lbp) if price_lbp else float(settings.get('pc_price_per_click_lbp') or 100000.0)
    p_usd = round(p_lbp / rate, 2) if rate > 0 else 0.0

    # Record as instant order so it integrates seamlessly in sales & receipts
    items_list = [{
        'name': 'كمبيوتر ألعاب GAMING 🎮',
        'price_lbp': p_lbp,
        'quantity': 1,
        'item_type': 'gaming',
        'item_id': None
    }]
    success, res = create_order({'customer_name': 'لاعب GAMING', 'notes': note}, items_list)
    return success, res"""

new_pc_click = """def log_single_pc_click(price_lbp=None, note='استخدام كمبيوتر GAMING', employee_id=None, employee_name=None):
    settings = get_settings()
    rate = float(settings.get('exchange_rate') or 89500.0)
    p_lbp = float(price_lbp) if price_lbp else float(settings.get('pc_price_per_click_lbp') or 100000.0)
    p_usd = round(p_lbp / rate, 2) if rate > 0 else 0.0

    # Record as instant order so it integrates seamlessly in sales & receipts
    items_list = [{
        'name': 'كمبيوتر ألعاب GAMING 🎮',
        'price_lbp': p_lbp,
        'quantity': 1,
        'item_type': 'gaming',
        'item_id': None
    }]
    order_data = {
        'customer_name': 'لاعب GAMING',
        'notes': note,
        'payment_method': 'cash',
        'employee_id': employee_id,
        'employee_name': employee_name or 'كاشير'
    }
    success, res = create_order(order_data, items_list)
    return success, res"""

assert old_pc_click in acc_code, "old_pc_click not found"
acc_code = acc_code.replace(old_pc_click, new_pc_click, 1)
print("2. Replaced log_single_pc_click")

with open(acc_path, 'w', encoding='utf-8') as f:
    f.write(acc_code)

print("Saved accounting.py successfully.")
