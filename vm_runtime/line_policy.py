"""Fail-closed paid-message policy, separate from trading execution."""
def push_allowed(target, category='other'):
    try:
        from easystock_admin.store import Store
        from easystock_admin.conversations import allowed
        kind = 'group' if target.startswith('C') else 'room' if target.startswith('R') else 'user'
        return allowed(Store(), {'type':kind, {'group':'groupId','room':'roomId','user':'userId'}[kind]:target}, category)
    except Exception as exc:
        print('[LINE POLICY] unavailable:',type(exc).__name__)
        return False
