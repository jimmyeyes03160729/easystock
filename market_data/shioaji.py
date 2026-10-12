"""Read-only contract adapters; base identifiers are not metadata records."""

from collections import OrderedDict
from collections.abc import Mapping
import math


def _stock_fields(record):
    """StockInfo stores optional fields in dict(); legacy Stock has attributes."""
    if isinstance(record, Mapping):
        return dict(record)
    convert = getattr(record, 'dict', None)
    if callable(convert):
        value = convert()
        if not isinstance(value, Mapping):
            raise ValueError('stock_info_not_mapping')
        return dict(value)
    return {key: getattr(record, key, None)
            for key in ('code', 'reference', 'category', 'day_trade')}


class StockMetadataCache:
    """Bounded, per-day metadata cache, used by the radar loop, never callbacks.

    In the VM SDK, contracts.get(code) returns BaseContract and info(base)
    returns StockInfo. Keep the BaseContract for subscriptions; do not replace
    it with a metadata dict or infer reference/short eligibility from a scanner.
    """
    def __init__(self):
        self.day = None
        self.cache = OrderedDict()

    def read(self, api, contract, symbol, now):
        day, at = now.date().isoformat(), now.timestamp()
        if day != self.day:
            self.cache.clear()
            self.day = day
        key = str(symbol)
        result = {'reference': None, 'category': '', 'day_trade': None,
                  'metadata_source': 'unknown', 'metadata_status': 'unavailable'}
        code = contract.get('code') if isinstance(contract, Mapping) else getattr(contract, 'code', None)
        if str(code or '') != key:
            self.cache.pop(key, None)
            result['metadata_error'] = 'contract_missing_or_symbol_mismatch'
            return result
        cached = self.cache.get(key)
        if cached and 0 <= at - cached[0] < cached[1]:
            return dict(cached[2])
        try:
            namespace = getattr(api, 'contracts', None)
            info = getattr(namespace, 'info', None)
            record = info(contract) if callable(info) else contract
            source = 'sdk_info' if callable(info) else 'legacy_contract'
            fields = _stock_fields(record)
            code = fields.get('code') or getattr(getattr(record, 'base', None), 'code', None)
            if str(code or '') != key:
                raise ValueError('stock_info_symbol_mismatch')
            raw = fields.get('reference')
            reference = float(raw) if raw is not None and not isinstance(raw, bool) else None
            if reference is not None and (not math.isfinite(reference) or reference <= 0):
                reference = None
            category = fields.get('category')
            category = category.strip() if isinstance(category, str) else ''
            flag = fields.get('day_trade')
            flag = getattr(flag, 'value', flag)
            if isinstance(flag, str) and flag.startswith('DayTrade.'):
                flag = flag[len('DayTrade.'):]
            flag = flag if isinstance(flag, str) and flag in ('Yes', 'OnlyBuy', 'No') else None
            result.update(reference=reference, category=category, day_trade=flag,
                          metadata_source=source,
                          metadata_status='ready' if reference and category and flag else 'partial')
        except Exception as exc:
            # No raw SDK payload, credentials, or scanner fallback in the result.
            result['metadata_error'] = type(exc).__name__
        ttl = 60 if result['metadata_status'] == 'ready' else 15
        self.cache[key] = (at, ttl, dict(result))
        self.cache.move_to_end(key)
        while len(self.cache) > 512:
            self.cache.popitem(last=False)
        return result


def taiex_contract(api):
    # Verified on the VM's Shioaji 1.7.4: contracts.get('IX0001').
    try:
        contracts = api.contracts
        for symbol in ('IX0001', '001'):
            contract = contracts.get(symbol)
            if contract is not None:
                return contract
    except (AttributeError, KeyError, TypeError):
        pass

    # Older SDKs expose the nested registry through the deprecated name.
    try:
        contracts = api.Contracts.Indexs.TSE
        for symbol in ('IX0001', '001'):
            try:
                contract = contracts[symbol]
            except (KeyError, AttributeError, TypeError):
                continue
            if contract is not None:
                return contract
    except (AttributeError, KeyError, TypeError):
        pass
    raise LookupError('index_contract_unavailable')
