from datetime import datetime,timedelta,timezone
import threading
from runtime_clock import LaneClock
AT=datetime(2026,10,16,10,tzinfo=timezone(timedelta(hours=8)))
def test_real_gap_is_preserved_without_catchup(tmp_path):
    times=iter([AT,AT+timedelta(seconds=53)]);seen=[]
    c=LaneClock(seen.append,now=lambda:next(times))
    c.tick();c.tick()
    assert seen==[AT,AT+timedelta(seconds=53)] and c.max_gap_seconds==53

def test_clock_advances_while_main_work_is_blocked():
    advanced=threading.Event();release=threading.Event();seen=[]
    def step(at):
        seen.append(at)
        if len(seen)>=3:advanced.set()
    c=LaneClock(step,interval=.01)
    blocked=threading.Thread(target=lambda:release.wait(1));blocked.start();c.start()
    try:
        assert advanced.wait(1) and blocked.is_alive()
    finally:release.set();blocked.join();c.stop()
    assert len(seen)>=3 and seen==sorted(seen) and c.error is None

def test_failure_stops_future_clocks_and_records_health(tmp_path):
    done=threading.Event()
    def fail(at):
        done.set();raise ValueError('fixture')
    c=LaneClock(fail,health_path=tmp_path/'clock.json');c.start()
    assert done.wait(1);c.stop()
    assert c.error=='ValueError' and c.ticks==0
    assert 'ValueError' in (tmp_path/'clock.json').read_text()


def test_engine_refreshes_decision_time_after_book_poll():
    import ast
    from pathlib import Path
    from types import SimpleNamespace
    tree=ast.parse(Path('intraday_live.py').read_text(encoding='utf-8'))
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='IntradayLiveEngine')
    fn=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='advance_b_clock')
    actual=AT+timedelta(seconds=53);scope={'now_tpe':lambda:actual}
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'clock-test','exec'),scope)
    seen=[];polls=[]
    engine=SimpleNamespace(dual_books=SimpleNamespace(poll=polls.append),runway_v2=SimpleNamespace(advance=seen.append))
    scope['advance_b_clock'](engine,AT)
    assert polls==[AT] and seen==[actual]
