/* Compatibility router. Enable only after the VM result publisher has been validated.
 * No legacy fallback after activation: a denied endpoint must never bypass isolation.
 */
(function (g) {
  const names = new Set(['intraday_live', 'intraday_picks', 'daytrade_learning_status', 'history_training_status']);
  function publicDataURL(input, enabled = g.PUBLIC_RESULTS_V1 === true) {
    const url = String(input);
    if (!enabled) return url;
    return url.replace(/\/market_data\/([^/?]+)\.json(?=\?|$)/, (whole, node) =>
      names.has(node) ? `/market_data/public_v1/${node}.json` : whole);
  }
  g.publicDataURL = publicDataURL;
  if (typeof module !== 'undefined') module.exports = {publicDataURL};
})(typeof window === 'undefined' ? globalThis : window);
