'use strict';
// Explicit read-only smoke check. Run with a temporary EASYSTOCK_MARKET_DATA_DIR.
const {Provider}=require('./provider');
if(!process.env.EASYSTOCK_MARKET_DATA_DIR)throw Error('temporary_data_directory_required');
const provider=new Provider();
const duration=Math.max(10000,Math.min(45000,Number(process.env.ESUN_SMOKE_MS)||22000));
const run=provider.run();
setTimeout(()=>{
  const row=provider.diagnostic;
  const result={connected:row.connected,authenticated:row.authenticated,subscribed:row.subscribed,
    subscription_count:row.subscription_count,heartbeat_received:!!row.last_heartbeat_at,
    received_event:!!row.last_event_at,normalized_indices:Object.keys(provider.quotes),
    error_code:row.error_code||null};
  console.log(JSON.stringify(result));
  process.exitCode=result.connected&&result.authenticated&&result.subscribed&&result.heartbeat_received&&result.normalized_indices.length===7?0:1;
  provider.stop();
},duration);
run.catch(()=>{console.error('smoke_storage_error');process.exitCode=1;});
