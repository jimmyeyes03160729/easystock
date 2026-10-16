# Approved translucent homepage

The owner approved the desktop/mobile prototype and explicitly requested Git and VM deployment on 2026-10-17.

The production homepage retains its existing public data readers, strategy calculations, Paper execution labels, stock-detail/K-line handlers, observation modules, and admin routes. The approved presentation adds the blue/lilac glass canvas, larger transparent EasyStock logo, small Google Chrome icon beside the date, research summary cards, independent A/B1/B2/B3 tabs, and compact expandable records. Missing data remains unknown; summary numbers come from the existing research status, not prototype fixtures. Open records are never hidden solely to enforce the default five-row limit.

Price and budget controls only change displayed records. No trading policy, account setting, database, secret, timer, or runtime installer is modified by this release. The Chrome image identifies the browser installation entry; it does not replace the extension's packaged identity.

The existing Pages pipeline publishes the website from main. The manually dispatched `Deploy approved homepage to VM` workflow uses the repository's existing VM secrets and a pinned, previously trusted VM host key. It only fast-forwards an unmodified main checkout whose entire incoming diff is limited to homepage assets and their tests/documentation/deployment helper. Divergence, tracked local edits, a moved main, or unrelated runtime changes stop deployment. A frontend archive and before/after commit receipts are retained under the existing VM maintenance directory. No services are restarted.

Static source synchronization does not claim that research/trading services were restarted or that any strategy was validated.

Chrome logo source: https://www.google.com/chrome/static/images/chrome-logo.svg
