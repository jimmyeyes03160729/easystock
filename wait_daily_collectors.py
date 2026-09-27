"""Give same-day labels priority over resumable historical backfill."""
import subprocess
import time
import sys

def main():
    deadline=time.monotonic()+3600
    while time.monotonic()<deadline:
        states=[subprocess.run(['systemctl','is-active',name],capture_output=True,text=True).stdout.strip()
                for name in (sys.argv[1:] or ['easystock-learning.service','easystock-paper-feedback.service'])]
        if not any(s in ('active','activating') for s in states):return 0
        time.sleep(15)
    return 1

if __name__=='__main__':raise SystemExit(main())
