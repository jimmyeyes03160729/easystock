'use strict';
// Read-only discovery: print index symbols/names, never the SDK's raw login result.
const { createClient } = require('./client');
(async () => {
  try {
    const client = createClient();
    await client.login();
    for (const exchange of ['TWSE', 'TPEx']) {
      const result = await client.restClient.stock.intraday.tickers({ type: 'INDEX', exchange });
      console.log(JSON.stringify({ exchange, indices: (result.data || []).map(({symbol, name}) => ({symbol, name})) }));
    }
    if (process.argv.includes('--quotes')) {
      for (const mapping of Object.values(require('./indices.json').indices)) {
        try {
          const data = await client.restClient.stock.intraday.quote({symbol:mapping.symbol});
          console.log(JSON.stringify({symbol:data.symbol,name:data.name,index:data.index,lastPrice:data.lastPrice,closePrice:data.closePrice,change:data.change,changePercent:data.changePercent,lastUpdated:data.lastUpdated}));
        } catch (_) { console.log(JSON.stringify({symbol:mapping.symbol,status:'unavailable'})); }
      }
    }
  } catch (_) { console.error('esun_discovery_failed'); process.exitCode = 1; }
})();
