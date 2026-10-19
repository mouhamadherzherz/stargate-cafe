# -*- coding: utf-8 -*-
"""
STARGATE CAFE — Role-Based Access Control (RBAC) System
Defines 7 standard roles and granular permissions enforced on server-side APIs and routes.
"""

# ─────────────────────────────────────────────────────────────
# 1. Permission Matrix Definitions
# ─────────────────────────────────────────────────────────────
ROLE_PERMISSIONS = {
    # 1. مالك النظام (Super Administrator / Owner) — Full Access
    'owner': {
        'pos.access', 'orders.create', 'orders.cancel', 'orders.discount', 'orders.refund',
        'debt.record', 'debt.collect', 'safe.view', 'safe.transfer', 'safe.zero',
        'shifts.open', 'shifts.close', 'shifts.approve', 'inventory.view', 'inventory.edit',
        'stocktaking.conduct', 'stocktaking.approve', 'purchases.create', 'purchases.approve',
        'suppliers.manage', 'expenses.record', 'expenses.approve', 'accounting.ledger',
        'accounting.statements', 'reports.view', 'reports.export', 'employees.manage',
        'audit.view', 'settings.edit', 'backup.manage', 'owner.drawings'
    },

    # 2. مدير النظام (Administrator) — Full Operational & Management Access
    'admin': {
        'pos.access', 'orders.create', 'orders.cancel', 'orders.discount', 'orders.refund',
        'debt.record', 'debt.collect', 'safe.view', 'safe.transfer', 'safe.zero',
        'shifts.open', 'shifts.close', 'shifts.approve', 'inventory.view', 'inventory.edit',
        'stocktaking.conduct', 'stocktaking.approve', 'purchases.create', 'purchases.approve',
        'suppliers.manage', 'expenses.record', 'expenses.approve', 'accounting.ledger',
        'accounting.statements', 'reports.view', 'reports.export', 'employees.manage',
        'audit.view', 'settings.edit', 'backup.manage', 'owner.drawings'
    },

    # 3. مدير وردية (Shift Manager) — Operational, Shift Oversight & Approvals
    'shift_manager': {
        'pos.access', 'orders.create', 'orders.cancel', 'orders.discount', 'orders.refund',
        'debt.record', 'debt.collect', 'safe.view', 'shifts.open', 'shifts.close',
        'shifts.approve', 'inventory.view', 'stocktaking.conduct', 'expenses.record',
        'reports.view', 'reports.export'
    },

    # 4. محاسب (Accountant) — Financial Ledger, Reconciliations & Reports
    'accountant': {
        'safe.view', 'debt.collect', 'inventory.view', 'stocktaking.conduct',
        'purchases.create', 'suppliers.manage', 'expenses.record', 'expenses.approve',
        'accounting.ledger', 'accounting.statements', 'reports.view', 'reports.export',
        'audit.view'
    },

    # 5. كاشير (Cashier) — POS Sales & Checkout Only
    'cashier': {
        'pos.access', 'orders.create', 'debt.record', 'debt.collect',
        'shifts.open', 'shifts.close'
    },

    # 6. مسؤول مخزون (Inventory Keeper) — Catalog, Movements, Stocktake & Purchases
    'inventory_keeper': {
        'inventory.view', 'inventory.edit', 'stocktaking.conduct',
        'purchases.create', 'suppliers.manage', 'reports.view'
    },

    # 7. مدقق للقراءة فقط (Read-Only Auditor) — Strict View-Only Access
    'auditor': {
        'inventory.view', 'accounting.ledger', 'accounting.statements',
        'reports.view', 'reports.export', 'audit.view'
    }
}

ROLE_TITLES_AR = {
    'owner': 'مالك النظام',
    'admin': 'مدير النظام',
    'shift_manager': 'مدير وردية',
    'accountant': 'محاسب مالي',
    'cashier': 'كاشير / نقطة بيع',
    'inventory_keeper': 'مسؤول مخزون ومشتريات',
    'auditor': 'مدقق حسابات (قراءة فقط)'
}

def get_role_permissions(role: str) -> set:
    """Return set of permission strings for a given role name."""
    if not role:
        return set()
    role_key = str(role).strip().lower()
    return ROLE_PERMISSIONS.get(role_key, set())

def has_permission(user_role: str, required_perm: str, custom_permissions_json: str = None) -> bool:
    """Check if user role has a specific permission."""
    if not user_role:
        return False
    role_key = str(user_role).strip().lower()
    
    # Owner and Admin have all permissions
    if role_key in ('owner', 'admin'):
        return True
        
    perms = get_role_permissions(role_key)
    if required_perm in perms:
        return True
        
    # Check custom granted permissions if JSON string is stored in DB
    if custom_permissions_json:
        try:
            import json
            custom = json.loads(custom_permissions_json)
            if isinstance(custom, list) and required_perm in custom:
                return True
        except Exception:
            pass
            
    return False

def get_all_roles():
    """Return dictionary of supported roles with their Arabic display titles."""
    return ROLE_TITLES_AR.copy()
