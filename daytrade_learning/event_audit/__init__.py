"""Event-audit toolkit: causal, cost-aware entry-event studies on archived ticks/kbars.

Extracted from the H2/H3/H4/source-primitive/base-rate audits so every future
hypothesis family is measured with the same frozen conventions:

- timebase: archive timestamps are naive Taiwan wall-clock encoded as nanoseconds
  (``datetime(1970,1,1) + timedelta(microseconds=ns//1000)``; never tz-converted)
- bars: only COMPLETE 5m/15m buckets aligned to 09:00, as in ``intraday_live._aggregate``
- events: false->true episodes with a 15 minute overlap exclusion
- returns: gross / research-net / quote-stress with ``paper_execution`` fee and tax rounding
- classification: fixed A-H economic criteria over five chronological test windows

RESEARCH_ONLY: nothing here sends orders, touches live services or trains models.
"""
RESEARCH_ONLY = True
