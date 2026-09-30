'use strict';
const fs = require('node:fs');

function createClient() {
  const values = {};
  const filename = process.env.ESUN_CREDENTIALS_FILE || '/etc/easystock/esun/credentials.env';
  for (const raw of fs.readFileSync(filename, 'utf8').split(/\r?\n/)) {
    const line = raw.trim(), at = line.indexOf('=');
    if (at < 1 || line.startsWith('#')) continue;
    const key = line.slice(0, at).trim();
    if (!['ESUN_PASSWORD', 'ESUN_CERT_PASS'].includes(key)) continue;
    values[key] = line.slice(at + 1).trim().replace(/^(['"])(.*)\1$/, '$2');
  }
  if (!values.ESUN_PASSWORD || !values.ESUN_CERT_PASS) throw Error('credentials_unavailable');
  const { EsunMarketdata } = require('@esun/marketdata');
  return new EsunMarketdata({
    configPath: process.env.ESUN_CONFIG_FILE || '/etc/easystock/esun/config.ini',
    config: { password: values.ESUN_PASSWORD, certPass: values.ESUN_CERT_PASS }
  });
}
module.exports = { createClient };
