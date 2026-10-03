# -*- coding: utf-8 -*-
from PIL import Image, ImageOps, ImageDraw
import io, base64, urllib.request
from werkzeug.utils import secure_filename
import os
import secrets
import sys
import json
import threading
from datetime import datetime, timedelta
from flask import (
    Flask, render_template, render_template_string,
    request, redirect, url_for, flash, jsonify,
    session, send_file, Response, abort
)
import database
from database import init_db, get_db, reset_operational_data, write_audit_log
import accounting
from logger import app_logger as logger, log_audit

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
    """يتحقق من التحديثات في الخلفية - HTTPS verified."""
    import ssl, urllib.request as ur, json as js, base64 as b64
    # Use default SSL context with proper certificate verification
    ctx = ssl.create_default_context()
    # Do NOT disable hostname check or certificate verification in production

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
            with ur.urlopen(req, timeout=6) as r:
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

import secrets

def generate_csrf_token():
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_hex(32)
    return session['_csrf_token']

@app.context_processor
def inject_global_helpers():
    return dict(
        csrf_token=generate_csrf_token,
        get_active_coffee_batch=accounting.get_active_coffee_batch,
        get_coffee_beans_stock=accounting.get_coffee_beans_stock
    )

@app.before_request
def csrf_protect():
    if app.config.get('TESTING'):
        return
    if request.method in ('POST', 'PUT', 'DELETE', 'PATCH'):
        if request.endpoint in ('employee_login', 'admin_login'):
            return
        token = request.headers.get('X-CSRFToken') or request.form.get('csrf_token')
        if not token and request.is_json:
            token = (request.get_json(silent=True) or {}).get('csrf_token')
        
        session_token = session.get('_csrf_token')
        if session_token and token:
            if not secrets.compare_digest(str(token), str(session_token)):
                if request.is_json:
                    return jsonify({'success': False, 'message': 'رمز الحماية CSRF غير صالح'}), 403
                flash('رمز الحماية غير صالح، يرجى المحاولة ثانية', 'warning')
                return redirect(request.referrer or url_for('index'))

