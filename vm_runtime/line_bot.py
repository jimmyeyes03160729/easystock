"""Minimal personal LINE outbound adapter. No group fallback and no replies."""
from easystock_admin.notifications import line_config


def access_token():
    return line_config()[0]


def default_target():
    return line_config()[1]
