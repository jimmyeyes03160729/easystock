# B shadow integration: implementation complete, live gate NOT passed

## Outcome

The isolated, signal-only implementation is complete. It was NOT switched into
the production B lane, promoted, scheduled, or pushed to Git. The latest corrected
live attempt did not establish the E.SUN book connection: it disconnected before
any subscription ACK. Do not describe this as LIVE VERIFIED or as improved B1
recommendations.

## Verified engineering checks

- 81 focused Python tests passed locally; these include 17 shadow tests.
- The same 17 shadow tests passed on VM Python 3.10.12 with only synthetic
  fixtures and private temporary databases. Seven mocked Node tests passed.
- UTC-Z compatibility is now explicit. All 14,231 genuine E.SUN book envelopes
  captured in the earlier instrumented trial normalized successfully under the
  corrected VM adapter at their recorded provider receipt time. This checks real
  provider format/time parsing, NOT live consumer delay, joins or execution.
- Native LaneSuite signal rules remain unchanged. There are no shadow positions,
  orders, wallet changes, production recommendations or notifications. Unknown
  quantity units continue to block depth sizing and execution.

## Live attempts and limitations

The first SDK construction attempt and the pre-UTC-fix trials are debugging
evidence only. Before the UTC fix, the bridge genuinely ACKed all 40 books but
the Python receiver rejected them due to Python 3.10's unsupported direct `Z`
parsing. Those attempts cannot establish cross-provider integration success.

After the fix, two bounded attempts were stopped by socket disconnection before
ACKs. No retry loop was installed. The latest attempt ran from
2026-10-13 10:21:39.946982 to 10:22:15.438731 (Taiwan time):

- 40 requested symbols; zero channel ACKs, zero shadow signals.
- 18 measured clocks; no bridge-capture overflow or invalid-JSON counter.
- Driver reason `bridge_finished_before_driver`; bridge reason
  `socket_disconnected`. This does not identify the underlying network,
  authentication or account-capacity cause, and is not proof of missing market
  opportunities.
- Measured market context retained `valid=true`, `gate_action=BLOCK`. The rule
  was not bypassed. Some native subscription snapshots were older than five
  seconds and were explicitly excluded from paired eligibility comparisons.
- B1 was outside its 09:00–09:10 entry window. Today's trials do not validate
  opening-session B1 coverage or recommendation generation.

The original production E.SUN worker remained available after the failed attempt;
its observed reconnect counter had increased from 31 to 32 with the recorded
last error at 10:14:03. The final 10:27:55 health read showed the same reconnect
counter 32, with last error at 10:20:11 and current error null. Neither observation
establishes why the reconnect or later error occurred. Production Git HEAD remains `666ad08`.
No permanent additional connection or systemd service was installed.

## Reproduction receipts and next gate

The corrected bundle SHA-256 is
`23bd01d2d0337d532de883ac9a3ba259ccf1325b9c1e276a7f0af119954ca653`.
The task output folder `b-books-shadow-20261013` retains the latest
`protocol.json` and `results.json`, including actual loaded source hashes.
A later local logging-only repair records actual message handling time rather
than the earlier loop timestamp; it was regression-tested locally but is not
represented as another successful live run.

Still required: a stable, corrected live joined-feed sample, actual B1 opening
observation, explicit size-unit verification, available fresh native control
state and reconnect/queue stress checks. Until those pass:
`execution_allowed=false`, `deployment_allowed=false`, `training_eligible=false`.
