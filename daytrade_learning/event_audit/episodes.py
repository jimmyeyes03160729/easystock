"""false->true episode construction with overlap exclusion."""
from __future__ import annotations

from dataclasses import dataclass

HORIZON_US = 15 * 60 * 1_000_000


@dataclass(frozen=True)
class EpisodeResult:
    raw_pass_rows: int
    false_to_true: int
    overlap_excluded: int
    accepted: tuple          # decision timestamps (us) of FINAL episodes


def select_episodes(states, horizon_us: int = HORIZON_US) -> EpisodeResult:
    """``states``: iterable of (decision_us, bool) in time order for ONE symbol-day.

    An episode starts on a false->true transition (the first point of the day counts
    from false).  A transition less than ``horizon_us`` after the previous ACCEPTED
    episode is excluded; exactly ``horizon_us`` later is allowed.  Points where the
    signal is false (including points dropped for stale ticks or limits) reset state.
    """
    raw = f2t = overlap = 0
    accepted = []
    prev = False
    last = None
    for t_us, state in states:
        state = bool(state)
        raw += state
        was, prev = prev, state
        if not state or was:
            continue
        f2t += 1
        if last is not None and t_us < last + horizon_us:
            overlap += 1
            continue
        last = t_us
        accepted.append(t_us)
    return EpisodeResult(raw, f2t, overlap, tuple(accepted))
