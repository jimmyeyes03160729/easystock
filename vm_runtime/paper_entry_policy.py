"""A paper-fill restrictions only; never suppress research event acceptance."""
from dataclasses import dataclass
from datetime import datetime
import math,re

@dataclass(frozen=True)
class PaperEntryPolicy:
    min_price: float = 30.
    max_price: float = 200.
    min_lots: float = 3000.

    def __post_init__(self):
        if not all(math.isfinite(x) for x in (self.min_price,self.max_price,self.min_lots)) or not 0<self.min_price<=self.max_price or self.min_lots<0:
            raise ValueError('invalid_paper_entry_policy')

    def check(self,symbol,name,price,evidence,now):
        def skip(reason):return {'status':'skipped','shares':0,'skip_reason':reason}
        if not re.fullmatch(r'[1-8]\d{3}',str(symbol)) or str(symbol).startswith(('00','01','02','91')) or any(k in str(name).upper() for k in ('ETF','ETN','境外指數','反1','正2','期信')):
            return skip('etf_ineligible')
        if not self.min_price<=price<=self.max_price:return skip('price_out_of_range')
        v=evidence.get('cumulative_volume') or {}
        try:
            at=datetime.fromisoformat(v['quote_at'])
            qty=v['value']
            if v.get('source')!='shioaji_common_stock_tick_total_volume' or v.get('unit')!='lot' or at.tzinfo is None or at.date()!=now.date() or not 0<=(now-at).total_seconds()<=3 or isinstance(qty,bool) or not math.isfinite(float(qty)) or float(qty)<0:
                return skip('volume_unverified')
            if float(qty)<self.min_lots:return skip('low_volume')
        except (KeyError,ValueError,TypeError,OverflowError):return skip('volume_unverified')
        return None
