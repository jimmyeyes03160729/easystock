"""Guardian monitoring remains active; external messaging is intentionally retired."""

def send(text, key):
    return False

def retry_pending():
    return None
