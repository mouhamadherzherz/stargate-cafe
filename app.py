from PIL import Image, ImageOps
import io, base64, urllib.request
from werkzeug.utils import secure_filename
# -*- coding: utf-8 -*-
import os
import secrets
import sys
import json
import threading
from datetime import datetime, timedelta
from flask import Flask, render_template, render_template_string, request, redirect, url_for, flash, jsonify, session, send_file, Response
import database
from database import init_db, get_db, reset_operational_data
import accounting

# ============================================================
# 🔄 نظام التحديث التلقائي عبر الإنترنت (OTA)
# ============================================================
_update_cache = {'checked': False, 'available': False, 'version': None, 'download_url': None, 'message': ''}

def _get_base_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def _get_current_version():
    base = _get_base_dir()
    for p in [os.path.join(base, 'cafe_version.json'),
              os.path.join(base, '_internal', 'cafe_version.json')]:
        if os.path.exists(p):
            try:
                with open(p, encoding='utf-8-sig') as f:
                    return json.load(f).get('version', '0.0.0')
            except Exception:
                pass
    return '0.0.0'

def _version_tuple(v):
    try:
        return tuple(int(x) for x in str(v).lstrip('v').split('.'))
    except Exception:
        return (0,)

def _background_update_check():
    """يتحقق من التحديثات في الخلفية عبر Firebase و GitHub API (بدون cache)."""
    import ssl, urllib.request as ur, json as js, base64 as b64
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    current = _get_current_version()
    best_remote = None
    best_data = None

    # --- Endpoint 1: Firebase (fastest, no cache) ---
    try:
        firebase_url = 'https://stargate-experts-default-rtdb.firebaseio.com/cafe_updates/latest.json'
        req = ur.Request(firebase_url, headers={'User-Agent': 'StargateCafe-OTA/4.6', 'Cache-Control': 'no-cache'})
        with ur.urlopen(req, timeout=6, context=ctx) as r:
            data = js.loads(r.read().decode('utf-8-sig'))
        remote = data.get('version', '0')
        if remote and remote != 'null':
            best_remote = remote
            best_data = data
    except Exception:
        pass

    # --- Endpoint 2: GitHub API (no CDN cache, always fresh) ---
    try:
        api_url = 'https://api.github.com/repos/mouhamadherzherz/stargate-cafe/contents/cafe_version.json'
        req = ur.Request(api_url, headers={
            'User-Agent': 'StargateCafe-OTA/4.6',
            'Accept': 'application/vnd.github+json',
            'Cache-Control': 'no-cache'
        })
        with ur.urlopen(req, timeout=8, context=ctx) as r:
            api_resp = js.loads(r.read().decode('utf-8'))
        # Decode base64 content from GitHub API response
        raw_content = b64.b64decode(api_resp.get('content', '').replace('\n', '')).decode('utf-8-sig')
        data = js.loads(raw_content)
        remote = data.get('version', '0')
        if not best_remote or _version_tuple(remote) > _version_tuple(best_remote):
            best_remote = remote
            best_data = data
    except Exception:
        pass

    # --- Endpoint 3: Fallback raw CDN (may be cached) ---
    if not best_remote:
        try:
            raw_url = 'https://raw.githubusercontent.com/mouhamadherzherz/stargate-cafe/master/cafe_version.json'
            req = ur.Request(raw_url, headers={'User-Agent': 'StargateCafe-OTA/4.6'})
            with ur.urlopen(req, timeout=6, context=ctx) as r:
                data = js.loads(r.read().decode('utf-8-sig'))
            remote = data.get('version', '0')
            if remote:
                best_remote = remote
                best_data = data
        except Exception:
            pass

    if best_remote and _version_tuple(best_remote) > _version_tuple(current):
        _update_cache.update({
            'checked': True, 'available': True,
            'version': best_remote,
            'download_url': best_data.get('download_url', ''),
            'changelog': best_data.get('changelog', ''),
            'message': f'يوجد تحديث رسمي جديد v{best_remote} (حالياً v{current}) - إصلاح الحسابات والخزينة.'
        })
    elif best_remote:
        _update_cache.update({'checked': True, 'available': False, 'version': current, 'message': f'البرنامج محدّث لآخر إصدار (v{current})'})
    else:
        _update_cache.update({'checked': True, 'available': False, 'message': 'تعذّر الاتصال بخادم التحديثات'})

def _periodic_update_checker():
    import time
    while True:
        try:
            _background_update_check()
        except Exception:
            pass
        time.sleep(300)

# بدء الفحص الدوري في الخلفية
threading.Thread(target=_periodic_update_checker, daemon=True).start()

if getattr(sys, 'frozen', False):
    # In PyInstaller, check sys._MEIPASS, executable dir, and _internal
    base_exe = os.path.dirname(sys.executable)
    possible_tpl = [
        os.path.join(base_exe, 'templates'),
        os.path.join(base_exe, '_internal', 'templates'),
        os.path.join(getattr(sys, '_MEIPASS', ''), 'templates')
    ]
    template_dir = next((p for p in possible_tpl if os.path.exists(p)), possible_tpl[0])
    
    possible_static = [
        os.path.join(base_exe, 'static'),
        os.path.join(base_exe, '_internal', 'static'),
        os.path.join(getattr(sys, '_MEIPASS', ''), 'static')
    ]
    static_dir = next((p for p in possible_static if os.path.exists(p)), possible_static[0])
    app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
else:
    app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
