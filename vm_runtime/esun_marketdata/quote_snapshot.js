// Legacy one-shot read-only diagnostic; the production gate reads Provider's cache.
// stdout contains only one normalized JSON object; credentials stay local.
const fs = require('fs');
const { EsunMarketdata } = require('@esun/marketdata');

function loadCredentials(path) {
  const values = {};
  for (const raw of fs.readFileSync(path, 'utf8').split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith('#')) continue;
    const separator = line.indexOf('=');
    if (separator < 1) continue;
    const key = line.slice(0, separator).trim();
    if (!['ESUN_PASSWORD', 'ESUN_CERT_PASS'].includes(key)) continue;
    let value = line.slice(separator + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'"))) value = value.slice(1, -1);
    values[key] = value;
  }
  return values;
}

(async () => {
  try {
    const credentials = loadCredentials('/etc/easystock/esun/credentials.env');
    if (!credentials.ESUN_PASSWORD || !credentials.ESUN_CERT_PASS) throw Error('credentials_unavailable');
    const client = new EsunMarketdata({
      configPath: '/etc/easystock/esun/config.ini',
      config: { password: credentials.ESUN_PASSWORD, certPass: credentials.ESUN_CERT_PASS }
    });
    await client.login();
    const quote = await client.restClient.stock.intraday.quote({ symbol: 'IX0001' });
    if (quote?.symbol !== 'IX0001') throw Error('unexpected_index_symbol');
    // Never substitute local receipt time for the exchange's quote timestamp.
    const timestamp = quote?.lastUpdated || quote?.lastTrade?.time || quote?.closeTime;
    const change = Number(quote?.changePercent);
    if (!Number.isFinite(Number(timestamp)) || !Number.isFinite(change)) throw Error('invalid_index_quote');
    process.stdout.write(JSON.stringify({ symbol: quote.symbol, name: quote.name,
      ts: Number(timestamp), change_rate: change }) + '\n');
  } catch (error) {
    process.stderr.write(`esun_quote_unavailable:${error?.name || 'Error'}\n`);
    process.exitCode = 1;
  }
})();
