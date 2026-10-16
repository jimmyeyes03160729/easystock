"""Chrome 2.0: the users/{uid} rules merge keeps every live rule and refuses unsafe inputs."""
import json
from pathlib import Path

import pytest

from tools.firebase_rules import merge_users, USER_OWNER_RULE

ROOT = Path(__file__).resolve().parents[1]
USERS = json.loads((ROOT / 'firebase.rules.json').read_text(encoding='utf-8'))['rules']['users']
LIVE = {'rules': {'.read': False, '.write': False, 'market_data': {
    'meta': {'.read': True}, 'public_feed': {'.read': True}, 'line_groups': {'.read': False}}}}


def test_merge_adds_only_users_subtree():
    candidate = merge_users(LIVE, USERS)
    assert 'users' not in LIVE['rules']
    assert candidate['rules']['users']['$uid']['.read'] == USER_OWNER_RULE
    assert candidate['rules']['users']['$uid']['.write'] == USER_OWNER_RULE
    del candidate['rules']['users']
    assert candidate == LIVE


def test_merge_refuses_open_root_because_grants_cascade():
    with pytest.raises(RuntimeError):
        merge_users({'rules': {'.read': True, 'market_data': {}}}, USERS)
    with pytest.raises(RuntimeError):
        merge_users({'rules': {'.read': False, '.write': True}}, USERS)


def test_merge_refuses_non_owner_users_block():
    with pytest.raises(RuntimeError):
        merge_users(LIVE, {'$uid': {'.read': 'auth != null', '.write': USER_OWNER_RULE}})
    with pytest.raises(RuntimeError):
        merge_users(LIVE, {'.read': True, '$uid': {'.read': USER_OWNER_RULE, '.write': USER_OWNER_RULE}})
