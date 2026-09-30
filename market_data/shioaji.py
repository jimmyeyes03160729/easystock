"""Resolve the TWSE price-index contract across installed Shioaji versions."""


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