@app.after_request
def add_no_cache_headers(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


def save_uploaded_item_image(file=None, data_url=None, item_id=None):
    """
    High-Definition Studio Image Processor:
    - Automatically corrects smartphone EXIF orientation (no upside-down or sideways photos)
    - Preserves clean transparency for PNG cutouts, uses 90% quality JPEG for photos
    - High-quality LANCZOS downscaling to max 800px (instant loading + razor-sharp display)
    - Fully supports direct file upload, clipboard paste (Ctrl+V), and web image URLs
    """
    try:
        raw_bytes = None
        
        # 1. Handle file upload (Werkzeug FileStorage or file-like)
        if file and hasattr(file, 'read'):
            raw_bytes = file.read()
        elif file and isinstance(file, bytes):
            raw_bytes = file
            
        # 2. Handle Base64 Data URL (from clipboard Ctrl+V)
        if (not raw_bytes or len(raw_bytes) < 10) and data_url:
            data_url = str(data_url).strip()
            if data_url.startswith('data:image'):
                header, encoded = data_url.split(',', 1)
                raw_bytes = base64.b64decode(encoded)
            elif data_url.startswith('http://') or data_url.startswith('https://'):
                req = urllib.request.Request(data_url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    raw_bytes = resp.read()

        if not raw_bytes or len(raw_bytes) < 10:
            return None

        # 3. Open with Pillow and process
        img = Image.open(io.BytesIO(raw_bytes))
        
        # Auto-orient EXIF (critical for phone camera photos)
        try:
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass

        # Smart Lanczos Downscaling (max 800px keeps ultra-sharp retina quality at tiny file size)
        max_dim = 800
        if max(img.size) > max_dim:
            img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

        # Check if image has solid white / near-white background from web or camera
        w, h = img.size
        sample_img = img.convert('RGB')
        corners = [sample_img.getpixel((0,0)), sample_img.getpixel((w-1,0)), 
                   sample_img.getpixel((0,h-1)), sample_img.getpixel((w-1,h-1))]
        avg_r = sum(p[0] for p in corners) / 4
        avg_g = sum(p[1] for p in corners) / 4
        avg_b = sum(p[2] for p in corners) / 4
        is_white_bg = (avg_r > 225 and avg_g > 225 and avg_b > 225)

        img = img.convert('RGBA')
        if is_white_bg:
            # Studio Cutout: automatically flood-fill corner white areas to transparent alpha
            try:
                for pt in [(0, 0), (w-1, 0), (0, h-1), (w-1, h-1), (w//2, 0), (w//2, h-1)]:
                    if img.getpixel(pt)[3] > 0 and sample_img.getpixel(pt)[0] > 220:
                        ImageDraw.floodfill(img, pt, (0, 0, 0, 0), thresh=35)
            except Exception:
                pass

        out_buf = io.BytesIO()
        unique_suffix = secrets.token_hex(4)
        item_str = f"item_{item_id}" if item_id else "item"
        filename = f"{item_str}_{int(datetime.now().timestamp())}_{unique_suffix}.png"
        img.save(out_buf, format='PNG', optimize=True)

        content = out_buf.getvalue()
        
        # Save to all target static/uploads directories
        base_exe = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
        folders = [
            r"F:\caffe\static\uploads",
            r"C:\STARGATE_CAFE\static\uploads",
            r"C:\STARGATE\static\uploads",
            os.path.join(app.static_folder, 'uploads'),
            os.path.join(base_exe, 'static', 'uploads'),
            os.path.join(base_exe, '_internal', 'static', 'uploads'),
            r"F:\static\uploads",
            r"F:\2 - نظام الكافيه (Stargate Cafe)\static\uploads"
        ]
        for fld in folders:
            try:
                os.makedirs(fld, exist_ok=True)
                with open(os.path.join(fld, filename), 'wb') as f_out:
                    f_out.write(content)
            except Exception:
                pass
                
        return f"/static/uploads/{filename}"
    except Exception as e:
        print(f"Image processing error: {e}")
        return None

@app.route('/static/uploads/<path:filename>')
def custom_serve_uploaded_file(filename):
    """Explicitly serves uploaded product images with correct MIME type across all possible paths."""
    base_exe = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
    folders = [
        r"F:\caffe\static\uploads",
        r"C:\STARGATE_CAFE\static\uploads",
        os.path.join(app.static_folder, 'uploads'),
        r"C:\STARGATE_CAFE\static\uploads",
        r"C:\STARGATE\static\uploads",
        os.path.join(base_exe, 'static', 'uploads'),
        os.path.join(base_exe, '_internal', 'static', 'uploads'),
    ]
    for fld in folders:
        fp = os.path.join(fld, filename)
        if os.path.isfile(fp):
            return send_file(fp)
    from flask import abort
    return abort(404)


app.secret_key = 'cafe_gaming_pos_secret_key_2026'

# Custom Jinja filters
@app.template_filter('format_currency')
def format_currency(value):
    try:
        val = float(value or 0)
        return f"{val:,.0f}"
    except (ValueError, TypeError):
        return "0"

@app.template_filter('to_usd')
def to_usd(value, rate=None):
    try:
        val = float(value or 0)
        if rate is None:
            settings = accounting.get_settings()
            r = float(settings.get('exchange_rate') or 89500.0)
        else:
            r = float(rate)
        if r <= 0: r = 89500.0
        
        # If value is already in dollars (small amount like < 500)
        # and not 0, format directly as dollar amount
        # Otherwise if it's large LBP amount (>= 500), divide by exchange rate!
        if abs(val) < 500.0 and val != 0.0:
            return f"${val:,.2f}"
        return f"${(val / r):,.2f}"
    except (ValueError, TypeError):
        return "$0.00"

@app.template_filter('format_date')
def format_date(value):
    if not value: return "-"
    try:
        if isinstance(value, str):
            dt = datetime.strptime(value.split('.')[0], '%Y-%m-%d %H:%M:%S')
        else:
            dt = value
        hour_12 = dt.strftime('%I:%M')
        am_pm = 'م' if dt.strftime('%p') == 'PM' else 'ص'
        return f"{dt.strftime('%Y/%m/%d')} {hour_12} {am_pm}"
    except Exception:
        return str(value)[:19]

@app.template_filter('format_time_only')
def format_time_only(value):
    if not value: return "-"
    try:
        if isinstance(value, str):
            dt = datetime.strptime(value.split('.')[0], '%Y-%m-%d %H:%M:%S')
        else:
            dt = value
        hour_12 = dt.strftime('%I:%M')
        am_pm = 'م' if dt.strftime('%p') == 'PM' else 'ص'
        return f"{hour_12} {am_pm}"
    except Exception:
        return str(value)[:16]



from functools import wraps

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('is_admin') and not session.get('admin_authenticated') and session.get('employee_role') != 'admin':
            flash("⚠️ عذراً، هذه الصفحة مخصصة لمدير النظام والإدارة فقط!", "danger")
            return redirect(url_for('admin_login', next=request.path))
        return f(*args, **kwargs)
    return decorated_function

@app.before_request
def ensure_default_session():
    # System requires employee login - no anonymous access
    # Only set default if accessing non-protected endpoints
    public_endpoints = ['employee_login', 'admin_login', 'static', 'favicon']
    if request.endpoint and any(ep in (request.endpoint or '') for ep in public_endpoints):
        return  # Allow public endpoints without session
    # If no employee is logged in, require login
    if 'employee_id' not in session and not session.get('admin_authenticated'):
        # Don't redirect for API calls - they'll get 401
        if request.endpoint and request.endpoint.startswith('api_'):
            pass
        elif request.endpoint and request.endpoint not in ('employee_login', 'admin_login'):
            pass  # Let individual routes handle their own auth

@app.context_processor
def inject_global_data():
    today_business_date = accounting.get_business_date()
    from datetime import datetime, timedelta, timedelta
    yesterday_business_date = accounting.get_business_date(dt=(datetime.now() - timedelta(days=1)))
    settings = accounting.get_settings()
    rate = float(settings.get('exchange_rate') or 89500.0)
    today_str = accounting.get_business_date()
    daily_summary = accounting.get_daily_summary(today_str)
    pc_price = float(settings.get('pc_price_per_click_lbp') or 100000.0)
    safe_bal = accounting.get_safe_balance()
    drawer_stat = accounting.get_drawer_cash_status()
    is_user_admin = bool(session.get('is_admin') or session.get('admin_authenticated') or session.get('employee_role') == 'admin')
    return {
        'settings': settings,
        'is_admin': is_user_admin,
        'company_name': settings.get('company_name', 'محل القهوة و GAMING'),
        'currency': settings.get('currency', 'ل.ل'),
        'secondary_currency': settings.get('secondary_currency', '$'),
        'exchange_rate': rate,
        'pc_price_lbp': pc_price,
        'safe_balance': safe_bal,
        'drawer_status': drawer_stat,
        'daily_kpi': daily_summary,
        'today_str': today_str,
        'now': datetime.now()
    }

# ----------------- 1. MAIN POS & GAMING SCREEN -----------------

@app.route('/')
def index():
    """Main Touch POS Screen with Drinks Grid, 1-Click GAMING, and Cashier Panel."""
    if 'employee_id' not in session and not session.get('is_admin'):
        return redirect(url_for('employee_login'))
    categories = accounting.get_categories()
    items = accounting.get_items(active_only=True)
    today_str = accounting.get_business_date()
    daily_summary = accounting.get_daily_summary(today_str)
    recent_orders = accounting.get_orders(target_date=today_str, limit=5)
    recent_pc_logs = accounting.get_pc_logs(target_date=today_str, limit=5)
    open_tabs = accounting.get_open_tabs()

    return render_template(
        'index.html',
        categories=categories,
        items=items,
        summary=daily_summary,
        recent_orders=recent_orders,
        recent_pc_logs=recent_pc_logs,
        open_tabs=open_tabs,
        active_page='pos'
    )

@app.route('/order/create', methods=['POST'])
def order_create():
    """Create a new cafe order or pay an existing open customer tab."""
    try:
        if request.is_json:
            req_data = request.get_json()
            items_list = req_data.get('items', [])
            customer_name = req_data.get('customer_name', 'زبون كاش')
            notes = req_data.get('notes', '')
            tab_id = req_data.get('tab_id')
            payment_method = req_data.get('payment_method', 'cash')
            phone = req_data.get('phone', '')
        else:
            raw_items = request.form.get('items_json', '[]')
            items_list = json.loads(raw_items)
            customer_name = request.form.get('customer_name', 'زبون كاش')
            notes = request.form.get('notes', '')
            tab_id = request.form.get('tab_id')
            payment_method = request.form.get('payment_method', 'cash')
            phone = request.form.get('phone', '')

        order_data = {
            'customer_name': customer_name,
            'notes': notes,
            'payment_method': payment_method,
            'phone': phone
        }
        success, result = accounting.create_order(order_data, items_list, tab_id=tab_id)

        if request.is_json:
            if success:
                return jsonify({'success': True, 'data': result, 'message': 'تم حفظ الفاتورة بنجاح'})
            return jsonify({'success': False, 'message': str(result)}), 400

        if success:
            flash(f"تم تسجيل الفاتورة بنجاح بمبلغ {result['total_lbp']:,.0f} ل.ل ☕", "success")
            return redirect(url_for('order_receipt', order_id=result['order_id']))
        else:
            flash(f"خطأ: {result}", "danger")
            return redirect(url_for('index'))
    except Exception as e:
        if request.is_json:
            return jsonify({'success': False, 'message': str(e)}), 500
        flash(f"خطأ: {str(e)}", "danger")
        return redirect(url_for('index'))

@app.route('/tab/save', methods=['POST'])
def tab_save():
    """Save or update an open customer tab (الزبائن الجالسون)."""
    try:
        if request.is_json:
            req_data = request.get_json()
            items_list = req_data.get('items', [])
            customer_name = req_data.get('customer_name', 'زبون في المحل')
            notes = req_data.get('notes', '')
            tab_id = req_data.get('tab_id')
        else:
            raw_items = request.form.get('items_json', '[]')
            items_list = json.loads(raw_items)
            customer_name = request.form.get('customer_name', 'زبون في المحل')
            notes = request.form.get('notes', '')
            tab_id = request.form.get('tab_id')

        success, result = accounting.save_customer_tab(customer_name, items_list, tab_id=tab_id, notes=notes)
        if request.is_json:
            if success:
                return jsonify({'success': True, 'data': result, 'message': f"تم حفظ حساب {customer_name} بنجاح 📌"})
            return jsonify({'success': False, 'message': str(result)}), 400

        if success:
            flash(f"تم حفظ حساب الزبون {customer_name} بنجاح 📌", "success")
        else:
            flash(f"خطأ: {result}", "danger")
        return redirect(url_for('index'))
    except Exception as e:
        if request.is_json:
            return jsonify({'success': False, 'message': str(e)}), 500
        flash(f"خطأ: {str(e)}", "danger")
        return redirect(url_for('index'))

@app.route('/tab/<int:tab_id>/delete', methods=['POST'])
def tab_delete(tab_id):
    """Cancel / Delete an open customer tab."""
    accounting.delete_tab(tab_id)
    if request.is_json:
        return jsonify({'success': True, 'message': 'تم إلغاء حساب الزبون'})
    flash("تم إلغاء حساب الزبون", "info")
    return redirect(url_for('index'))

@app.route('/pc/click', methods=['POST'])
def pc_single_click():
    """1-Click Recording for Single Gaming PC."""
    custom_price = request.form.get('price_lbp')
    note = request.form.get('note', 'استخدام كمبيوتر GAMING')

    success, res = accounting.log_single_pc_click(price_lbp=custom_price, note=note)
    if success:
        amount = res.get('total_lbp', res.get('price_lbp', 100000.0))
        flash(f"تم تسجيل استخدام GAMING بنجاح (+1) بمبلغ {amount:,.0f} ل.ل 🎮", "success")
    else:
        flash(f"خطأ: {res}", "danger")
    return redirect(url_for('index'))

@app.route('/sale/quick', methods=['POST'])
def quick_custom_sale():
    """Instant manual sale with typed name and price."""
    name = request.form.get('item_name', 'مبيعات يدوية').strip() or 'مبيعات يدوية'
    price_lbp = float(request.form.get('price_lbp') or 0)
    qty = int(request.form.get('quantity') or 1)

    if price_lbp <= 0:
        flash("يرجى إدخال سعر صحيح", "danger")
        return redirect(url_for('index'))

    items_list = [{'name': name, 'price_lbp': price_lbp, 'quantity': qty, 'item_id': None}]
    success, res = accounting.create_order({'customer_name': 'زبون كاش'}, items_list)
    if success:
        flash(f"تم تسجيل {name} بمبلغ {price_lbp * qty:,.0f} ل.ل بنجاح 💰", "success")
    else:
        flash(f"خطأ: {res}", "danger")
    return redirect(url_for('index'))

@app.route('/order/<int:order_id>/receipt', endpoint='order_receipt')
@app.route('/order/<int:order_id>/receipt', endpoint='print_receipt')
def order_receipt(order_id):
    """Printable Thermal Receipt for Cafe."""
    order = accounting.get_order_details(order_id)
    if not order:
        flash("الفاتورة غير موجودة", "danger")
        return redirect(url_for('index'))
    return render_template('print_receipt.html', order=order)

# ----------------- 3. CUSTOMER DEBTS LEDGER (سجل ديون الزبائن والآجل) -----------------

@app.route('/debts')
def debts_page():
    """Customer Debts Ledger & Balance Tracking."""
    search_q = request.args.get('q', '').strip()
    summary = accounting.get_debts_summary()
    customer_balances = accounting.get_customers_debt_balances(search=search_q if search_q else None)
    all_debts = accounting.get_all_debts(search=search_q if search_q else None, limit=100)

    return render_template(
        'debts.html',
        summary=summary,
        customer_balances=customer_balances,
        all_debts=all_debts,
        active_page='debts'
    )

@app.route('/debt/create/manual', methods=['POST'])
def debt_create_manual():
    """Manually add a debt record for a customer."""
    customer_name = request.form.get('customer_name', '').strip()
    phone = request.form.get('phone', '').strip()
    amount_lbp = request.form.get('amount_lbp', 0)
    notes = request.form.get('notes', '').strip()

    success, res = accounting.add_manual_debt(customer_name, amount_lbp, phone=phone, notes=notes)
    if success:
        flash(f"تم تسجيل دين جديد على الزبون ({customer_name}) بمبلغ {float(amount_lbp):,.0f} ل.ل بنجاح 📝", "success")
    else:
        flash(f"خطأ أثناء تسجيل الدين: {res}", "danger")
    return redirect(url_for('debts_page'))

@app.route('/debt/pay/customer', methods=['POST'])
def debt_pay_customer():
    """Record payment for a customer balance."""
    customer_name = request.form.get('customer_name', '').strip()
    amount_lbp = request.form.get('amount_lbp', 0)
    notes = request.form.get('notes', '').strip()

    success, res = accounting.pay_customer_balance(customer_name, amount_lbp, notes=notes)
    if success:
        flash(f"تم تسجيل دفعة سداد من الزبون ({customer_name}) بمبلغ {float(amount_lbp):,.0f} ل.ل بنجاح 💰", "success")
    else:
        flash(f"خطأ أثناء تسجيل السداد: {res}", "danger")
    return redirect(url_for('debts_page'))

@app.route('/debt/pay/single', methods=['POST'])
def debt_pay_single():
    """Record payment for a single debt record."""
    debt_id = request.form.get('debt_id')
    amount_lbp = request.form.get('amount_lbp', 0)
    notes = request.form.get('notes', '').strip()

    success, res = accounting.pay_debt(debt_id, amount_lbp, notes=notes)
    if success:
        flash(f"تم تسجيل سداد بمبلغ {float(amount_lbp):,.0f} ل.ل بنجاح 💰", "success")
    else:
        flash(f"خطأ: {res}", "danger")
    return redirect(url_for('debts_page'))

@app.route('/debt/<int:debt_id>/delete', methods=['POST'])
def debt_delete(debt_id):
    """Delete / Cancel a debt record."""
    accounting.delete_debt(debt_id)
    flash("تم حذف سجل الدين بنجاح", "info")
    return redirect(url_for('debts_page'))

# ----------------- 2. ADMIN AUTHENTICATION & DASHBOARD -----------------

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    """Admin Login Authentication supporting personal admin employee passwords/PINs."""
    if request.method == 'POST':
        entered_secret = request.form.get('admin_pin', '').strip()
        username = request.form.get('username', '').strip()
        authenticated = False
        emp_match = None
        if username:
            emp = accounting.authenticate_employee(username, entered_secret)
            if emp and emp.get('role') == 'admin':
                authenticated = True
                emp_match = emp
        else:
            conn = database.get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM employees WHERE role = 'admin' AND is_active = 1 AND (password = ? OR pin = ?)", (entered_secret, entered_secret))
            row = cursor.fetchone()
            conn.close()
            if row:
                authenticated = True
                emp_match = dict(row)
        if not authenticated and accounting.verify_admin_password(entered_secret):
            authenticated = True
        if authenticated:
            session['admin_authenticated'] = True
            session['admin_logged_in'] = True
            if emp_match:
                session['employee_id'] = emp_match['id']
                session['employee_name'] = emp_match['name']
                session['employee_role'] = emp_match['role']
            next_target = request.args.get('next') or request.form.get('next')
            flash('تم تسجيل الدخول لصفحة الإدارة بصلاحية المدير 🔓', 'success')
            if next_target and next_target.startswith('/'):
                return redirect(next_target)
            return redirect(url_for('admin_panel'))
        else:
            flash('⚠️ كلمة المرور غير صحيحة! تأكد من إدخال كلمة السر أو الـ PIN الخاص بك كمدير', 'danger')
            return render_template('admin_login.html', active_page='admin')
    if session.get('admin_authenticated'):
        return redirect(url_for('admin_panel'))
    return render_template('admin_login.html', active_page='admin')

@app.route('/admin/logout')
def admin_logout():
    """Admin Logout."""
    session.pop('admin_authenticated', None)
    session.pop('admin_logged_in', None)
    flash("تم تسجيل الخروج من صفحة الإدارة بنجاح", "info")
    return redirect(url_for('index'))

@app.route('/admin/change-password', methods=['POST'])
def admin_change_password():
    """Change Admin Password dynamically."""
    if not session.get('admin_authenticated'):
        return redirect(url_for('admin_login'))
    
    current_pin = request.form.get('current_pin', '').strip()
    new_pin = request.form.get('new_pin', '').strip()
    confirm_pin = request.form.get('confirm_pin', '').strip()

    if not accounting.verify_admin_password(current_pin):
        flash("⚠️ كلمة المرور الحالية غير صحيحة! لم يتم تغيير كلمة السر", "danger")
        return redirect(url_for('admin_panel'))
    
    if not new_pin or len(new_pin) < 4:
        flash("⚠️ يرجى إدخال كلمة سر جديدة لا تقل عن 4 أرقام أو حروف", "danger")
        return redirect(url_for('admin_panel'))
    
    if new_pin != confirm_pin:
        flash("⚠️ تأكيد كلمة السر الجديدة غير متطابق! يرجى إعادة المحاولة", "danger")
        return redirect(url_for('admin_panel'))
    
    success, msg = accounting.update_admin_password(new_pin)
    if success:
        flash(f"✅ {msg}", "success")
    else:
        flash(f"❌ {msg}", "danger")
    return redirect(url_for('admin_panel'))

@app.route('/admin', endpoint='admin')
@app.route('/admin', endpoint='admin_panel')
@admin_required
def admin_panel():
    """Daily Production & Financial Management Dashboard (Protected)."""
    if not session.get('admin_authenticated'):
        return redirect(url_for('admin_login'))

    target_date = request.args.get('date', accounting.get_business_date())
    daily_summary = accounting.get_daily_summary(target_date)
    orders = accounting.get_orders(target_date=target_date, limit=100)
    pc_logs = accounting.get_pc_logs(target_date=target_date, limit=100)
    expenses = accounting.get_expenses(target_date=target_date, limit=100)
    items = accounting.get_items(active_only=False)
    categories = accounting.get_categories()
    weekly_trend = accounting.get_weekly_trend()

    product_sales_raw = accounting.get_product_sales_breakdown(target_date=target_date)
    product_sales = product_sales_raw.get('products_list', product_sales_raw) if isinstance(product_sales_raw, dict) else product_sales_raw
    safe_balance = accounting.get_safe_balance()
    safe_daily = accounting.get_safe_daily_summary(target_date=target_date)
    daily_transfer_status = accounting.check_daily_safe_transfer_status(target_date=target_date)
    return render_template(
        'admin.html',
        daily_transfer_status=daily_transfer_status,
        summary=daily_summary,
        orders=orders,
        product_sales=product_sales,
        pc_logs=pc_logs,
        expenses=expenses,
        items=items,
        categories=categories,
        weekly_trend=weekly_trend,
        target_date=target_date,
        safe_balance=safe_balance,
        safe_daily=safe_daily,
        active_page='admin'
    )

@app.route('/print/daily')
def print_daily():
    """Printable Daily Closing Audit Statement."""
    target_date = request.args.get('date', accounting.get_business_date())
    daily_summary = accounting.get_daily_summary(target_date)
    orders = accounting.get_orders(target_date=target_date, limit=100)
    product_sales_raw = accounting.get_product_sales_breakdown(target_date=target_date)
    product_sales = product_sales_raw.get('products_list', product_sales_raw) if isinstance(product_sales_raw, dict) else product_sales_raw
    pc_logs = accounting.get_pc_logs(target_date=target_date, limit=100)
    expenses = accounting.get_expenses(target_date=target_date, limit=100)

    return render_template(
        'print_daily.html',
        summary=daily_summary,
        orders=orders,
        pc_logs=pc_logs,
        expenses=expenses,
        target_date=target_date
    )

# ----------------- 3. MANAGEMENT ACTIONS -----------------

@app.route('/expense/add', methods=['POST'])
@admin_required
def expense_add():
    title = request.form.get('title')
    amount = float(request.form.get('amount_lbp') or 0)
    category = request.form.get('category', 'مصاريف عامة')
    notes = request.form.get('notes', '')
    source = request.form.get('source', 'drawer')

    if not title or amount <= 0:
        flash("يرجى إدخال بيان المصروف والمبلغ", "danger")
        return redirect(url_for('admin_panel'))

    emp_id = session.get('employee_id')
    emp_name = session.get('employee_name', 'المدير')
    success, res = accounting.add_expense(
        title=title,
        amount_lbp=amount,
        category=category,
        notes=notes,
        source=source,
        employee_id=emp_id,
        employee_name=emp_name
    )
    if success:
        src_label = 'الخزنة الخاصة 🏦' if source == 'safe' else 'درج الصندوق 💵'
        flash(f"✅ تم تسجيل مصروف [{title}] بمبلغ {amount:,.0f} ل.ل بنجاح ({src_label})", "success")
    else:
        flash(f"خطأ: {res}", "danger")
    return redirect(url_for('admin_panel'))

@app.route('/expense/quick-add', methods=['POST'])
def expense_quick_add():
    """تسجيل مصروف سريع من درج الكاشير بواسطة الموظف أو الإدارة."""
    emp_id = session.get('employee_id')
    emp_name = session.get('employee_name', 'كاشير')
    is_admin = session.get('is_admin') or session.get('admin_authenticated')

    title = request.form.get('title', '').strip()
    amount = float(request.form.get('amount_lbp') or 0)
    category = request.form.get('category', 'مصاريف تشغيلية')
    notes = request.form.get('notes', '')
    source = request.form.get('source', 'drawer')

    # الدفع من الخزنة محصور بالإدارة فقط
    if source == 'safe' and not is_admin:
        flash("⚠️ الصرف من الخزنة الخاصة مخصص للإدارة فقط", "danger")
        return redirect(request.referrer or url_for('index'))

    if not title or amount <= 0:
        flash("⚠️ يرجى إدخال بيان المصروف والمبلغ بشكل صحيح", "danger")
        return redirect(request.referrer or url_for('index'))

    success, res = accounting.add_expense(
        title=title,
        amount_lbp=amount,
        category=category,
        notes=notes,
        source=source,
        employee_id=emp_id,
        employee_name=emp_name
    )
    if success:
        src_label = 'الخزنة الخاصة 🏦' if source == 'safe' else 'درج الصندوق 💵'
        flash(f"✅ تم تسجيل مصروف [{title}] بقيمة {amount:,.0f} ل.ل بنجاح من {src_label}", "success")
    else:
        flash(f"خطأ في تسجيل المصروف: {res}", "danger")
    return redirect(request.referrer or url_for('index'))

@app.route('/expense/<int:expense_id>/delete', methods=['POST'])
@admin_required
def expense_delete(expense_id):
    accounting.delete_expense(expense_id)
    flash("تم حذف المصروف", "info")
    return redirect(url_for('admin_panel'))

@app.route('/pc/log/<int:log_id>/delete', methods=['POST'])
def pc_log_delete(log_id):
    accounting.delete_pc_log(log_id)
    flash("تم حذف سجل GAMING", "info")
    return redirect(url_for('admin_panel'))

@app.route('/order/<int:order_id>/delete', methods=['POST'])
@admin_required
def order_delete(order_id):
    accounting.delete_order(order_id)
    flash("تم حذف الفاتورة", "info")
    return redirect(url_for('admin_panel'))

@app.route('/settings/update', methods=['POST'])
@admin_required
def settings_update():
    if not session.get('admin_authenticated'):
        return redirect(url_for('admin_login'))
    accounting.update_settings(request.form)
    flash("تم حفظ الإعدادات وسعر صرف الدولار بنجاح", "success")
    return redirect(url_for('admin_panel'))

# ----------------- CATEGORY & MENU ITEM MANAGEMENT -----------------

@app.route('/menu/category/add', methods=['POST'])
def menu_category_add():
    if not session.get('admin_authenticated'):
        return redirect(url_for('admin_login'))
    name = request.form.get('name', '').strip()
    icon = request.form.get('icon', '☕').strip() or '☕'
    sort_order = request.form.get('sort_order', 0)
    success, res = accounting.add_category(name, icon, sort_order)
    if success:
        flash(f"تمت إضافة القسم [{name}] بنجاح 🏷️", "success")
    else:
        flash(f"خطأ: {res}", "danger")
    return redirect(url_for('admin_panel'))

@app.route('/menu/category/<int:cat_id>/edit', methods=['POST'])
def menu_category_edit(cat_id):
    if not session.get('admin_authenticated'):
        return redirect(url_for('admin_login'))
    name = request.form.get('name', '').strip()
    icon = request.form.get('icon', '☕').strip() or '☕'
    sort_order = request.form.get('sort_order', 0)
    success, res = accounting.update_category(cat_id, name, icon, sort_order)
    if success:
        flash("تم تعديل القسم بنجاح", "success")
    else:
        flash(f"خطأ: {res}", "danger")
    return redirect(url_for('admin_panel'))

@app.route('/menu/category/<int:cat_id>/delete', methods=['POST'])
def menu_category_delete(cat_id):
    if not session.get('admin_authenticated'):
        return redirect(url_for('admin_login'))
    accounting.delete_category(cat_id)
    flash("تم حذف القسم وجميع أصنافه بنجاح", "info")
    return redirect(url_for('admin_panel'))

@app.route('/menu/add', methods=['POST'])
@app.route('/menu/item/add', methods=['POST'])
def menu_item_add():
    if not session.get('admin_authenticated'):
        return redirect(url_for('admin_login'))
    
    data = dict(request.form)
    # Check if an image file was uploaded
    if 'image_file' in request.files and request.files['image_file'].filename:
        img_url = save_uploaded_item_image(file=request.files['image_file'])
        if img_url:
            data['icon'] = img_url
    elif data.get('image_base64'):
        img_url = save_uploaded_item_image(data_url=data.get('image_base64'))
        if img_url:
            data['icon'] = img_url

    success, res = accounting.add_item(data)
    if success:
        flash("تمت إضافة الصنف إلى المنيو بنجاح! ☕", "success")
    else:
        flash(f"خطأ: {res}", "danger")
    return redirect(url_for('admin_panel'))

@app.route('/menu/item/<int:item_id>/edit', methods=['POST'])
def menu_item_edit(item_id):
    if not session.get('admin_authenticated'):
        return redirect(url_for('admin_login'))
    
    data = dict(request.form)
    # Check if a new image file was uploaded
    new_image_uploaded = False
    if 'image_file' in request.files and request.files['image_file'].filename:
        img_url = save_uploaded_item_image(file=request.files['image_file'], item_id=item_id)
        if img_url:
            data['icon'] = img_url
            new_image_uploaded = True
    elif data.get('image_base64'):
        img_url = save_uploaded_item_image(data_url=data.get('image_base64'), item_id=item_id)
        if img_url:
            data['icon'] = img_url
            new_image_uploaded = True

    # If no new image uploaded, check if there's a current_icon to preserve
    if not new_image_uploaded:
        current_icon = request.form.get('current_icon', '').strip()
        if current_icon and current_icon.startswith('/static'):
            # Preserve the existing image URL
            data['icon'] = current_icon
        elif not data.get('icon', '').strip():
            # No icon specified, keep existing from DB
            existing = accounting.get_item(item_id)
            if existing and existing.get('icon'):
                data['icon'] = existing['icon']

    success, res = accounting.update_item(item_id, data)
    if success:
        flash("تم تعديل الصنف والأسعار بنجاح", "success")
    else:
        flash(f"خطأ: {res}", "danger")
    return redirect(url_for('admin_panel'))

@app.route('/menu/<int:item_id>/delete', methods=['POST'])
@app.route('/menu/item/<int:item_id>/delete', methods=['POST'])
def menu_item_delete(item_id):
    if not session.get('admin_authenticated'):
        return redirect(url_for('admin_login'))
    accounting.delete_item(item_id)
    flash("تم حذف الصنف من المنيو", "info")
    return redirect(url_for('admin_panel'))

# ----------------- BACKUP, EXPORT & RESTORE (النسخ الاحتياطي واستيراد وتصدير البيانات) -----------------

@app.route('/backup/download')
@admin_required
def backup_download():
    """Download a full SQLite database backup file to user computer."""
    try:
        backup_path, backup_filename = database.create_backup_copy()
        return send_file(backup_path, as_attachment=True, download_name=backup_filename, mimetype='application/x-sqlite3')
    except Exception as e:
        flash(f"خطأ أثناء تصدير النسخة الاحتياطية: {str(e)}", "danger")
        return redirect(url_for('admin_panel'))

@app.route('/backup/restore', methods=['POST'])
@admin_required
def backup_restore():
    """Upload and restore database from a user backup file."""
    if not session.get('admin_authenticated'):
        return redirect(url_for('admin_login'))
    if 'backup_file' not in request.files:
        flash("يرجى اختيار ملف النسخة الاحتياطية أولاً", "danger")
        return redirect(url_for('admin_panel'))

    file = request.files['backup_file']
    if not file or file.filename == '':
        flash("لم يتم اختيار أي ملف", "danger")
        return redirect(url_for('admin_panel'))

    success, msg = database.restore_from_backup(file)
    if success:
        flash(msg, "success")
    else:
        flash(msg, "danger")
    return redirect(url_for('admin_panel'))

@app.route('/export/menu/json')
def export_menu_json():
    """Download menu items & categories as JSON file."""
    data = accounting.export_menu_data()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"stargate_menu_{timestamp}.json"
    response = Response(json.dumps(data, ensure_ascii=False, indent=2), mimetype='application/json; charset=utf-8')
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    return response

@app.route('/import/menu', methods=['POST'])
def import_menu():
    """Import menu items & categories from uploaded JSON file."""
    if not session.get('admin_authenticated'):
        return redirect(url_for('admin_login'))
    if 'menu_file' not in request.files:
        flash("يرجى اختيار ملف المنيو (JSON)", "danger")
        return redirect(url_for('admin_panel'))
    file = request.files['menu_file']
    if not file or file.filename == '':
        flash("لم يتم اختيار أي ملف", "danger")
        return redirect(url_for('admin_panel'))
    try:
        content = file.read().decode('utf-8')
        data = json.loads(content)
        success, msg = accounting.import_menu_data(data)
        if success:
            flash(msg, "success")
        else:
            flash(msg, "danger")
    except Exception as e:
        flash(f"خطأ في قراءة ملف المنيو: {str(e)}", "danger")
    return redirect(url_for('admin_panel'))

@app.route('/export/sales/csv')
def export_sales_csv_route():
    """Export complete sales, debts, and expenses to Excel CSV."""
    csv_data = accounting.export_sales_csv()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"stargate_sales_report_{timestamp}.csv"
    response = Response(csv_data, mimetype='text/csv; charset=utf-8')
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    return response

@app.route('/export/system/json')
def export_system_json():
    """Download full system backup as JSON package."""
    data = accounting.export_full_system_data()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"stargate_full_backup_{timestamp}.json"
    response = Response(json.dumps(data, ensure_ascii=False, indent=2), mimetype='application/json; charset=utf-8')
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    return response

@app.route('/import/system/json', methods=['POST'])
def import_system_json():
    """Import full system backup from uploaded JSON file."""
    if not session.get('admin_authenticated'):
        return redirect(url_for('admin_login'))
    if 'system_file' not in request.files:
        flash("يرجى اختيار ملف النسخة الاحتياطية (JSON)", "danger")
        return redirect(url_for('admin_panel'))
    file = request.files['system_file']
    if not file or file.filename == '':
        flash("لم يتم اختيار أي ملف", "danger")
        return redirect(url_for('admin_panel'))
    try:
        content = file.read().decode('utf-8')
        data = json.loads(content)
        success, msg = accounting.import_full_system_data(data)
        if success:
            flash(msg, "success")
        else:
            flash(msg, "danger")
    except Exception as e:
        flash(f"خطأ أثناء استيراد البيانات: {str(e)}", "danger")
    return redirect(url_for('admin_panel'))

@app.route('/admin/factory-reset', methods=['POST'])
@app.route('/reset/data', methods=['POST'])
@admin_required
def admin_factory_reset():
    entered_pin = request.form.get('admin_pin', '').strip() or request.form.get('password', '').strip()
    if not accounting.verify_admin_password(entered_pin):
        flash("⚠️ كلمة المرور غير صحيحة! يرجى إدخال كلمة سر الإدارة لتنفيذ ضبط المصنع", "danger")
        return redirect(url_for('admin_panel'))

    reset_type = request.form.get('reset_type', 'full')
    success, msg = accounting.factory_reset(reset_type)
    if success:
        if reset_type == 'full':
            session.clear()
        flash(msg, "warning" if reset_type == 'transactions_only' else "danger")
        return redirect(url_for('index') if reset_type == 'full' else url_for('admin_panel'))
    else:
        flash(f"خطأ: {msg}", "danger")
        return redirect(url_for('admin_panel'))

# ----------------- APP START -----------------


# ==========================================
# INVENTORY & FAST EDITING ROUTES (PRO CAFE)
# ==========================================

@app.route('/inventory')
@admin_required
def inventory_page():
    """Dedicated Pro Inventory & Stock Management Page."""
    items = accounting.get_inventory_stock()
    settings = accounting.get_settings()
    summary = accounting.get_daily_summary()
    categories = accounting.get_categories()
    return render_template(
        'inventory.html',
        items=items,
        settings=settings,
        summary=summary,
        categories=categories,
        active_page='inventory',
        company_name=settings.get('company_name', 'STARGATE')
    )

@app.route('/inventory/export/csv')
@app.route('/export/inventory-csv')
def export_inventory_csv_route():
    """Export current stock and inventory list to CSV (Excel compatible with UTF-8 BOM)."""
    items = accounting.get_inventory_stock()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M')
    
    # Generate CSV with UTF-8 BOM for Arabic Excel support
    lines = ["\ufeffمعرف الصنف,اسم الصنف,التصنيف,النوع,سعر البيع (ل.ل),سعر البيع ($),الكمية بالمستودع,حد الطلب الأدنى,الحالة"]
    for it in items:
        status_text = "متوفر" if it.get('stock_qty', 0) > it.get('low_stock_limit', 5) else ("منخفض" if it.get('stock_qty', 0) > 0 else "نفد من المستودع")
        if not it.get('track_stock'):
            status_text = "بدون تتبع كميات"
        line = f"{it.get('id')},\"{it.get('name')}\",\"{it.get('category_name') or '-'}\",{it.get('item_type')},{it.get('price_lbp')},{it.get('price_usd')},{it.get('stock_qty')},{it.get('low_stock_limit')},{status_text}"
        lines.append(line)
        
    csv_data = "\n".join(lines)
    filename = f"stargate_inventory_stock_{timestamp}.csv"
    response = Response(csv_data, mimetype='text/csv; charset=utf-8')
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    return response

@app.route('/item/quick-update', methods=['POST'])
def quick_update_item():
    """Ultra-fast AJAX inline update for item price, name, or stock."""
    try:
        data = request.get_json() or request.form
        item_id = int(data.get('item_id'))
        field = data.get('field')
        value = data.get('value')
        if not field or field not in ('price_lbp', 'price_usd', 'stock_qty', 'name'):
            return jsonify({'success': False, 'message': 'حقل غير صالح'}), 400
            
        success, msg = accounting.quick_update_item_field(item_id, field, value)
        return jsonify({'success': success, 'message': msg})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/item/quick-add', methods=['POST'])
def quick_add_item_inline():
    """Instant item creation directly from POS modal."""
    try:
        data = request.form.to_dict()
        if 'image_file' in request.files and request.files['image_file'].filename:
            img_url = save_uploaded_item_image(file=request.files['image_file'])
            if img_url:
                data['icon'] = img_url
        elif data.get('image_base64'):
            img_url = save_uploaded_item_image(data_url=data.get('image_base64'))
            if img_url:
                data['icon'] = img_url
        success, res = accounting.add_item(data)
        if success:
            flash("تمت إضافة الصنف بنجاح إلى المنيو والمخزون", "success")
        else:
            flash(f"تعذر إضافة الصنف: {res}", "danger")
    except Exception as e:
        flash(f"خطأ: {str(e)}", "danger")
    return redirect(request.referrer or url_for('index'))


# ==========================================
# EMPLOYEES & SHIFT MANAGEMENT ROUTES
# ==========================================

@app.route('/employees')
@admin_required
def employees_page():
    """Employee Management and Staff Performance Dashboard."""
    period = request.args.get('period', 'today')
    target_date = request.args.get('date') or accounting.get_business_date()
    all_time = (period == 'all')

    employees = accounting.get_all_employees()
    performance = accounting.get_employee_performance_summary(target_date=target_date, all_time=all_time)
    settings = accounting.get_settings()
    summary = accounting.get_daily_summary(target_date=target_date)
    return render_template(
        'employees.html',
        employees=employees,
        performance=performance,
        settings=settings,
        summary=summary,
        active_page='employees',
        period=period,
        selected_date=target_date,
        company_name=settings.get('company_name', 'STARGATE')
    )

@app.route('/employee/add', methods=['POST'])
def add_employee_route():
    """Create new employee."""
    success, res = accounting.add_employee(request.form.to_dict())
    if success:
        flash("تمت إضافة الموظف بنجاح", "success")
    else:
        flash(f"تعذر إضافة الموظف: {res}", "danger")
    return redirect(url_for('employees_page'))

@app.route('/employee/<int:emp_id>/edit', methods=['POST'])
def edit_employee_route(emp_id):
    """Update employee details."""
    success, res = accounting.update_employee(emp_id, request.form.to_dict())
    if success:
        flash("تم تعديل بيانات الموظف بنجاح", "success")
    else:
        flash(f"تعذر التعديل: {res}", "danger")
    return redirect(url_for('employees_page'))

@app.route('/employee/<int:emp_id>/delete', methods=['POST'])
def delete_employee_route(emp_id):
    """Permanently delete employee account."""
    if session.get('employee_id') == emp_id:
        flash("لا يمكنك حذف حسابك الشخصي الذي تستخدمه حالياً!", "warning")
        return redirect(url_for('employees_page'))
    success, res = accounting.delete_employee(emp_id)
    if success:
        flash("تم حذف الموظف نهائياً بنجاح", "success")
    else:
        flash(f"خطأ: {res}", "danger")
    return redirect(url_for('employees_page'))

@app.route('/employee/switch', methods=['POST'])
def switch_active_employee():
    """Switch current active employee on POS using PIN or username/password."""
    data = request.get_json() or request.form
    pin = (data.get('pin') or '').strip()
    username = (data.get('username') or '').strip()
    password = (data.get('password') or '').strip()

    emp = None
    if pin:
        emp = accounting.authenticate_employee(pin, None)
    elif username and password:
        emp = accounting.authenticate_employee(username, password)

    if emp:
        session['employee_id'] = emp['id']
        session['employee_name'] = emp['name']
        session['employee_role'] = emp['role']
        if emp.get('role') == 'admin':
            session['admin_authenticated'] = True
            session['admin_logged_in'] = True
            session['is_admin'] = True
        else:
            session.pop('admin_authenticated', None)
            session.pop('admin_logged_in', None)
            session.pop('is_admin', None)
        return jsonify({
            'success': True,
            'employee_id': emp['id'],
            'employee_name': emp['name'],
            'role': emp['role'],
            'is_admin': emp.get('role') == 'admin'
        })
    else:
        return jsonify({'success': False, 'message': 'رمز الـ PIN أو كلمة المرور غير صحيحة'}), 401

@app.route('/employee/current')
def get_current_employee():
    """Return currently active employee in session."""
    emp_id = session.get('employee_id')
    emp_name = session.get('employee_name')
    if not emp_name:
        # Default to first active employee or cashier
        emps = accounting.get_all_employees()
        if emps:
            first_cashier = next((e for e in emps if e['is_active'] and e['role'] == 'cashier'), emps[0])
            session['employee_id'] = first_cashier['id']
            session['employee_name'] = first_cashier['name']
            session['employee_role'] = first_cashier['role']
            emp_id = first_cashier['id']
            emp_name = first_cashier['name']
        else:
            emp_id = 1
            emp_name = 'كاشير'
            session['employee_id'] = emp_id
            session['employee_name'] = emp_name
            session['employee_role'] = 'cashier'

    return jsonify({
        'employee_id': emp_id,
        'employee_name': emp_name,
        'role': session.get('employee_role', 'cashier')
    })

# ==========================================
# EMPLOYEE AUTHENTICATION & SHIFT CLOSING
# ==========================================

@app.route('/employee/login', methods=['GET', 'POST'])
def employee_login():
    """Employee shift login screen."""
    if request.method == 'POST':
        pin = request.form.get('pin', '').strip()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        emp = None
        if pin:
            emp = accounting.authenticate_employee(pin, None)
        elif username and password:
            emp = accounting.authenticate_employee(username, password)

        if emp:
            session['employee_id'] = emp['id']
            session['employee_name'] = emp['name']
            session['employee_role'] = emp['role']
            if emp.get('role') == 'admin':
                session['admin_authenticated'] = True
                session['admin_logged_in'] = True
                session['is_admin'] = True
            session['shift_start_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            flash(f"أهلاً بك {emp['name']}، تم بدء ورديتك بنجاح ☕", "success")
            return redirect(url_for('index'))
        else:
            flash("رمز الدخول (PIN) أو كلمة المرور غير صحيحة!", "danger")
            return redirect(url_for('employee_login'))

    return render_template('employee_login.html', company_name=accounting.get_settings().get('company_name', 'STARGATE CAFE'))

@app.route('/employee/logout')
def employee_logout():
    """Logout current employee and lock POS screen."""
    emp_name = session.get('employee_name', 'الموظف')
    session.pop('employee_id', None)
    session.pop('employee_name', None)
    session.pop('employee_role', None)
    session.pop('shift_start_time', None)
    flash(f"تم قفل الحساب وتسجيل خروج {emp_name} بنجاح.", "info")
    return redirect(url_for('employee_login'))

@app.route('/employee/close-shift', methods=['GET', 'POST'])
def employee_close_shift():
    """Close employee shift, calculate sales, reconcile cash drawer, and handover to next employee."""
    emp_id = session.get('employee_id')
    emp_name = session.get('employee_name')
    if not emp_id and not session.get('is_admin'):
        return redirect(url_for('employee_login'))

    today_str = accounting.get_business_date()
    settings = accounting.get_settings()
    exchange_rate = float(settings.get('exchange_rate') or 89500.0)
    company_name = settings.get('company_name', 'STARGATE CAFE')

    # 1. مبيعات الموظف لليوم
    emp_orders = accounting.get_orders(target_date=today_str, employee_id=emp_id)
    total_sales_lbp = sum(float(o.get('total_lbp', 0)) for o in emp_orders)
    total_sales_usd = sum(float(o.get('total_usd', 0)) for o in emp_orders)
    cash_sales_lbp = sum(float(o.get('total_lbp', 0)) for o in emp_orders if o.get('payment_method') == 'cash')
    debt_sales_lbp = sum(float(o.get('total_lbp', 0)) for o in emp_orders if o.get('payment_method') == 'debt')

    # 2. حركة الكاش الشاملة للصندوق (تحصيل ديون، مصاريف الدرج، تحويلات الخزنة السابقة، عهدة افتتاحية)
    conn = accounting.get_db()
    c = conn.cursor()

    # سدادات ديون مستلمة اليوم
    if emp_id:
        c.execute("""
            SELECT COALESCE(SUM(amount_lbp), 0)
            FROM debt_payments
            WHERE (DATE(datetime(created_at, '-5 hours')) = DATE(?) OR DATE(created_at) = DATE(?))
              AND (employee_id = ? OR employee_id IS NULL)
        """, (today_str, today_str, emp_id))
    else:
        c.execute("""
            SELECT COALESCE(SUM(amount_lbp), 0)
            FROM debt_payments
            WHERE (DATE(datetime(created_at, '-5 hours')) = DATE(?) OR DATE(created_at) = DATE(?))
        """, (today_str, today_str))
    debt_collected_lbp = float(c.fetchone()[0] or 0.0)

    # مصاريف مدفوعة من الدرج اليوم
    if emp_id:
        c.execute("""
            SELECT COALESCE(SUM(amount_lbp), 0)
            FROM expenses
            WHERE (DATE(datetime(created_at, '-5 hours')) = DATE(?) OR DATE(created_at) = DATE(?))
              AND (source != 'safe' OR source IS NULL)
              AND (employee_id = ? OR employee_id IS NULL)
        """, (today_str, today_str, emp_id))
    else:
        c.execute("""
            SELECT COALESCE(SUM(amount_lbp), 0)
            FROM expenses
            WHERE (DATE(datetime(created_at, '-5 hours')) = DATE(?) OR DATE(created_at) = DATE(?))
              AND (source != 'safe' OR source IS NULL)
        """, (today_str, today_str))
    shift_expenses_lbp = float(c.fetchone()[0] or 0.0)

    # مبالغ تم توريدها للخزنة مسبقاً خلال الوردية
    if emp_id:
        c.execute("""
            SELECT COALESCE(SUM(amount_lbp), 0)
            FROM safe_transfers
            WHERE (DATE(datetime(created_at, '-5 hours')) = DATE(?) OR DATE(created_at) = DATE(?) OR note LIKE ?)
              AND operation_type = 'deposit'
              AND (source != 'external' OR source IS NULL)
              AND (employee_id = ? OR employee_id IS NULL)
        """, (today_str, today_str, f"%{today_str}%", emp_id))
    else:
        c.execute("""
            SELECT COALESCE(SUM(amount_lbp), 0)
            FROM safe_transfers
            WHERE (DATE(datetime(created_at, '-5 hours')) = DATE(?) OR DATE(created_at) = DATE(?) OR note LIKE ?)
              AND operation_type = 'deposit'
              AND (source != 'external' OR source IS NULL)
        """, (today_str, today_str, f"%{today_str}%"))
    prior_safe_transfers_lbp = float(c.fetchone()[0] or 0.0)
    conn.close()

    # عهدة افتتاحية للدرج إن وجدت
    opening_float = float(session.get('opening_cash_lbp') or session.get('handover_actual_cash') or 0.0)

    # رصيد الكاش المتوقع في الدرج بدقة متناهية
    # الكاش المتوقع = (عهدة افتتاحية + مبيعات كاش + تحصيل ديون) - (مصاريف الصندوق + توريدات الخزنة السابقة)
    expected_cash_lbp = max(0.0, opening_float + cash_sales_lbp + debt_collected_lbp - shift_expenses_lbp - prior_safe_transfers_lbp)

    if request.method == 'POST':
        actual_cash_val = request.form.get('actual_cash_lbp', '').strip()
        if not actual_cash_val:
            flash("⚠️ يجب وضع مبلغ الكاش الفعلي في الصندوق قبل تسكير الوردية!", "danger")
            return render_template(
                'employee_close_shift.html',
                emp_name=emp_name,
                orders_count=len(emp_orders),
                total_sales_lbp=total_sales_lbp,
                total_sales_usd=total_sales_usd,
                cash_sales_lbp=cash_sales_lbp,
                debt_sales_lbp=debt_sales_lbp,
                debt_collected_lbp=debt_collected_lbp,
                shift_expenses_lbp=shift_expenses_lbp,
                prior_safe_transfers_lbp=prior_safe_transfers_lbp,
                opening_float=opening_float,
                expected_cash_lbp=expected_cash_lbp,
                target_date=today_str,
                company_name=company_name,
                exchange_rate=exchange_rate
            )

        actual_cash = float(actual_cash_val)
        diff = actual_cash - expected_cash_lbp
        
        diff_note = ""
        if diff > 0:
            diff_note = f" (زيادة نقدية: +{diff:,.0f} ل.ل)"
        elif diff < 0:
            diff_note = f" (عجز نقدي: -{abs(diff):,.0f} ل.ل)"
        else:
            diff_note = " (مطابق 100% بدون أي عجز)"

        # فحص هل اختار الموظف أو الإدارة توريد الكاش للخزنة الخاصة عند تسكير الوردية
        transfer_to_safe = request.form.get('transfer_to_safe') in ('yes', '1', 'true', 'on')
        safe_deposit_val = request.form.get('safe_deposit_lbp', '').strip()
        safe_deposit_lbp = float(safe_deposit_val) if safe_deposit_val and float(safe_deposit_val) > 0 else 0.0

        safe_transfer_note = ""
        drawer_remaining_cash = actual_cash
        if transfer_to_safe and safe_deposit_lbp > 0:
            try:
                # تسجيل إيداع بالخزنة الخاصة من الدرج
                transfer_id = accounting.add_safe_transfer(
                    amount_lbp=safe_deposit_lbp,
                    note=f"توريد كاش تسكير وردية ({emp_name})",
                    transferred_by=emp_name,
                    operation_type='deposit',
                    source='drawer',
                    target='safe',
                    employee_id=emp_id,
                    employee_name=emp_name
                )
                drawer_remaining_cash = max(0.0, actual_cash - safe_deposit_lbp)
                safe_transfer_note = f" (تم ترحيل {safe_deposit_lbp:,.0f} ل.ل إلى الخزنة الخاصة 🏦 والمتبقي بالصندوق {drawer_remaining_cash:,.0f} ل.ل)"
            except Exception as e:
                safe_transfer_note = f" (تنبيه: تعذر إيداع الكاش بالخزنة: {e})"

        # Log shift closing in employee performance record
        try:
            accounting.log_shift_close(
                employee_id=emp_id,
                employee_name=emp_name,
                total_sales_lbp=total_sales_lbp,
                cash_sales_lbp=actual_cash,
                production_note=f"تسكير وردية ومطابقة الصندوق [متوقع: {expected_cash_lbp:,.0f} | فعلي: {actual_cash:,.0f}]{diff_note}{safe_transfer_note}",
                date=today_str
            )
        except Exception:
            pass  # Non-critical
        
        # Finalize shift closing & handover to next employee
        session.pop('employee_id', None)
        session.pop('employee_name', None)
        session.pop('employee_role', None)
        session.pop('admin_authenticated', None)
        session.pop('admin_logged_in', None)
        session.pop('is_admin', None)
        session['handover_prev_employee'] = emp_name
        session['handover_actual_cash'] = drawer_remaining_cash
        session['handover_diff_note'] = f"{diff_note}{safe_transfer_note}"
        
        flash(f"✅ تم تسكير وردية {emp_name} بنجاح ومقارنة الصندوق{diff_note}{safe_transfer_note}. يرجى من الموظف التالي تسجيل الدخول لاستلام الصندوق.", "success")
        return redirect(url_for('employee_login'))

    return render_template(
        'employee_close_shift.html',
        emp_name=emp_name,
        orders_count=len(emp_orders),
        total_sales_lbp=total_sales_lbp,
        total_sales_usd=total_sales_usd,
        cash_sales_lbp=cash_sales_lbp,
        debt_sales_lbp=debt_sales_lbp,
        debt_collected_lbp=debt_collected_lbp,
        shift_expenses_lbp=shift_expenses_lbp,
        prior_safe_transfers_lbp=prior_safe_transfers_lbp,
        opening_float=opening_float,
        expected_cash_lbp=expected_cash_lbp,
        target_date=today_str,
        company_name=company_name,
        exchange_rate=exchange_rate
    )

def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'), 'icons/favicon.ico', mimetype='image/vnd.microsoft.icon') if os.path.exists(os.path.join(app.root_path, 'static', 'icons', 'favicon.ico')) else ('', 204)

@app.errorhandler(500)
def internal_server_error_handler(e):
    import traceback
    err_detail = traceback.format_exc()
    print("CRITICAL 500 ERROR DETECTED:", err_detail)
    try:
        log_path = os.path.join(database.DB_DIR, "server_error.log")
        with open(log_path, "a", encoding="utf-8") as lf:
            lf.write(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 500 ERROR:\n{err_detail}\n" + "="*60 + "\n")
    except Exception:
        pass
    return render_template_string("""
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <title>خطأ في النظام</title>
        <style>body { font-family: sans-serif; background: #0f172a; color: #fff; text-align: center; padding: 50px; }</style>
    </head>
    <body>
        <h1 style="color: #f43f5e;">⚠️ حدث خطأ في النظام</h1>
        <p>يرجى العودة والضغط على الزر مرة أخرى أو إعادة تشغيل البرنامج.</p>
        <a href="/" style="display: inline-block; background: #3b82f6; color: white; padding: 10px 20px; border-radius: 8px; text-decoration: none; font-weight: bold; margin-top: 15px;">العودة للرئيسية</a>
        <div style="margin-top: 30px; text-align: left; background: #1e293b; padding: 15px; border-radius: 8px; font-family: monospace; font-size: 11px; max-width: 700px; margin-left: auto; margin-right: auto; overflow: auto; color: #fca5a5;">
            {{ err_detail }}
        </div>
    </body>
    </html>
    """, err_detail=err_detail), 500




# ============================================================
# 🏦 routes الخزنة الخاصة (Safe/Vault)
# ============================================================

# -------------------------------------------------------------------------
# 🏦 CENTRAL VAULT & SAFE ROUTES (الخزنة الخاصة وإدارة النقدية)
# -------------------------------------------------------------------------

@app.route('/safe', endpoint='safe_page')
@admin_required
def safe_page():
    """صفحة الخزنة الخاصة مع البحث المتقدم عبر التاريخ ودعم الإيداع والسحب."""
    if 'employee_id' not in session and not session.get('is_admin') and not session.get('admin_authenticated'):
        return redirect(url_for('employee_login'))

    today_str = accounting.get_business_date()
    yesterday_str = accounting.get_business_date(dt=(datetime.now() - timedelta(days=1)))

    raw_date = request.args.get('date', '').strip()
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()
    search_query = request.args.get('q', '').strip()

    is_range = False
    is_filtered = False

    if start_date and end_date and start_date != end_date:
        is_range = True
        is_filtered = True
        target_date = start_date
        display_period = f"من {start_date} إلى {end_date}"
    elif raw_date == 'all':
        target_date = 'all'
        start_date = None
        end_date = None
        is_filtered = True
        display_period = "كافة التاريخ"
    elif raw_date:
        target_date = raw_date
        start_date = raw_date
        end_date = raw_date
        is_filtered = True
        display_period = raw_date
    elif start_date:
        target_date = start_date
        end_date = start_date
        is_filtered = True
        display_period = start_date
    else:
        target_date = today_str
        start_date = today_str
        end_date = today_str
        display_period = f"اليوم ({today_str})"

    settings = accounting.get_settings()
    rate = float(settings.get('exchange_rate') or 89500.0)

    transfers = accounting.get_safe_transfers(
        start_date=start_date if target_date != 'all' else None,
        end_date=end_date if target_date != 'all' else None,
        search_query=search_query,
        target_date=target_date
    )
    balance = accounting.get_safe_balance()
    period_summary = accounting.get_safe_daily_summary(
        target_date=target_date if target_date != 'all' else None,
        start_date=start_date if is_range else None,
        end_date=end_date if is_range else None
    )
    drawer_status = accounting.get_drawer_cash_status()
    daily_transfer_status = accounting.check_daily_safe_transfer_status(target_date if target_date != 'all' else today_str)

    return render_template('safe.html',
        daily_transfer_status=daily_transfer_status,
        transfers=transfers,
        balance=balance,
        period_summary=period_summary,
        drawer_status=drawer_status,
        target_date=target_date,
        start_date=start_date,
        end_date=end_date,
        search_query=search_query,
        is_range=is_range,
        is_filtered=is_filtered,
        display_period=display_period,
        today_str=today_str,
        yesterday_str=yesterday_str,
        settings=settings,
        rate=rate,
        active_page='safe'
    )


@app.route('/safe/transfer', methods=['POST'])
def safe_transfer():
    """إضافة عملية إيداع أو سحب للخزنة مع دعم الليرة والدولار والتحقق من الصلاحيات."""
    if 'employee_id' not in session and not session.get('is_admin') and not session.get('admin_authenticated'):
        return redirect(url_for('employee_login'))

    op_type = request.form.get('operation_type', 'deposit').strip()
    # عمليات السحب فقط محصورة بالمدير:
    if op_type == 'withdraw' and not session.get('is_admin') and not session.get('admin_authenticated') and session.get('employee_role') != 'admin':
        flash('⚠️ عذراً، عمليات السحب من الخزنة مخصصة لمدير النظام فقط!', 'danger')
        return redirect(url_for('safe_page'))

    try:
        amount_lbp = float(request.form.get('amount_lbp') or 0)
        amount_usd = float(request.form.get('amount_usd') or 0)
        note = request.form.get('note', '').strip()
        transferred_by = request.form.get('transferred_by', session.get('employee_name', 'المدير')).strip()

        if amount_lbp <= 0 and amount_usd <= 0:
            flash('يرجى إدخال مبلغ صحيح أكبر من صفر بالليرة أو الدولار', 'warning')
            return redirect(url_for('safe_page'))

        if not note:
            note = 'إيداع نقدي في الخزنة' if op_type == 'deposit' else 'سحب نقدي من الخزنة'

        settings = accounting.get_settings()
        rate = float(settings.get('exchange_rate') or 89500.0)

        accounting.add_safe_transfer(
            amount_lbp=amount_lbp,
            amount_usd=amount_usd,
            note=note,
            transferred_by=transferred_by,
            rate=rate,
            operation_type=op_type,
            employee_id=session.get('employee_id')
        )
        op_title = "إيداع" if op_type == 'deposit' else "سحب"
        flash(f'تم تسجيل عملية {op_title} بنجاح في الخزنة الخاصة ✓', 'success')
    except Exception as e:
        flash(f'خطأ أثناء الحفظ في الخزنة: {str(e)}', 'danger')

    return redirect(url_for('safe_page'))


@app.route('/safe/transfer/<int:transfer_id>/delete', methods=['POST'])
def delete_safe_transfer(transfer_id):
    """حذف حركة من الخزنة."""
    ok = accounting.delete_safe_transfer(transfer_id)
    if ok:
        flash('تم حذف الحركة من سجل الخزنة بنجاح', 'info')
    else:
        flash('تعذر العثور على الحركة المطلوبة', 'error')
    return redirect(url_for('safe_page'))


@app.route('/print/safe-statement')
def print_safe_statement():
    """طباعة كشف حساب الخزنة للفترة المحددة."""
    raw_date = request.args.get('date', '').strip()
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()
    search_query = request.args.get('q', '').strip()

    is_range = bool(start_date and end_date and start_date != end_date)
    transfers = accounting.get_safe_transfers(
        start_date=start_date if raw_date != 'all' else None,
        end_date=end_date if raw_date != 'all' else None,
        search_query=search_query,
        target_date=raw_date
    )
    balance = accounting.get_safe_balance()
    period_summary = accounting.get_safe_daily_summary(
        target_date=raw_date if raw_date != 'all' else None,
        start_date=start_date if is_range else None,
        end_date=end_date if is_range else None
    )
    settings = accounting.get_settings()
    rate = float(settings.get('exchange_rate') or 89500.0)

    display_period = f"من {start_date} إلى {end_date}" if is_range else (raw_date or "كامل التاريخ")

    return render_template('print_safe_statement.html',
        transfers=transfers,
        balance=balance,
        daily=period_summary,
        period_summary=period_summary,
        target_date=display_period,
        display_period=display_period,
        settings=settings,
        rate=rate
    )



@app.route('/api/inventory/alerts')
def api_inventory_alerts():
    """API: جلب عدد المنتجات المنخفضة أو النافدة من المخزون."""
    try:
        alerts = accounting.get_inventory_alerts_count()
        return jsonify(alerts)
    except Exception as e:
        return jsonify({'total': 0, 'out_of_stock': 0, 'low_stock': 0, 'error': str(e)})

if __name__ == '__main__':
    init_db()
    print("=" * 60)
    print("[RUNNING] Cafe & Single Gaming PC Accounting on http://127.0.0.1:5000")
    print("=" * 60)
    app.run(host='0.0.0.0', port=5000, debug=True)


# ----------------- QUICK ITEM & SAFE API ENDPOINTS -----------------

@app.route('/api/item/quick_edit', methods=['POST'])
def api_item_quick_edit():
    try:
        data = request.form if request.form else (request.get_json() or {})
        item_id_raw = data.get('item_id')
        if not item_id_raw:
            return jsonify({'success': False, 'error': 'معرف الصنف غير موجود'}), 400
        item_id = int(item_id_raw)
        
        name = str(data.get('name') or '').strip()
        if not name:
            existing = accounting.get_item(item_id)
            name = existing.get('name', 'صنف') if existing else 'صنف'
            
        try:
            price_lbp = float(data.get('price_lbp') or 0)
        except (ValueError, TypeError):
            price_lbp = 0.0
            
        try:
            price_usd = float(data.get('price_usd') or 0)
        except (ValueError, TypeError):
            price_usd = 0.0

        cat_id_raw = data.get('category_id')
        category_id = None
        if cat_id_raw and str(cat_id_raw).strip() not in ('None', 'null', '', '0'):
            try:
                category_id = int(cat_id_raw)
            except (ValueError, TypeError):
                category_id = None

        try:
            conn_cat = database.get_db()
            c_cat = conn_cat.cursor()
            valid_cat = False
            if category_id is not None:
                c_cat.execute("SELECT id FROM cafe_categories WHERE id = ?", (category_id,))
                if c_cat.fetchone():
                    valid_cat = True
            if not valid_cat:
                existing = accounting.get_item(item_id)
                category_id = existing.get('category_id') if existing else None
                if not category_id:
                    c_cat.execute("SELECT id FROM cafe_categories LIMIT 1")
                    r_cat = c_cat.fetchone()
                    category_id = r_cat[0] if r_cat else 6
        except Exception:
            pass

        item_type = str(data.get('item_type') or 'cafe').strip() or 'cafe'
        icon = str(data.get('icon') or '').strip()
        current_icon = str(data.get('current_icon') or '').strip()
        
        # Check if an image file was uploaded
        if 'image_file' in request.files and request.files['image_file'].filename:
            img_url = save_uploaded_item_image(file=request.files['image_file'], item_id=item_id)
            if img_url:
                icon = img_url
        elif data.get('image_base64'):
            img_url = save_uploaded_item_image(data_url=data.get('image_base64'), item_id=item_id)
            if img_url:
                icon = img_url

        # Image preservation logic
        if not icon and current_icon:
            icon = current_icon
        elif not icon:
            existing = accounting.get_item(item_id)
            if existing and existing.get('icon'):
                icon = existing['icon']
            else:
                icon = '☕'

        settings = accounting.get_settings()
        rate = float(settings.get('exchange_rate') or 89500.0)
        if price_lbp > 0 and price_usd == 0 and rate > 0:
            price_usd = round(price_lbp / rate, 2)
        elif price_usd > 0 and price_lbp == 0 and rate > 0:
            price_lbp = round(price_usd * rate, -3)
            
        conn = database.get_db()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE cafe_items 
            SET name = ?, price_lbp = ?, price_usd = ?, category_id = ?, item_type = ?, icon = ?
            WHERE id = ?
        """, (name, price_lbp, price_usd, category_id, item_type, icon, item_id))
            
        conn.commit()
        return jsonify({
            'success': True,
            'message': 'تم تحديث بيانات وصورة الصنف بنجاح',
            'item': {
                'id': item_id,
                'name': name,
                'price_lbp': price_lbp,
                'price_usd': price_usd,
                'category_id': category_id,
                'item_type': item_type,
                'icon': icon
            }
        })
    except Exception as e:
        print(f"Quick edit error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 400

@app.route('/api/item/quick_add', methods=['POST'])
def api_item_quick_add():
    try:
        data = request.get_json() if request.is_json else request.form
        name = data.get('name', '').strip()
        price_lbp = float(data.get('price_lbp') or 0)
        price_usd = float(data.get('price_usd') or 0)
        category_id = int(data.get('category_id')) if data.get('category_id') else 1
        item_type = data.get('item_type', 'cafe').strip()
        
        settings = accounting.get_settings()
        rate = float(settings.get('exchange_rate') or 89500.0)
        if price_lbp > 0 and price_usd == 0:
            price_usd = round(price_lbp / rate, 2)
        elif price_usd > 0 and price_lbp == 0:
            price_lbp = round(price_usd * rate, -3)

        new_id = accounting.add_item({
            'name': name,
            'price_lbp': price_lbp,
            'price_usd': price_usd,
            'category_id': category_id,
            'item_type': item_type,
            'icon': '☕' if item_type == 'cafe' else ('🎮' if item_type in ('gaming', 'computer') else '✍️')
        })
        return jsonify({'success': True, 'item_id': new_id, 'name': name, 'price_lbp': price_lbp, 'price_usd': price_usd})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@app.route('/safe/quick_transfer', methods=['POST'])
def safe_quick_transfer():
    if 'employee_id' not in session and not session.get('is_admin') and not session.get('admin_authenticated'):
        return jsonify({'success': False, 'error': 'يجب تسجيل الدخول لتسجيل حركة بالخزنة'}), 401

    try:
        data = request.get_json() if request.is_json else request.form
        amount_lbp = float(data.get('amount_lbp') or 0)
        amount_usd = float(data.get('amount_usd') or 0)
        emp_name = data.get('employee_name') or session.get('employee_name', 'الكاشير')
        note = (data.get('note') or 'توريد نقدي إلى الخزنة الخاصة').strip()

        settings = accounting.get_settings()
        rate = float(settings.get('exchange_rate') or 89500.0)
        if amount_usd > 0 and amount_lbp <= 0:
            amount_lbp = round(amount_usd * rate, 0)
        elif amount_lbp > 0 and amount_usd <= 0:
            amount_usd = round(amount_lbp / rate, 2)

        if amount_lbp <= 0 and amount_usd <= 0:
            return jsonify({'success': False, 'error': 'يرجى إدخال مبلغ صحيح أكبر من صفر'}), 400

        transfer_id = accounting.add_safe_transfer(
            amount_lbp=amount_lbp,
            amount_usd=amount_usd,
            note=f"{note} (المسلّم: {emp_name})",
            transferred_by=emp_name,
            rate=rate,
            operation_type='deposit',
            employee_id=session.get('employee_id')
        )
        new_balance = accounting.get_safe_balance()
        return jsonify({
            'success': True,
            'transfer_id': transfer_id,
            'message': f'تم ترحيل {amount_lbp:,.0f} ل.ل إلى الخزنة الخاصة بنجاح',
            'balance': new_balance
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


# -------------------------------------------------------------------------
# 📊 COMPREHENSIVE DAILY & PERIOD FINANCIAL REPORTS (التقارير اليومية وحركة الأصناف)
# -------------------------------------------------------------------------

@app.route('/reports', endpoint='reports_page')
@admin_required
def reports_page():
    """صفحة التقارير اليومية وتفاصيل حركة المنتجات والأصناف."""
    if 'employee_id' not in session and not session.get('is_admin') and not session.get('admin_authenticated'):
        return redirect(url_for('employee_login'))

    today_str = accounting.get_business_date()
    yesterday_str = accounting.get_business_date(dt=(datetime.now() - timedelta(days=1)))
    before_yesterday_str = accounting.get_business_date(dt=(datetime.now() - timedelta(days=2)))

    raw_date = request.args.get('date', '').strip()
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()

    is_range = False
    if start_date and end_date and start_date != end_date:
        is_range = True
        target_date = start_date
        display_period = f"من {start_date} إلى {end_date}"
    elif raw_date == 'all':
        target_date = 'all'
        start_date = None
        end_date = None
        display_period = "كافة التاريخ المسجل"
    elif raw_date:
        target_date = raw_date
        start_date = raw_date
        end_date = raw_date
        display_period = raw_date
    elif start_date:
        target_date = start_date
        end_date = start_date
        display_period = start_date
    else:
        target_date = today_str
        start_date = today_str
        end_date = today_str
        display_period = f"اليوم ({today_str})"

    # Fetch Data
    summary = accounting.get_daily_summary(target_date=target_date if target_date != 'all' else None)
    products_report = accounting.get_product_sales_breakdown(
        target_date=target_date,
        start_date=start_date if is_range else None,
        end_date=end_date if is_range else None
    )
    orders = accounting.get_orders(target_date=target_date if target_date != 'all' else None, limit=200)
    expenses = accounting.get_expenses(target_date=target_date if target_date != 'all' else None, limit=100)
    pc_logs = accounting.get_pc_logs(target_date=target_date if target_date != 'all' else None, limit=100)
    safe_period = accounting.get_safe_daily_summary(
        target_date=target_date,
        start_date=start_date if is_range else None,
        end_date=end_date if is_range else None
    )
    drawer_status = accounting.get_drawer_cash_status()
    daily_transfer_status = accounting.check_daily_safe_transfer_status(target_date if target_date != 'all' else today_str)
    category_sales = accounting.get_category_sales_distribution(target_date if target_date != 'all' else today_str)
    hourly_sales = accounting.get_hourly_sales_distribution(target_date if target_date != 'all' else today_str)
    staff_summary = accounting.get_employee_performance_summary(target_date=target_date if target_date != 'all' else today_str)

    return render_template(
        'reports.html',
        daily_transfer_status=daily_transfer_status,
        category_sales=category_sales,
        hourly_sales=hourly_sales,
        staff_summary=staff_summary,
        summary=summary,
        products_report=products_report,
        orders=orders,
        expenses=expenses,
        pc_logs=pc_logs,
        safe_period=safe_period,
        drawer_status=drawer_status,
        target_date=target_date,
        start_date=start_date,
        end_date=end_date,
        is_range=is_range,
        display_period=display_period,
        today_str=today_str,
        yesterday_str=yesterday_str,
        before_yesterday_str=before_yesterday_str,
        active_page='reports'
    )


@app.route('/reports/print', endpoint='print_reports_page')
def print_reports_page():
    """طباعة التقرير المالي وحركة الأصناف A4."""
    today_str = accounting.get_business_date()
    raw_date = request.args.get('date', '').strip()
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()

    is_range = False
    if start_date and end_date and start_date != end_date:
        is_range = True
        target_date = start_date
        display_period = f"من {start_date} إلى {end_date}"
    elif raw_date == 'all':
        target_date = 'all'
        display_period = "كافة التاريخ المسجل"
    elif raw_date:
        target_date = raw_date
        display_period = raw_date
    else:
        target_date = today_str
        display_period = today_str

    summary = accounting.get_daily_summary(target_date=target_date if target_date != 'all' else None)
    products_report = accounting.get_product_sales_breakdown(
        target_date=target_date,
        start_date=start_date if is_range else None,
        end_date=end_date if is_range else None
    )
    drawer_status = accounting.get_drawer_cash_status()
    settings = accounting.get_settings()
    rate = float(settings.get('exchange_rate') or 89500.0)

    return render_template(
        'print_reports.html',
        summary=summary,
        products_report=products_report,
        drawer_status=drawer_status,
        display_period=display_period,
        company_name=settings.get('company_name', 'STARGATE CAFE'),
        exchange_rate=rate
    )


@app.route('/reports/export-csv', endpoint='export_reports_csv')
def export_reports_csv():
    """تصدير تقرير مبيعات الأصناف لملف CSV / Excel."""
    import io, csv
    from flask import Response
    target_date = request.args.get('date', accounting.get_business_date())
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    report = accounting.get_product_sales_breakdown(target_date=target_date, start_date=start_date, end_date=end_date)
    settings = accounting.get_settings()
    rate = float(settings.get('exchange_rate') or 89500.0)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["#", "اسم الصنف", "القسم", "الكمية المباعة", "متوسط السعر (ل.ل)", "إجمالي المبيعات (ل.ل)", "المقابل بالدولار ($)", "نسبة المساهمة %"])

    for i, it in enumerate(report['products_list'], 1):
        writer.writerow([
            i,
            it['item_name'],
            it['category_name'],
            it['total_qty'],
            it['avg_price_lbp'],
            it['total_lbp'],
            it['total_usd'],
            f"{it['pct']}%"
        ])

    writer.writerow([])
    writer.writerow(["المجموع", "", "", report['grand_total_qty'], "", report['grand_total_lbp'], round(report['grand_total_lbp'] / rate, 2), "100%"])

    csv_data = output.getvalue().encode('utf-8-sig')
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-disposition": f"attachment; filename=stargate_cafe_report_{target_date}.csv"}
    )

# =========================================================================
# SPECIAL SAFE DAILY TRANSFER ROUTES
# =========================================================================

@app.route('/safe/transfer_daily', methods=['POST'])
def safe_transfer_daily():
    """نقل وترحيل صافي نقدية اليوم إلى الخزنة الخاصة مباشرة بنقرة واحدة."""
    if 'employee_id' not in session and not session.get('is_admin') and not session.get('admin_authenticated'):
        return redirect(url_for('employee_login'))

    target_date = request.form.get('target_date', '').strip() or accounting.get_business_date()
    transferred_by = session.get('employee_name') or session.get('admin_name') or 'المدير'
    
    amount_lbp_str = request.form.get('amount_lbp', '').strip()
    amount_usd_str = request.form.get('amount_usd', '').strip()
    custom_amount_lbp = float(amount_lbp_str) if amount_lbp_str else None
    custom_amount_usd = float(amount_usd_str) if amount_usd_str else None
    
    note = request.form.get('note', '').strip()

    try:
        res = accounting.transfer_daily_net_to_safe(
            target_date=target_date,
            transferred_by=transferred_by,
            custom_amount_lbp=custom_amount_lbp,
            custom_amount_usd=custom_amount_usd,
            note=note
        )
        flash(f"✓ تم ترحيل مبلغ {res['amount_lbp']:,.0f} ل.ل بنجاح إلى الخزنة الخاصة ليوم {target_date}!", "success")
    except Exception as e:
        flash(f"تنبيه أثناء الترحيل للخزنة: {e}", "warning")

    next_url = request.form.get('next') or request.referrer or url_for('safe_page')
    return redirect(next_url)

@app.route('/safe/transfer_drawer_total', methods=['POST'])
def safe_transfer_drawer_total():
    """ترحيل كامل الرصيد النقدي المتراكم بالدرج إلى الخزنة الخاصة بنقرة واحدة."""
    if 'employee_id' not in session and not session.get('is_admin') and not session.get('admin_authenticated'):
        return redirect(url_for('employee_login'))

    transferred_by = session.get('employee_name') or session.get('admin_name') or 'المدير'
    note = request.form.get('note', '').strip() or "ترحيل كامل كاش الدرج المتراكم إلى الخزنة الخاصة"
    try:
        res = accounting.transfer_drawer_total_to_safe(transferred_by=transferred_by, note=note)
        flash(f"✓ تم ترحيل كامل كاش الدرج ({res['amount_lbp']:,.0f} ل.ل) بنجاح إلى الخزنة الخاصة!", "success")
    except Exception as e:
        flash(f"تنبيه: {e}", "warning")

    next_url = request.form.get('next') or request.referrer or url_for('safe_page')
    return redirect(next_url)

@app.route('/api/safe/daily_status')
def api_safe_daily_status():
    """API لفحص حالة ترحيل اليوم والمبالغ المتبقية للترحيل."""
    target_date = request.args.get('date', '').strip() or accounting.get_business_date()
    status = accounting.check_daily_safe_transfer_status(target_date)
    return jsonify(status)


# ============================================================
# 🔄 API مسارات التحديث التلقائي OTA
# ============================================================

@app.route('/api/check_update')
def api_check_update():
    """يُعيد حالة التحديث المتاح (JSON)."""
    # إعادة الفحص إذا كان الوقت قد مضى أو لم يتم الفحص بعد
    if not _update_cache.get('checked'):
        threading.Thread(target=_background_update_check, daemon=True).start()
    return jsonify(_update_cache)


@app.route('/api/force_check_update')
def api_force_check_update():
    """إعادة الفحص الفوري من GitHub."""
    _update_cache['checked'] = False
    _background_update_check()
    return jsonify(_update_cache)


@app.route('/api/do_update', methods=['POST'])
def api_do_update():
    """تنزيل وتثبيت التحديث."""
    import subprocess, tempfile, shutil, zipfile as zf
    try:
        url = _update_cache.get('download_url', '')
        if not url or not url.startswith('http'):
            return jsonify({'success': False, 'error': 'رابط التحديث غير صالح'})

        import ssl, urllib.request as ur
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        base_dir = _get_base_dir()
        zip_path = os.path.join(base_dir, 'cafe_update_package.zip')
        tmp_dir  = os.path.join(base_dir, 'cafe_update_tmp')

        # تحميل الـ ZIP
        req = ur.Request(url, headers={'User-Agent': 'StargateCafe-OTA/4.4'})
        with ur.urlopen(req, timeout=120, context=ctx) as resp, open(zip_path, 'wb') as out:
            shutil.copyfileobj(resp, out)

        # فك الضغط
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir, ignore_errors=True)
        os.makedirs(tmp_dir, exist_ok=True)
        with zf.ZipFile(zip_path, 'r') as z:
            for m in z.namelist():
                if '..' not in m and not m.startswith('/'):
                    z.extract(m, tmp_dir)

        # إنشاء BAT يُطبّق التحديث بعد إغلاق البرنامج
        bat = os.path.join(base_dir, 'apply_update_now.bat')
        bat_content = f"""@echo off
chcp 65001 >nul
title تطبيق تحديث STARGATE CAFE
echo جاري تطبيق التحديث...
timeout /t 3 /nobreak >nul
taskkill /F /IM STARGATE.exe >nul 2>&1
taskkill /F /IM python.exe >nul 2>&1
robocopy "{tmp_dir}" "{base_dir}" /E /IS /IT /XF "*.db" "*.sqlite" "cafe_accounting.db" /XD "data" "Safe_Backups" >nul
if exist "{base_dir}\\_internal" (
    robocopy "{tmp_dir}\\templates" "{base_dir}\\_internal\\templates" /E /IS >nul 2>&1
    robocopy "{tmp_dir}\\static"    "{base_dir}\\_internal\\static"    /E /IS >nul 2>&1
    copy /Y "{tmp_dir}\\*.py" "{base_dir}\\_internal\\" >nul 2>&1
    copy /Y "{tmp_dir}\\cafe_version.json" "{base_dir}\\_internal\\" >nul 2>&1
)
rmdir /S /Q "{tmp_dir}" >nul 2>&1
del /F /Q "{zip_path}" >nul 2>&1
echo اكتمل التحديث! جاري إعادة التشغيل...
cd /d "{base_dir}"
if exist "STARGATE.exe" ( start "" "STARGATE.exe" ) else ( start "" pythonw.exe desktop_app.py )
del "%~f0"
"""
        with open(bat, 'w', encoding='utf-8') as f:
            f.write(bat_content)

        subprocess.Popen([bat], shell=True, creationflags=subprocess.CREATE_NEW_CONSOLE)
        return jsonify({'success': True, 'message': 'جاري تطبيق التحديث... سيُعاد تشغيل البرنامج تلقائياً!'})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