@app.after_request
def add_no_cache_headers(response):
    # Only force no-cache on dynamic HTML/API pages; allow browser to cache static assets
    if request.path.startswith('/static/'):
        response.headers["Cache-Control"] = "public, max-age=86400"
    else:
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
            # Studio Cutout: flood-fill corner white areas to transparent alpha
            try:
                from PIL import ImageDraw as _ImageDraw
                for pt in [(0, 0), (w-1, 0), (0, h-1), (w-1, h-1), (w//2, 0), (w//2, h-1)]:
                    if img.getpixel(pt)[3] > 0 and sample_img.getpixel(pt)[0] > 220:
                        _ImageDraw.floodfill(img, pt, (0, 0, 0, 0), thresh=35)
            except Exception as e:
                logger.warning("Image background removal failed: %s", e)

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
        logger.exception("Image processing error: %s", e)
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


# ── Secret Key (from env var in production, random fallback in dev) ──
_SECRET_KEY_FILE = os.path.join(database.DB_DIR, '.secret_key')

def _load_or_create_secret_key() -> str:
    """Load persisted secret key or generate+save a new one."""
    if os.environ.get('STARGATE_SECRET_KEY'):
        return os.environ['STARGATE_SECRET_KEY']
    try:
        if os.path.exists(_SECRET_KEY_FILE):
            with open(_SECRET_KEY_FILE, 'r') as f:
                key = f.read().strip()
                if key and len(key) >= 32:
                    return key
        # Generate new persistent key
        key = secrets.token_hex(32)
        os.makedirs(os.path.dirname(_SECRET_KEY_FILE), exist_ok=True)
        with open(_SECRET_KEY_FILE, 'w') as f:
            f.write(key)
        return key
    except Exception:
        return secrets.token_hex(32)  # ephemeral fallback

app.secret_key = _load_or_create_secret_key()
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

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

@app.template_filter('clean_phone_for_whatsapp')
def clean_phone_for_whatsapp(phone):
    if not phone:
        return ''
    p = re.sub(r'\D', '', str(phone))
    if p.startswith('0'):
        p = p[1:]
    if len(p) == 7 or len(p) == 8:
        p = '961' + p
    return p



from functools import wraps

def login_required(f):
    """Require any authenticated employee (admin or cashier)."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'employee_id' not in session and not session.get('admin_authenticated'):
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({'error': 'Authentication required', 'code': 401}), 401
            flash("⚠️ يرجى تسجيل الدخول أولاً", "warning")
            return redirect(url_for('employee_login', next=request.path))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    """Require admin/owner level authentication."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        is_admin = (
            session.get('is_admin') or
            session.get('admin_authenticated') or
            session.get('employee_role') == 'admin'
        )
        if not is_admin:
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({'error': 'Admin access required', 'code': 403}), 403
            flash("⚠️ عذراً، هذه الصفحة مخصصة لمدير النظام والإدارة فقط!", "danger")
            return redirect(url_for('admin_login', next=request.path))
        return f(*args, **kwargs)
    return decorated_function

def generate_csrf_token():
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_hex(24)
    return session['_csrf_token']

app.jinja_env.globals['csrf_token'] = generate_csrf_token

@app.before_request
def csrf_protect():
    # Only validate state-changing HTTP methods
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        session_token = session.get('_csrf_token')
        submitted_token = (
            request.form.get('csrf_token') or
            request.headers.get('X-CSRFToken') or
            request.headers.get('X-CSRF-Token') or
            (request.is_json and request.get_json(silent=True) and request.get_json(silent=True).get('csrf_token'))
        )
        if session_token and submitted_token and secrets.compare_digest(session_token, submitted_token):
            return None  # valid CSRF match

        # Allow same-origin localhost/desktop requests
        origin = request.headers.get('Origin') or request.headers.get('Referer') or ''
        is_same_origin = (
            request.remote_addr in ('127.0.0.1', '::1') or
            any(h in origin for h in ('127.0.0.1', 'localhost', request.host or ''))
        )
        if is_same_origin:
            if not session_token:
                session['_csrf_token'] = secrets.token_hex(24)
            return None
        
        if submitted_token and session_token and secrets.compare_digest(session_token, submitted_token):
            return None
            
        if request.endpoint in ('employee_login', 'admin_login'):
            return None

        # CSRF failed
        if request.is_json or request.path.startswith('/api/'):
            return jsonify({'error': 'CSRF verification failed', 'code': 403}), 403
        flash("⚠️ انتهت صلاحية الجلسة أو تعذر التحقق من الأمان (CSRF).", "danger")
        return redirect(request.referrer or url_for('index'))

@app.before_request
def ensure_default_session():
    public_endpoints = ['employee_login', 'admin_login', 'static', 'favicon']
    if request.endpoint and any(ep in (request.endpoint or '') for ep in public_endpoints):
        return
    if 'employee_id' not in session and not session.get('admin_authenticated'):
        if request.endpoint and request.endpoint.startswith('api_'):
            pass
        elif request.endpoint and request.endpoint not in ('employee_login', 'admin_login'):
            pass

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

# ----------------- 0. EXECUTIVE ERP DASHBOARD -----------------

@app.route('/dashboard')
@login_required
def dashboard_page():
    """Executive ERP Dashboard displaying KPIs, real P&L profit, Safe Balance, and charts."""
    today_str = accounting.get_business_date()
    daily_summary = accounting.get_daily_summary(today_str)
    safe_bal = accounting.get_safe_balance()
    drawer_stat = accounting.get_drawer_cash_status()
    pnl = accounting.get_comprehensive_financial_statement(start_date=today_str, end_date=today_str)
    
    # Top Products Today
    breakdown_data = accounting.get_product_sales_breakdown(target_date=today_str)
    products_breakdown = breakdown_data.get('products_list', []) if isinstance(breakdown_data, dict) else (breakdown_data or [])
    top_products = sorted(products_breakdown, key=lambda x: float(x.get('total_lbp') or 0), reverse=True)[:6]
    
    # Low stock items
    stock_items = accounting.get_inventory_stock()
    low_stock = [i for i in stock_items if i.get('track_stock') and float(i.get('stock_qty') or 0) <= float(i.get('low_stock_limit') or 5)]
    
    category_sales = accounting.get_category_sales_distribution(today_str)
    hourly_sales = accounting.get_hourly_sales_distribution(today_str)

    return render_template(
        'dashboard.html',
        summary=daily_summary,
        safe_balance=safe_bal,
        drawer_status=drawer_stat,
        pnl=pnl,
        top_products=top_products,
        low_stock_items=low_stock,
        category_sales=category_sales,
        hourly_sales=hourly_sales,
        today_str=today_str,
        active_page='dashboard'
    )

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
    top_selling_items = accounting.get_top_selling_items(limit=15)
    top_seller_ids = [it['id'] for it in top_selling_items if (it.get('total_sold') or 0) > 0]
    if not top_seller_ids and items:
        top_seller_ids = [it['id'] for it in items[:6]]

    return render_template(
        'index.html',
        categories=categories,
        items=items,
        summary=daily_summary,
        recent_orders=recent_orders,
        recent_pc_logs=recent_pc_logs,
        open_tabs=open_tabs,
        top_seller_ids=top_seller_ids,
        active_page='pos'
    )

@app.route('/order/create', methods=['POST'])
@login_required
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

        if not items_list:
            if request.is_json:
                return jsonify({'success': False, 'message': 'الفاتورة فارغة'}), 400
            flash("⚠️ لا يمكن حفظ فاتورة فارغة بدون أصناف", "warning")
            return redirect(url_for('index'))

        order_data = {
            'customer_name': customer_name,
            'notes': notes,
            'payment_method': payment_method,
            'phone': phone,
            'employee_id': session.get('employee_id'),
            'employee_name': session.get('employee_name', 'كاشير')
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
        logger.exception("Error in order_create: %s", e)
        if request.is_json:
            return jsonify({'success': False, 'message': str(e)}), 500
        flash(f"خطأ: {str(e)}", "danger")
        return redirect(url_for('index'))

@app.route('/tab/save', methods=['POST'])
@login_required
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
        logger.exception("Error in tab_save: %s", e)
        if request.is_json:
            return jsonify({'success': False, 'message': str(e)}), 500
        flash(f"خطأ: {str(e)}", "danger")
        return redirect(url_for('index'))

@app.route('/tab/<int:tab_id>/delete', methods=['POST'])
@login_required
def tab_delete(tab_id):
    """Cancel / Delete an open customer tab."""
    accounting.delete_tab(tab_id)
    if request.is_json:
        return jsonify({'success': True, 'message': 'تم إلغاء حساب الزبون'})
    flash("تم إلغاء حساب الزبون", "info")
    return redirect(url_for('index'))

@app.route('/pc/click', methods=['POST'])
@login_required
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
@login_required
def quick_custom_sale():
    """Instant manual sale with typed name and price."""
    name = request.form.get('item_name', 'مبيعات يدوية').strip() or 'مبيعات يدوية'
    price_lbp = float(request.form.get('price_lbp') or 0)
    qty = int(request.form.get('quantity') or 1)

    if price_lbp <= 0:
        flash("يرجى إدخال سعر صحيح", "danger")
        return redirect(url_for('index'))

    items_list = [{'name': name, 'price_lbp': price_lbp, 'quantity': qty, 'item_id': None}]
    success, res = accounting.create_order({
        'customer_name': 'زبون كاش',
        'employee_id': session.get('employee_id'),
        'employee_name': session.get('employee_name', 'كاشير')
    }, items_list)
    if success:
        flash(f"تم تسجيل {name} بمبلغ {price_lbp * qty:,.0f} ل.ل بنجاح 💰", "success")
    else:
        flash(f"خطأ: {res}", "danger")
    return redirect(url_for('index'))

@app.route('/order/<int:order_id>/receipt', endpoint='order_receipt')
@app.route('/order/<int:order_id>/receipt', endpoint='print_receipt')
@login_required
def order_receipt(order_id):
    """Printable Thermal Receipt for Cafe."""
    order = accounting.get_order_details(order_id)
    if not order:
        flash("الفاتورة غير موجودة", "danger")
        return redirect(url_for('index'))
    return render_template('print_receipt.html', order=order)

# ----------------- 3. CUSTOMER DEBTS LEDGER (سجل ديون الزبائن والآجل) -----------------

@app.route('/debts')
@login_required
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
@login_required
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
@login_required
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
@login_required
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
@app.route('/debt/<int:debt_id>/cancel', methods=['POST'])
@admin_required
def debt_delete(debt_id):
    """Delete / Cancel a debt record safely with full audit trail."""
    reason = request.form.get('cancel_reason', '').strip() or 'إلغاء من لوحة الديون'
    cancelled_by = session.get('employee_name') or 'المدير'
    ok, msg = accounting.delete_debt(debt_id, cancelled_by=cancelled_by, reason=reason)
    if ok:
        flash(f"✓ {msg}", "success")
    else:
        flash(f"⚠️ {msg}", "danger")
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
            cursor.execute("SELECT * FROM employees WHERE role = 'admin' AND is_active = 1")
            admin_rows = cursor.fetchall()
            conn.close()
            for r in admin_rows:
                pwd = r['password'] or ''
                pin = r['pin'] or ''
                if (pwd and database.verify_password(entered_secret, pwd)) or \
                   (pin and database.verify_password(entered_secret, pin)):
                    authenticated = True
                    emp_match = dict(r)
                    break
        if not authenticated and accounting.verify_admin_password(entered_secret):
            authenticated = True

        # First run check: if system has no admin password and no admin employees, let user set it
        if not authenticated:
            admin_hash = accounting.get_admin_password_hash()
            conn = database.get_db()
            has_admins = conn.execute("SELECT COUNT(*) FROM employees WHERE role='admin' AND is_active=1").fetchone()[0]
            conn.close()
            if not admin_hash and has_admins == 0:
                if entered_secret and len(entered_secret) >= 4:
                    accounting.update_admin_password(entered_secret)
                    authenticated = True
                    flash("✅ تم إنشاء وتعيين كلمة سر الإدارة لأول مرة بنجاح!", "success")

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
@admin_required
def admin_change_password():
    """Change Admin Password dynamically."""
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
        write_audit_log(session.get('employee_name', 'Admin'), 'CHANGE_ADMIN_PASSWORD', 'settings', 1)
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
@admin_required
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
@login_required
def expense_quick_add():
    """تسجيل مصروف سريع من درج الكاشير بواسطة الموظف أو الإدارة."""
    emp_id = session.get('employee_id')
    emp_name = session.get('employee_name', 'كاشير')
    is_admin = session.get('is_admin') or session.get('admin_authenticated')

    if request.is_json:
        data = request.get_json(silent=True) or {}
        title = data.get('title', '').strip()
        amount = float(data.get('amount_lbp') or 0)
        category = data.get('category', 'مصاريف تشغيلية')
        notes = data.get('notes', '')
        source = data.get('source', 'drawer')
    else:
        title = request.form.get('title', '').strip()
        amount = float(request.form.get('amount_lbp') or 0)
        category = request.form.get('category', 'مصاريف تشغيلية')
        notes = request.form.get('notes', '')
        source = request.form.get('source', 'drawer')

    # الدفع من الخزنة محصور بالإدارة فقط
    if source == 'safe' and not is_admin:
        if request.is_json:
            return jsonify({'success': False, 'message': '⚠️ الصرف من الخزنة مخصص للإدارة فقط'}), 403
        flash("⚠️ الصرف من الخزنة الخاصة مخصص للإدارة فقط", "danger")
        return redirect(request.referrer or url_for('index'))

    if not title or amount <= 0:
        if request.is_json:
            return jsonify({'success': False, 'message': '⚠️ يرجى إدخال بيان المصروف والمبلغ بشكل صحيح'}), 400
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
        msg = f"✅ تم تسجيل مصروف [{title}] بقيمة {amount:,.0f} ل.ل بنجاح من {src_label}"
        if request.is_json:
            return jsonify({'success': True, 'message': msg, 'expense_id': res})
        flash(msg, "success")
    else:
        err_msg = f"خطأ في تسجيل المصروف: {res}"
        if request.is_json:
            return jsonify({'success': False, 'message': err_msg}), 400
        flash(err_msg, "danger")
    return redirect(request.referrer or url_for('index'))

# ----------------- ☕ COFFEE BEANS & CUP YIELD MANAGEMENT -----------------

@app.route('/coffee/hub', endpoint='coffee_hub')
@app.route('/coffee-hub', endpoint='coffee_hub_page')
@login_required
def coffee_hub():
    """لوحة تتبع وإدارة حبوب القهوة، الفناجين المبيعة، التالف، ورسمال الفنجان."""
    summary = accounting.get_coffee_dashboard_summary()
    settings = accounting.get_settings()
    return render_template(
        'coffee_hub.html',
        summary=summary,
        settings=settings,
        active_page='coffee_hub'
    )

@app.route('/coffee/open-bag', methods=['POST'])
@login_required
def coffee_open_bag():
    """فتح كيلو قهوة جديد للاستعمال مع إغلاق الكيلو السابق تلقائياً واحتساب إنتاجيته وأرباحه والتالف."""
    emp_name = session.get('employee_name', 'كاشير')
    if request.is_json:
        data = request.get_json(silent=True) or {}
        cost_lbp = data.get('cost_per_kg_lbp')
        cost_usd = data.get('cost_per_kg_usd')
        notes = data.get('notes', '')
    else:
        cost_lbp = request.form.get('cost_per_kg_lbp')
        cost_usd = request.form.get('cost_per_kg_usd')
        notes = request.form.get('notes', '')

    cost_lbp = float(cost_lbp) if cost_lbp and float(cost_lbp) > 0 else None
    cost_usd = float(cost_usd) if cost_usd and float(cost_usd) > 0 else None

    ok, res = accounting.open_coffee_bag(cost_kg_lbp=cost_lbp, cost_kg_usd=cost_usd, employee_name=emp_name, notes=notes, auto_close_previous=True)
    if request.is_json:
        if ok:
            prev = res.get('closed_previous')
            prev_msg = ""
            if prev:
                prev_msg = f" (تم إغلاق الكيلو السابق [{prev['batch_code']}] تلقائياً: أنتج {prev['total_cups']} فنجان - صافي ربح {prev['net_profit_lbp']:,.0f} ل.ل)"
            return jsonify({'success': True, 'message': f"تم فتح كيلو قهوة جديد بنجاح [{res['batch_code']}]{prev_msg}", 'data': res})
        return jsonify({'success': False, 'message': str(res)}), 400

    if ok:
        prev = res.get('closed_previous')
        if prev:
            msg = (
                f"☕ تم فتح كيلو جديد برقم [{res['batch_code']}] بنجاح! "
                f"(تم إغلاق الكيلو السابق [{prev['batch_code']}] تلقائياً: "
                f"أنتج {prev['total_cups']} فنجان | المبيعة: {prev['cups_sold']} | التالفة: {prev['cups_damaged']} "
                f"| تكلفة الفنجان: {prev['cost_per_cup_lbp']:,.0f} ل.ل | صافي الربح: {prev['net_profit_lbp']:,.0f} ل.ل | خسارة التلف: {prev.get('loss_damaged_lbp', 0):,.0f} ل.ل)"
            )
        else:
            msg = f"☕ تم فتح كيلو قهوة جديد بنجاح برقم [{res['batch_code']}] وبدء احتساب الفناجين المبيعة والتالفة تلقائياً من 0!"
        flash(msg, "success")
    else:
        flash(f"⚠️ {res}", "danger")
    return redirect(request.referrer or url_for('coffee_hub'))

@app.route('/coffee/close-bag', methods=['POST'])
@login_required
def coffee_close_bag():
    """إنهاء وإغلاق الكيلو المفتوح وحساب الإنتاجية ورسمال الفنجان الدقيق وصافي الربح والتالف."""
    emp_name = session.get('employee_name', 'كاشير')
    batch_id = request.form.get('batch_id')
    notes = request.form.get('notes', '')

    batch_id = int(batch_id) if batch_id else None
    ok, res = accounting.close_coffee_bag(batch_id=batch_id, employee_name=emp_name, notes=notes)
    if ok:
        flash(
            f"✅ تم إغلاق الكيلو [{res['batch_code']}] بنجاح! "
            f"أنتج الكيلو {res['total_cups']} فنجان "
            f"(المبيعة: {res['cups_sold']} | التالفة: {res['cups_damaged']}) - "
            f"تكلفة الفنجان: {res['cost_per_cup_lbp']:,.0f} ل.ل - "
            f"صافي الربح: {res['net_profit_lbp']:,.0f} ل.ل - "
            f"خسارة التلف: {res.get('loss_damaged_lbp', 0):,.0f} ل.ل",
            "success"
        )
    else:
        flash(f"⚠️ {res}", "danger")
    return redirect(request.referrer or url_for('coffee_hub'))

@app.route('/coffee/log-waste', methods=['POST'])
@login_required
def coffee_log_waste():
    """تسجيل فنجان تالف أثناء التحضير أو سكب."""
    emp_name = session.get('employee_name', 'كاشير')
    if request.is_json:
        data = request.get_json(silent=True) or {}
        qty = int(data.get('qty') or 1)
        reason = data.get('reason', 'تلف أثناء التحضير')
        notes = data.get('notes', '')
    else:
        qty = int(request.form.get('qty') or 1)
        reason = request.form.get('reason', 'تلف أثناء التحضير')
        notes = request.form.get('notes', '')

    ok, res = accounting.record_coffee_waste(qty=qty, reason=reason, employee_name=emp_name, notes=notes)
    if request.is_json:
        if ok:
            return jsonify({'success': True, 'message': f"تم تسجيل {qty} فنجان تالف كخسارة على الكيلو بنجاح", 'data': res})
        return jsonify({'success': False, 'message': str(res)}), 400

    if ok:
        flash(f"⚠️ تم تسجيل {qty} فنجان تالف كخسارة على الكيلو بنجاح (خسارة التكلفة: {res['loss_lbp']:,.0f} ل.ل دون احتساب ربح)", "warning")
    else:
        flash(f"خطأ: {res}", "danger")
    return redirect(request.referrer or url_for('coffee_hub'))

@app.route('/coffee/update-stock', methods=['POST'])
@login_required
def coffee_update_stock():
    """تعديل رصيد حبوب القهوة (كم كيلو بن متوفر بالمخزن مع السعر الموحد)."""
    stock_kg = float(request.form.get('stock_kg') or 0.0)
    cost_lbp = float(request.form.get('cost_per_kg_lbp') or 0.0)
    cost_usd = float(request.form.get('cost_per_kg_usd') or 0.0)
    tot_cost = float(request.form.get('total_cost_lbp') or 0.0)

    ok, msg = accounting.update_coffee_beans_stock(stock_kg=stock_kg, cost_per_kg_lbp=cost_lbp, cost_per_kg_usd=cost_usd, total_cost_lbp=tot_cost)
    if ok:
        flash(f"✅ {msg}", "success")
    else:
        flash(f"خطأ: {msg}", "danger")
    return redirect(request.referrer or url_for('coffee_hub'))

@app.route('/api/coffee/status', methods=['GET'])
@login_required
def api_coffee_status():
    """API لحظي للحصول على حالة الكيلو المفتوح ورصيد البن."""
    summary = accounting.get_coffee_dashboard_summary()
    return jsonify({
        'success': True,
        'active_batch': summary.get('active_batch'),
        'stock_kg': (summary.get('stock_info') or {}).get('stock_kg', 0.0)
    })

@app.route('/expense/<int:expense_id>/cancel', methods=['POST'])
@app.route('/expense/<int:expense_id>/delete', methods=['POST'])
@admin_required
def expense_delete(expense_id):
    """إلغاء مصروف بطريقة غير مدمرة (Non-Destructive) مع توثيق السبب."""
    reason = request.form.get('cancel_reason', '').strip() or 'إلغاء من لوحة الإدارة'
    cancelled_by = session.get('employee_name') or 'المدير'
    ok, msg = accounting.cancel_expense(expense_id, cancelled_by=cancelled_by, reason=reason)
    if ok:
        flash(f'✓ {msg}', 'success')
    else:
        flash(f'⚠️ {msg}', 'warning')
    return redirect(url_for('admin_panel'))


@app.route('/pc/log/<int:log_id>/delete', methods=['POST'])
@admin_required
def pc_log_delete(log_id):
    accounting.delete_pc_log(log_id)
    write_audit_log(
        actor=session.get('employee_name', 'Admin'),
        action='DELETE_PC_LOG',
        table_name='pc_usage_logs',
        record_id=log_id,
        reason='Gaming log deleted by admin'
    )
    flash("تم حذف سجل GAMING", "info")
    return redirect(url_for('admin_panel'))

@app.route('/order/<int:order_id>/cancel', methods=['POST'])
@app.route('/order/<int:order_id>/delete', methods=['POST'])
@admin_required
def order_delete(order_id):
    """إلغاء فاتورة مع توثيق السبب واستعادة المخزون بشكل تدقيقي آمن."""
    reason = request.form.get('cancel_reason', '').strip() or 'إلغاء من لوحة الإدارة'
    cancelled_by = session.get('employee_name') or 'المدير'
    ok, msg = accounting.cancel_order(order_id, cancelled_by=cancelled_by, reason=reason)
    if ok:
        flash(f'✓ {msg}', 'success')
    else:
        flash(f'⚠️ {msg}', 'warning')
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

@app.route('/categories')
@admin_required
def categories_page():
    """صفحة إدارة الأقسام والتصنيفات وتنظيم شاشة الكاشير والربط بالبن."""
    categories = accounting.get_categories_with_items()
    settings = accounting.get_settings()
    return render_template(
        'categories.html',
        categories=categories,
        settings=settings,
        active_page='categories'
    )

@app.route('/menu/category/add', methods=['POST'])
@app.route('/categories/add', methods=['POST'])
@admin_required
def menu_category_add():
    name = request.form.get('name', '').strip()
    icon = request.form.get('icon', '☕').strip() or '☕'
    sort_order = request.form.get('sort_order', 0)
    success, res = accounting.add_category(name, icon, sort_order)
    if success:
        flash(f"تمت إضافة القسم [{name}] بنجاح 🏷️", "success")
    else:
        flash(f"خطأ: {res}", "danger")
    return redirect(request.referrer or url_for('categories_page'))

@app.route('/menu/category/<int:cat_id>/edit', methods=['POST'])
@app.route('/categories/<int:cat_id>/edit', methods=['POST'])
@admin_required
def menu_category_edit(cat_id):
    name = request.form.get('name', '').strip()
    icon = request.form.get('icon', '☕').strip() or '☕'
    sort_order = request.form.get('sort_order', 0)
    success, res = accounting.update_category(cat_id, name, icon, sort_order)
    if success:
        flash("تم تعديل القسم بنجاح", "success")
    else:
        flash(f"خطأ: {res}", "danger")
    return redirect(request.referrer or url_for('categories_page'))

@app.route('/menu/category/<int:cat_id>/delete', methods=['POST'])
@app.route('/categories/<int:cat_id>/delete', methods=['POST'])
@admin_required
def menu_category_delete(cat_id):
    accounting.delete_category(cat_id)
    write_audit_log(session.get('employee_name', 'Admin'), 'DELETE_CATEGORY', 'cafe_categories', cat_id)
    flash("تم حذف القسم وجميع أصنافه بنجاح", "info")
    return redirect(request.referrer or url_for('categories_page'))

@app.route('/categories/reorder/<int:cat_id>/<direction>', methods=['POST'])
@admin_required
def category_reorder(cat_id, direction):
    """تحريك القسم لأعلى أو لأسفل لترتيب الأزرار في شاشة الكاشير."""
    ok, msg = accounting.reorder_category(cat_id, direction)
    if request.is_json:
        return jsonify({'success': ok, 'message': msg})
    if ok:
        flash(msg, "success")
    else:
        flash(msg, "warning")
    return redirect(request.referrer or url_for('categories_page'))

@app.route('/categories/reorder-all', methods=['POST'])
@admin_required
def categories_reorder_all():
    """حفظ ترتيب جميع الأقسام المحددة بالترتيب الجديد."""
    data = request.get_json(silent=True) or {}
    order_ids = data.get('category_ids') or request.form.getlist('category_ids[]')
    ok, msg = accounting.save_categories_order(order_ids)
    if request.is_json:
        return jsonify({'success': ok, 'message': msg})
    flash(msg, "success" if ok else "danger")
    return redirect(request.referrer or url_for('categories_page'))

@app.route('/item/<int:item_id>/move-category', methods=['POST'])
@admin_required
def item_move_category(item_id):
    """نقل الصنف إلى قسم وتصنيف آخر."""
    if request.is_json:
        data = request.get_json(silent=True) or {}
        new_cat_id = data.get('category_id')
    else:
        new_cat_id = request.form.get('category_id')
    try:
        new_cat_id = int(new_cat_id)
    except Exception:
        new_cat_id = None
        
    if not new_cat_id:
        if request.is_json:
            return jsonify({'success': False, 'message': 'القسم المستهدف غير صالح'}), 400
        flash('يرجى اختيار القسم المستهدف', 'warning')
        return redirect(request.referrer or url_for('categories_page'))
        
    ok, msg = accounting.move_item_to_category(item_id, new_cat_id)
    if request.is_json:
        return jsonify({'success': ok, 'message': msg})
    if ok:
        flash(f"✅ {msg}", "success")
    else:
        flash(f"⚠️ {msg}", "danger")
    return redirect(request.referrer or url_for('categories_page'))

@app.route('/item/<int:item_id>/toggle-coffee-link', methods=['POST'])
@admin_required
def item_toggle_coffee_link(item_id):
    """تفعيل أو إلغاء ربط الصنف بخصم كيلو البن (كيس القهوة)."""
    ok, val = accounting.toggle_coffee_bean_link(item_id)
    if ok:
        state_txt = "يخصم من كيلو البن ☕" if val == 1 else "لا يخصم من كيلو البن (مشروب عادي)"
        msg = f"تم تحديث الصنف: الآن {state_txt}"
        if request.is_json:
            return jsonify({'success': True, 'is_coffee_bean_linked': val, 'message': msg})
        flash(f"✅ {msg}", "success")
    else:
        msg = f"خطأ: {val}"
        if request.is_json:
            return jsonify({'success': False, 'message': msg}), 400
        flash(msg, "danger")
    return redirect(request.referrer or url_for('categories_page'))

@app.route('/item/<int:item_id>/reorder/<direction>', methods=['POST'])
@login_required
def item_reorder(item_id, direction):
    """تحريك الصنف للأمام أو للخلف على شاشة الكاشير لترتيب أماكن المنتجات."""
    cat_id = request.args.get('category_id', type=int) or (request.get_json(silent=True) or {}).get('category_id')
    ok, msg = accounting.reorder_item(item_id, direction, category_id=cat_id)
    if request.is_json:
        return jsonify({'success': ok, 'message': msg})
    if ok:
        flash(f"✅ {msg}", "success")
    else:
        flash(f"⚠️ {msg}", "warning")
    return redirect(request.referrer or url_for('index'))

@app.route('/item/<int:item_id>/set-order', methods=['POST'])
@login_required
def item_set_order(item_id):
    """تحديد رقم ترتيب الصنف مباشرة."""
    if request.is_json:
        data = request.get_json(silent=True) or {}
        sort_order = data.get('sort_order', 0)
    else:
        sort_order = request.form.get('sort_order', 0)
    ok, msg = accounting.set_item_sort_order(item_id, sort_order)
    if request.is_json:
        return jsonify({'success': ok, 'message': msg})
    flash(f"✅ {msg}", "success" if ok else "danger")
    return redirect(request.referrer or url_for('index'))

@app.route('/item/<int:item_id>/pin-top', methods=['POST'])
@login_required
def item_pin_top(item_id):
    """تثبيت الصنف في مقدمة شاشة الكاشير كأول صنف."""
    ok, msg = accounting.pin_item_to_top(item_id)
    if request.is_json:
        return jsonify({'success': ok, 'message': msg})
    flash(f"✅ {msg}", "success" if ok else "danger")
    return redirect(request.referrer or url_for('index'))

@app.route('/api/items/auto-sort-sales', methods=['POST'])
@login_required
def api_items_auto_sort_sales():
    """ترتيب أصناف الكاشير تلقائياً حسب الأكثر طلباً ومبيعاً."""
    ok, msg = accounting.auto_sort_items_by_sales()
    return jsonify({'success': ok, 'message': msg})

@app.route('/api/items/set-position', methods=['POST'])
@login_required
def api_items_set_position():
    """نقل الصنف مباشرة لموضع محدد (مثل الموضع 1 أو 2 أو 5)."""
    data = request.get_json(silent=True) or request.form
    item_id = int(data.get('item_id', 0))
    pos = int(data.get('position', 1))
    ok, msg = accounting.set_item_exact_position(item_id, pos)
    return jsonify({'success': ok, 'message': msg})

@app.route('/api/items/top-selling', methods=['GET'])
def api_top_selling_items():
    """واجهة برمجية لجلب أكثر الأصناف مبيعاً وطلباً لشاشة الكاشير."""
    limit = request.args.get('limit', 12, type=int)
    top_items = accounting.get_top_selling_items(limit=limit)
    return jsonify({'success': True, 'items': top_items})

@app.route('/menu/add', methods=['POST'])
@app.route('/menu/item/add', methods=['POST'])
@admin_required
def menu_item_add():
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
    return redirect(request.referrer or url_for('admin_panel'))

@app.route('/menu/item/<int:item_id>/edit', methods=['POST'])
@admin_required
def menu_item_edit(item_id):
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
            data['icon'] = current_icon
        elif not data.get('icon', '').strip():
            existing = accounting.get_item(item_id)
            if existing and existing.get('icon'):
                data['icon'] = existing['icon']

    success, res = accounting.update_item(item_id, data)
    if success:
        flash("تم تعديل الصنف والأسعار بنجاح", "success")
    else:
        flash(f"خطأ: {res}", "danger")
    return redirect(request.referrer or url_for('admin_panel'))

@app.route('/menu/<int:item_id>/delete', methods=['POST'])
@app.route('/menu/item/<int:item_id>/delete', methods=['POST'])
@admin_required
def menu_item_delete(item_id):
    accounting.delete_item(item_id)
    write_audit_log(session.get('employee_name', 'Admin'), 'DELETE_ITEM', 'cafe_items', item_id)
    flash("تم حذف الصنف من المنيو والمخزون", "info")
    return redirect(request.referrer or url_for('admin_panel'))

# ----------------- BACKUP, EXPORT & RESTORE (النسخ الاحتياطي واستيراد وتصدير البيانات) -----------------

@app.route('/backup/download')
@admin_required
def backup_download():
    """Download a full SQLite database backup file to user computer."""
    try:
        backup_path, backup_filename = database.create_backup_copy()
        return send_file(backup_path, as_attachment=True, download_name=backup_filename, mimetype='application/x-sqlite3')
    except Exception as e:
        logger.exception("Backup download failed: %s", e)
        flash(f"خطأ أثناء تصدير النسخة الاحتياطية: {str(e)}", "danger")
        return redirect(url_for('admin_panel'))

@app.route('/backup/restore', methods=['POST'])
@admin_required
def backup_restore():
    """Upload and restore database from a user backup file."""
    if 'backup_file' not in request.files:
        flash("يرجى اختيار ملف النسخة الاحتياطية أولاً", "danger")
        return redirect(url_for('admin_panel'))

    file = request.files['backup_file']
    if not file or file.filename == '':
        flash("لم يتم اختيار أي ملف", "danger")
        return redirect(url_for('admin_panel'))

    success, msg = database.restore_from_backup(file)
    if success:
        write_audit_log(session.get('employee_name', 'Admin'), 'RESTORE_BACKUP', 'database', reason=file.filename)
        flash(msg, "success")
    else:
        flash(msg, "danger")
    return redirect(url_for('admin_panel'))

@app.route('/export/menu/json')
@admin_required
def export_menu_json():
    """Download menu items & categories as JSON file."""
    data = accounting.export_menu_data()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"stargate_menu_{timestamp}.json"
    response = Response(json.dumps(data, ensure_ascii=False, indent=2), mimetype='application/json; charset=utf-8')
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    return response

@app.route('/import/menu', methods=['POST'])
@admin_required
def import_menu():
    """Import menu items & categories from uploaded JSON file."""
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
            write_audit_log(session.get('employee_name', 'Admin'), 'IMPORT_MENU', 'cafe_items')
            flash(msg, "success")
        else:
            flash(msg, "danger")
    except Exception as e:
        logger.exception("Error in import_menu: %s", e)
        flash(f"خطأ في قراءة ملف المنيو: {str(e)}", "danger")
    return redirect(url_for('admin_panel'))

@app.route('/export/sales/csv')
@admin_required
def export_sales_csv_route():
    """Export complete sales, debts, and expenses to Excel CSV."""
    csv_data = accounting.export_sales_csv()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"stargate_sales_report_{timestamp}.csv"
    response = Response(csv_data, mimetype='text/csv; charset=utf-8')
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    return response

@app.route('/export/system/json')
@admin_required
def export_system_json():
    """Download full system backup as JSON package."""
    data = accounting.export_full_system_data()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"stargate_full_backup_{timestamp}.json"
    response = Response(json.dumps(data, ensure_ascii=False, indent=2), mimetype='application/json; charset=utf-8')
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    return response

@app.route('/import/system/json', methods=['POST'])
@admin_required
def import_system_json():
    """Import full system backup from uploaded JSON file."""
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
            write_audit_log(session.get('employee_name', 'Admin'), 'IMPORT_SYSTEM_JSON', 'ALL')
            flash(msg, "success")
        else:
            flash(msg, "danger")
    except Exception as e:
        logger.exception("Error in import_system_json: %s", e)
        flash(f"خطأ أثناء استيراد البيانات: {str(e)}", "danger")
    return redirect(url_for('admin_panel'))

@app.route('/admin/factory-reset', methods=['POST'])
@app.route('/reset/data', methods=['POST'])
@admin_required
def admin_factory_reset():
    """Protected Factory Reset: requires admin PIN or password, auto-backup, and audit."""
    entered_pin = request.form.get('admin_pin', '').strip() or request.form.get('password', '').strip()
    
    # Strictly verify admin password or authenticated admin employee PIN
    is_valid_auth = accounting.verify_admin_password(entered_pin)
    if not is_valid_auth and entered_pin:
        emp = accounting.authenticate_employee(entered_pin, None)
        if emp and emp.get('role') == 'admin':
            is_valid_auth = True

    if not is_valid_auth:
        flash("⚠️ كلمة المرور أو رمز PIN غير صحيح! يرجى إدخال كلمة سر الإدارة لتنفيذ العملية", "danger")
        return redirect(url_for('admin_panel'))

    reset_type = request.form.get('reset_type', 'transactions_only')

    # If full reset, optionally check confirmation if sent by form
    confirm_text = (request.form.get('confirm_text') or '').strip().upper()
    if reset_type == 'full' and request.form.get('require_confirm') and confirm_text != 'RESET':
        flash("⚠️ للتأكيد على ضبط المصنع الشامل يرجى كتابة كلمة RESET في حقل التأكيد", "danger")
        return redirect(url_for('admin_panel'))

    # Auto backup current DB before performing any reset
    try:
        database.create_backup_copy()
    except Exception as e:
        logger.exception("Pre-reset backup: %s", e)

    actor_name = session.get('employee_name', 'المدير العام')
    success, msg = accounting.factory_reset(reset_type, admin_pin=entered_pin, actor=actor_name)
    if success:
        write_audit_log(
            actor=actor_name,
            action='FACTORY_RESET',
            table_name='ALL',
            reason=f"Reset type: {reset_type}"
        )
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
    stock_movements = accounting.get_stock_movements(limit=200)
    return render_template(
        'inventory.html',
        items=items,
        settings=settings,
        exchange_rate=float(settings.get('exchange_rate') or 89500.0),
        summary=summary,
        categories=categories,
        stock_movements=stock_movements,
        active_page='inventory',
        company_name=settings.get('company_name', 'STARGATE')
    )

@app.route('/inventory/export/csv')
@app.route('/export/inventory-csv')
@admin_required
def export_inventory_csv_route():
    """Export current stock and inventory list to CSV (Excel compatible with UTF-8 BOM)."""
    items = accounting.get_inventory_stock()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M')
    
    # Generate CSV with UTF-8 BOM for Arabic Excel support
    lines = ["\ufeffمعرف الصنف,اسم الصنف,التصنيف,النوع,سعر البيع (ل.ل),سعر البيع ($),سعر الجملة (ل.ل),سعر الجملة ($),سعر التكلفة (ل.ل),سعر التكلفة ($),الكمية بالمستودع,حد الطلب الأدنى,الحالة"]
    for it in items:
        status_text = "متوفر" if it.get('stock_qty', 0) > it.get('low_stock_limit', 5) else ("منخفض" if it.get('stock_qty', 0) > 0 else "نفد من المستودع")
        if not it.get('track_stock'):
            status_text = "بدون تتبع كميات"
        line = f"{it.get('id')},\"{it.get('name')}\",\"{it.get('category_name') or '-'}\",{it.get('item_type')},{it.get('price_lbp')},{it.get('price_usd')},{it.get('wholesale_price_lbp') or 0},{it.get('wholesale_price_usd') or 0},{it.get('cost_price_lbp') or 0},{it.get('cost_price_usd') or 0},{it.get('stock_qty')},{it.get('low_stock_limit')},{status_text}"
        lines.append(line)
        
    csv_data = "\n".join(lines)
    filename = f"stargate_inventory_stock_{timestamp}.csv"
    response = Response(csv_data, mimetype='text/csv; charset=utf-8')
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    return response

@app.route('/inventory/sample-template')
@admin_required
def download_inventory_sample_template():
    """Download clean Arabic CSV template for bulk importing products."""
    sample_lines = [
        "\ufeffاسم الصنف,التصنيف,سعر البيع (ل.ل),سعر البيع ($),سعر الجملة (ل.ل),سعر التكلفة (ل.ل),الكمية بالمخزن,حد التنبيه",
        "قهوة اسبريسو إيطالي,مشروبات ساخنة,150000,1.67,120000,80000,50,10",
        "كابتشينو دوبل,مشروبات ساخنة,220000,2.45,180000,110000,40,10",
        "شاي كرك مميز,مشروبات ساخنة,120000,1.34,95000,50000,60,15",
        "ريد بول أصلي,مشروبات باردة,250000,2.79,200000,160000,100,20",
        "مياه معدنية 500 مل,مشروبات باردة,40000,0.45,30000,20000,200,30",
        "سناك كوكيز شوكولا,سناكس وحلويات,180000,2.00,140000,90000,35,5",
        "معسل تفاحتين نخلة,أراجيل وشيشة,350000,3.91,280000,180000,25,5"
    ]
    csv_data = "\n".join(sample_lines)
    response = Response(csv_data, mimetype='text/csv; charset=utf-8')
    response.headers['Content-Disposition'] = 'attachment; filename=stargate_products_template.csv'
    return response

@app.route('/inventory/import/csv', methods=['POST'])
@admin_required
def import_inventory_csv_route():
    """Bulk import products and wholesale prices from uploaded CSV file."""
    if 'csv_file' not in request.files:
        flash("⚠️ يرجى اختيار ملف CSV أولاً", "warning")
        return redirect(url_for('inventory_page'))
    
    file = request.files['csv_file']
    if not file or file.filename == '':
        flash("⚠️ لم يتم اختيار أي ملف للتحميل", "warning")
        return redirect(url_for('inventory_page'))
        
    try:
        success, msg = accounting.import_inventory_from_csv(file.stream)
        if success:
            write_audit_log(
                actor=session.get('employee_name', 'Admin'),
                action='IMPORT_PRODUCTS_CSV',
                table_name='cafe_items',
                reason=f"Uploaded file: {file.filename}"
            )
            flash(f"✓ {msg}", "success")
        else:
            flash(f"⚠️ {msg}", "danger")
    except Exception as e:
        logger.exception("Error importing CSV: %s", e)
        flash(f"خطأ أثناء معالجة ملف المنتجات: {str(e)}", "danger")
        
    return redirect(url_for('inventory_page'))

@app.route('/item/quick-update', methods=['POST'])
@admin_required
def quick_update_item():
    """Ultra-fast AJAX inline update for item price, name, or stock."""
    try:
        data = request.get_json() or request.form
        item_id = int(data.get('item_id'))
        field = data.get('field')
        value = data.get('value')
        if not field or field not in ('price_lbp', 'price_usd', 'wholesale_price_lbp', 'wholesale_price_usd', 'cost_price_lbp', 'cost_price_usd', 'stock_qty', 'name'):
            return jsonify({'success': False, 'message': 'حقل غير صالح'}), 400
            
        success, res = accounting.quick_update_item_field(item_id, field, value)
        if success:
            return jsonify({'success': True, 'data': res, 'message': 'تم التعديل الفوري بنجاح'})
        else:
            return jsonify({'success': False, 'message': str(res)})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/item/quick-add', methods=['POST'])
@admin_required
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
@admin_required
def add_employee_route():
    """Create new employee."""
    success, res = accounting.add_employee(request.form.to_dict())
    if success:
        flash("تمت إضافة الموظف بنجاح", "success")
    else:
        flash(f"تعذر إضافة الموظف: {res}", "danger")
    return redirect(url_for('employees_page'))

@app.route('/employee/<int:emp_id>/edit', methods=['POST'])
@admin_required
def edit_employee_route(emp_id):
    """Update employee details."""
    success, res = accounting.update_employee(emp_id, request.form.to_dict())
    if success:
        flash("تم تعديل بيانات الموظف بنجاح", "success")
    else:
        flash(f"تعذر التعديل: {res}", "danger")
    return redirect(url_for('employees_page'))

@app.route('/employee/<int:emp_id>/delete', methods=['POST'])
@admin_required
def delete_employee_route(emp_id):
    """Permanently delete employee account."""
    if session.get('employee_id') == emp_id:
        flash("لا يمكنك حذف حسابك الشخصي الذي تستخدمه حالياً!", "warning")
        return redirect(url_for('employees_page'))
    success, res = accounting.delete_employee(emp_id)
    if success:
        database.write_audit_log(
            user_id=session.get('employee_id'),
            username=session.get('employee_name') or 'admin',
            action='DELETE_EMPLOYEE',
            details=f"Deleted employee ID {emp_id}",
            ip_address=request.remote_addr
        )
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
@login_required
def employee_close_shift():
    """Close employee shift, calculate sales, reconcile cash drawer, and handover to next employee."""
    emp_id = session.get('employee_id')
    emp_name = session.get('employee_name')

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

        # تسجيل المطابقة وإغلاق الوردية في سجل shift_closings المحاسبي
        diff_reason = request.form.get('difference_reason', '').strip() or diff_note
        handover_next = request.form.get('handover_to', '').strip()
        try:
            accounting.record_shift_closing(
                business_date=today_str,
                employee_id=emp_id,
                employee_name=emp_name,
                opening_float_lbp=opening_float,
                opening_float_usd=round(opening_float / exchange_rate, 2) if exchange_rate > 0 else 0.0,
                cash_sales_lbp=cash_sales_lbp,
                cash_sales_usd=round(cash_sales_lbp / exchange_rate, 2) if exchange_rate > 0 else 0.0,
                debt_sales_lbp=debt_sales_lbp,
                debt_collected_lbp=debt_collected_lbp,
                expenses_lbp=shift_expenses_lbp,
                safe_transfers_lbp=prior_safe_transfers_lbp + safe_deposit_lbp,
                expected_cash_lbp=expected_cash_lbp,
                actual_cash_lbp=actual_cash,
                difference_lbp=diff,
                difference_note=diff_reason,
                orders_count=len(emp_orders),
                handover_to_employee_name=handover_next
            )

            # إذا وُجد فرق (عجز أو زيادة) نوثقه كقيد تسوية في سجل الحركة المالية
            if abs(diff) > 0:
                adj_type = 'adjustment'
                adj_src = 'external' if diff > 0 else 'drawer'
                adj_dst = 'drawer' if diff > 0 else 'expense'
                accounting.record_financial_ledger_entry(
                    entry_type=adj_type,
                    source=adj_src,
                    destination=adj_dst,
                    amount_lbp=abs(diff),
                    amount_usd=round(abs(diff) / exchange_rate, 2) if exchange_rate > 0 else 0.0,
                    reference_table='shift_closings',
                    reference_id=emp_id,
                    user_id=emp_id,
                    user_name=emp_name,
                    notes=f"تسوية كاش الوردية: {diff_reason}",
                    exchange_rate=exchange_rate,
                    business_date=today_str
                )
        except Exception as ce:
            logger.logger.warning(f"Error in record_shift_closing: {ce}")
        
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


@app.route('/shift/<int:shift_id>/approve', methods=['POST'])
@admin_required
def approve_shift_route(shift_id):
    """اعتماد رسمي لإغلاق الوردية ومطابقة الصندوق من قبل الإدارة."""
    notes = request.form.get('notes', '').strip() or 'اعتماد رسمي ومطابقة تامة'
    approver = session.get('employee_name') or 'المالك'
    accounting.approve_shift_closing(shift_id, approved_by=approver, notes=notes)
    flash(f"✓ تم اعتماد ومطابقة إغلاق الوردية #{shift_id} بنجاح بواسطة {approver}.", "success")
    return redirect(request.referrer or url_for('reports_page'))

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
@login_required
def safe_transfer():
    """إضافة عملية إيداع أو سحب للخزنة مع دعم الليرة والدولار والتحقق من الصلاحيات."""
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


@app.route('/safe/transfer/<int:transfer_id>/cancel', methods=['POST'])
@app.route('/safe/transfer/<int:transfer_id>/delete', methods=['POST'])
@admin_required
def cancel_safe_transfer_route(transfer_id):
    """إلغاء حركة من الخزنة مع توثيق السبب وتحديث الأرصدة دون حذف فيزيائي."""
    reason = request.form.get('cancel_reason', '').strip() or 'إلغاء حركة خزنة بواسطة الإدارة'
    cancelled_by = session.get('employee_name') or 'المدير'
    ok, msg = accounting.cancel_safe_transfer(transfer_id, cancelled_by=cancelled_by, reason=reason)
    if ok:
        flash(f'✓ {msg}', 'success')
    else:
        flash(f'⚠️ {msg}', 'warning')
    return redirect(url_for('safe_page'))


@app.route('/financial/ledger')
@app.route('/financial-ledger')
@admin_required
def financial_ledger_page():
    """عرض سجل الحركة المالية المركزي (Audit Ledger) لمدير النظام."""
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()
    entry_type = request.args.get('entry_type', '').strip()

    entries = accounting.get_financial_ledger_entries(
        start_date=start_date if start_date else None,
        end_date=end_date if end_date else None,
        entry_type=entry_type if entry_type else None,
        limit=300
    )
    safe_balance = accounting.get_safe_balance()
    drawer_status = accounting.get_drawer_cash_status()
    settings = accounting.get_settings()
    accounts = accounting.get_chart_of_accounts()
    journal_entries = accounting.get_journal_entries(limit=150, start_date=start_date if start_date else None, end_date=end_date if end_date else None)

    return render_template(
        'financial_ledger.html',
        entries=entries,
        journal_entries=journal_entries,
        safe_balance=safe_balance,
        drawer_status=drawer_status,
        settings=settings,
        accounts=accounts,
        start_date=start_date,
        end_date=end_date,
        entry_type=entry_type
    )


@app.route('/financial/ledger/<int:ledger_id>/cancel', methods=['POST'])
@admin_required
def cancel_financial_ledger_route(ledger_id):
    """إلغاء قيد مالي محدد من السجل المركزي وتوثيق السبب في سجل التدقيق."""
    reason = request.form.get('cancel_reason', '').strip() or 'إلغاء يدوي من قبل الإدارة'
    cancelled_by = session.get('employee_name') or 'المدير'
    ok, msg = accounting.cancel_financial_ledger_entry(ledger_id, cancelled_by=cancelled_by, reason=reason)
    if ok:
        flash(f'✓ {msg}', 'success')
    else:
        flash(f'⚠️ {msg}', 'warning')
    return redirect(url_for('financial_ledger_page'))



@app.route('/print/safe-statement')
@admin_required
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


# ----------------- QUICK ITEM & SAFE API ENDPOINTS -----------------

@app.route('/api/item/quick_edit', methods=['POST'])
@admin_required
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
@admin_required
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
@login_required
def safe_quick_transfer():
    try:
        data = request.get_json() if request.is_json else request.form
        transfer_all = bool(data.get('transfer_all'))
        drawer_stat = accounting.get_drawer_cash_status()
        drawer_rem_lbp = float(drawer_stat.get('total_untransferred_lbp') or 0.0)

        amount_lbp = float(data.get('amount_lbp') or 0)
        amount_usd = float(data.get('amount_usd') or 0)
        emp_name = data.get('employee_name') or session.get('employee_name', 'الكاشير')
        note = (data.get('note') or 'توريد نقدي إلى الخزنة الخاصة').strip()

        settings = accounting.get_settings()
        rate = float(settings.get('exchange_rate') or 89500.0)

        # إذا طُلب نقل كامل الكاش أو لم يدخل مبلغ وكان في الدرج كاش
        if transfer_all or (amount_lbp <= 0 and amount_usd <= 0 and drawer_rem_lbp > 0):
            amount_lbp = drawer_rem_lbp
            amount_usd = round(amount_lbp / rate, 2) if rate > 0 else 0.0
            if not note or note == 'توريد نقدي إلى الخزنة الخاصة':
                note = 'ترحيل كامل كاش الدرج وتصفير رصيد الدرج'

        if amount_usd > 0 and amount_lbp <= 0:
            amount_lbp = round(amount_usd * rate, 0)
        elif amount_lbp > 0 and amount_usd <= 0:
            amount_usd = round(amount_lbp / rate, 2)

        if amount_lbp <= 0 and amount_usd <= 0:
            return jsonify({'success': False, 'error': 'درج الكاشير فارغ حالياً (0 ل.ل) أو لم يتم إدخال مبلغ'}), 400

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
        new_drawer_stat = accounting.get_drawer_cash_status()
        new_rem_lbp = float(new_drawer_stat.get('total_untransferred_lbp') or 0.0)

        msg = f"تم ترحيل {amount_lbp:,.0f} ل.ل إلى الخزنة بنجاح"
        if new_rem_lbp == 0:
            msg += " وأصبح رصيد كاش الدرج مصفراً (0 ل.ل) ✅"
        else:
            msg += f" (المتبقي بالدرج: {new_rem_lbp:,.0f} ل.ل)"

        return jsonify({
            'success': True,
            'transfer_id': transfer_id,
            'message': msg,
            'balance': new_balance,
            'drawer_remaining_lbp': new_rem_lbp
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
    today_str = accounting.get_business_date()
    yesterday_str = accounting.get_business_date(dt=(datetime.now() - timedelta(days=1)))
    before_yesterday_str = accounting.get_business_date(dt=(datetime.now() - timedelta(days=2)))

    raw_date = request.args.get('date', '').strip()
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()
    period = request.args.get('period', '').strip().lower()

    is_range = False
    now_dt = datetime.now()
    if period == 'week':
        is_range = True
        start_date = (now_dt - timedelta(days=6)).strftime('%Y-%m-%d')
        end_date = today_str
        target_date = start_date
        display_period = f"هذا الأسبوع ({start_date} إلى {end_date})"
    elif period == 'month':
        is_range = True
        start_date = now_dt.strftime('%Y-%m-01')
        end_date = today_str
        target_date = start_date
        display_period = f"هذا الشهر ({start_date} إلى {end_date})"
    elif period == 'year':
        is_range = True
        start_date = now_dt.strftime('%Y-01-01')
        end_date = today_str
        target_date = start_date
        display_period = f"هذه السنة ({start_date} إلى {end_date})"
    elif start_date and end_date and start_date != end_date:
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

    pnl = accounting.get_comprehensive_financial_statement(
        start_date=start_date if is_range else (target_date if target_date != 'all' else '2000-01-01'),
        end_date=end_date if is_range else (target_date if target_date != 'all' else today_str)
    )
    coffee_period_stats = accounting.get_coffee_period_stats(
        start_date=start_date if is_range else (target_date if target_date != 'all' else '2000-01-01'),
        end_date=end_date if is_range else (target_date if target_date != 'all' else today_str)
    )

    return render_template(
        'reports.html',
        coffee_period_stats=coffee_period_stats,
        pnl=pnl,
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
        period=period,
        active_page='reports'
    )


@app.route('/reports/print', endpoint='print_reports_page')
@admin_required
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
@admin_required
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
@admin_required
def safe_transfer_daily():
    """نقل وترحيل صافي نقدية اليوم إلى الخزنة الخاصة مباشرة بنقرة واحدة."""
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
@login_required
def safe_transfer_drawer_total():
    """ترحيل كامل الرصيد النقدي المتراكم بالدرج إلى الخزنة الخاصة وتصفير رصيد الدرج إلى 0 ل.ل."""
    transferred_by = session.get('employee_name') or session.get('admin_name') or 'الكاشير'
    note = (request.form.get('note') if not request.is_json else (request.get_json(silent=True) or {}).get('note')) or "ترحيل كامل كاش الدرج وتصفير رصيد الصندوق"
    try:
        res = accounting.transfer_drawer_total_to_safe(transferred_by=transferred_by, note=note)
        msg = f"تم ترحيل كامل كاش الدرج ({res['amount_lbp']:,.0f} ل.ل) بنجاح وأصبح رصيد الدرج مصفراً (0 ل.ل) 🔒"
        if request.is_json:
            return jsonify({'success': True, 'message': msg, 'amount_lbp': res['amount_lbp'], 'drawer_remaining_lbp': 0.0})
        flash(f"✓ {msg}", "success")
    except Exception as e:
        if request.is_json:
            return jsonify({'success': False, 'message': str(e)}), 400
        flash(f"تنبيه: {e}", "warning")

    next_url = request.form.get('next') or request.referrer or url_for('safe_page')
    return redirect(next_url)

@app.route('/api/safe/daily_status')
@admin_required
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
    """يُعيد حالة التحديث المتاح (JSON) مع الإصدار الحالي المثبت."""
    # إعادة الفحص إذا لم يتم الفحص بعد
    if not _update_cache.get('checked'):
        threading.Thread(target=_background_update_check, daemon=True).start()
    result = dict(_update_cache)
    result['local_version'] = _get_current_version()
    return jsonify(result)


@app.route('/api/force_check_update')
def api_force_check_update():
    """إعادة الفحص الفوري من GitHub."""
    _update_cache['checked'] = False
    _background_update_check()
    result = dict(_update_cache)
    result['local_version'] = _get_current_version()
    return jsonify(result)


@app.route('/api/do_update', methods=['POST'])
@admin_required
def api_do_update():
    """تنزيل وتثبيت التحديث مع التحقق الأمني والنسخ الاحتياطي."""
    import subprocess, shutil, zipfile as zf
    try:
        url = _update_cache.get('download_url', '')
        if not url or not url.startswith('http'):
            return jsonify({'success': False, 'error': 'رابط التحديث غير صالح'})

        import ssl, urllib.request as ur
        ctx = ssl.create_default_context()

        base_dir = _get_base_dir()
        zip_path = os.path.join(base_dir, 'cafe_update_package.zip')
        tmp_dir  = os.path.join(base_dir, 'cafe_update_tmp')

        # إنشاء نسخة احتياطية فورية قبل أي تعديل
        try:
            database.create_backup_copy()
        except Exception as e:
            logger.logger.warning(f"Pre-update backup warning: {e}")

        # تحميل حزمة التحديث
        req = ur.Request(url, headers={'User-Agent': 'StargateCafe-OTA/4.6'})
        with ur.urlopen(req, timeout=120, context=ctx) as resp, open(zip_path, 'wb') as out:
            shutil.copyfileobj(resp, out)

        # فحص سلامة ملف الـ ZIP وتجنب ثغرات Directory Traversal (Zip Slip)
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir, ignore_errors=True)
        os.makedirs(tmp_dir, exist_ok=True)
        
        with zf.ZipFile(zip_path, 'r') as z:
            bad_file = z.testzip()
            if bad_file:
                raise Exception(f"ملف التحديث تالف عند الملف: {bad_file}")
            abs_tmp = os.path.abspath(tmp_dir)
            for m in z.namelist():
                dest = os.path.abspath(os.path.join(abs_tmp, m))
                if not dest.startswith(abs_tmp):
                    continue  # Block zip slip attempts
                z.extract(m, abs_tmp)

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
        logger.logger.error(f"OTA Update error: {e}")
        return jsonify({'success': False, 'error': str(e)})



# =========================================================================
# 🏢 ERP ROUTES: SUPPLIERS & PURCHASES
# =========================================================================

@app.route('/suppliers')
@admin_required
def suppliers_page():
    """شاشة إدارة الموردين وفواتير الشراء."""
    q = request.args.get('q', '').strip()
    suppliers = accounting.get_suppliers(search_query=q)
    inventory_items = accounting.get_inventory_stock()
    settings = accounting.get_settings()
    return render_template(
        'suppliers.html',
        suppliers=suppliers,
        inventory_items=inventory_items,
        settings=settings,
        active_page='suppliers'
    )

@app.route('/supplier/add', methods=['POST'])
@admin_required
def supplier_add():
    """إضافة مورد جديد."""
    name = request.form.get('name', '').strip()
    phone = request.form.get('phone', '').strip()
    company = request.form.get('company', '').strip()
    notes = request.form.get('notes', '').strip()
    if name:
        accounting.add_supplier(name=name, phone=phone, company=company, notes=notes)
        flash("✓ تم حفظ المورد بنجاح", "success")
    return redirect(url_for('suppliers_page'))

@app.route('/purchase/add', methods=['POST'])
@admin_required
def purchase_invoice_add():
    """تسجيل فاتورة شراء بضاعة ومواد خام وتغذية المخزون."""
    supplier_id = request.form.get('supplier_id')
    inv_id = request.form.get('inventory_id')
    qty = float(request.form.get('qty', 1) or 1)
    cost_usd = float(request.form.get('cost_usd', 0) or 0)
    cost_lbp = float(request.form.get('cost_lbp', 0) or 0)
    paid_usd = float(request.form.get('paid_usd', 0) or 0)
    payment_source = request.form.get('payment_source', 'safe')
    notes = request.form.get('notes', '').strip()

    items = [{
        'inventory_id': int(inv_id) if inv_id else None,
        'item_name': 'مشتريات مواد خام',
        'qty': qty,
        'cost_unit_usd': cost_usd,
        'cost_unit_lbp': cost_lbp,
        'unit': 'قطعة'
    }]

    if supplier_id:
        accounting.record_purchase_invoice(
            supplier_id=int(supplier_id),
            items=items,
            paid_usd=paid_usd,
            paid_lbp=0.0,
            payment_source=payment_source,
            notes=notes,
            created_by=session.get('employee_name') or 'المدير'
        )
        flash("✓ تم تسجيل فاتورة الشراء وتحديث المخزون بنجاح!", "success")
    return redirect(url_for('suppliers_page'))

@app.route('/supplier/<int:supplier_id>/pay', methods=['POST'])
@admin_required
def supplier_pay_route(supplier_id):
    """سداد دفعة نقدية لحساب المورد."""
    amount_usd = float(request.form.get('amount_usd', 0) or 0)
    amount_lbp = float(request.form.get('amount_lbp', 0) or 0)
    payment_source = request.form.get('payment_source', 'safe')
    notes = request.form.get('notes', '').strip()
    
    success, msg = accounting.record_supplier_payment(
        supplier_id=supplier_id,
        amount_usd=amount_usd,
        amount_lbp=amount_lbp,
        payment_source=payment_source,
        notes=notes,
        created_by=session.get('employee_name') or 'المدير'
    )
    if success:
        flash(f"✓ {msg}", "success")
    else:
        flash(f"⚠️ {msg}", "danger")
    return redirect(url_for('suppliers_page'))


# =========================================================================
# 🍽️ ERP ROUTES: DINING TABLES
# =========================================================================

@app.route('/tables')
@login_required
def tables_page():
    """شاشة إدارة طاولات وصالات الكافيه."""
    tables = accounting.get_dining_tables()
    settings = accounting.get_settings()
    return render_template(
        'tables.html',
        tables=tables,
        settings=settings,
        active_page='tables'
    )

@app.route('/table/add', methods=['POST'])
@admin_required
def table_add():
    """إضافة طاولة جديدة."""
    t_num = request.form.get('table_number', '').strip()
    t_name = request.form.get('table_name', '').strip()
    sec = request.form.get('section', 'الصالة الرئيسية').strip()
    seats = int(request.form.get('seats', 4) or 4)
    if t_num:
        try:
            accounting.add_dining_table(table_number=t_num, table_name=t_name, section=sec, seats=seats)
            flash(f"✓ تمت إضافة الطاولة {t_num} بنجاح", "success")
        except Exception as e:
            flash(f"تنبيه: {e}", "warning")
    return redirect(url_for('tables_page'))


if __name__ == '__main__':
    database.init_db()
    import socket
    try:
        local_ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        local_ip = '0.0.0.0'
    print("=" * 60)
    print(f"[RUNNING] STARGATE CAFE & GAMING ERP SYSTEM v5.0 PRO")
    print(f"  - Local Host:    http://127.0.0.1:5000")
    print(f"  - Employee Host: http://{local_ip}:5000")
    print("=" * 60)
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False, threaded=True)

