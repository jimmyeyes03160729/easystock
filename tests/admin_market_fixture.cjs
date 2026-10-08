// Synthetic UI data only; no broker, Firebase, account or production payload.
module.exports=()=>({
  current:true,generated_at:'2026-10-08T11:17:45.655+08:00',
  breadth:{status:'UNKNOWN',valid:false,fresh:false,advancers:null,decliners:null,unchanged:null,coverage:null},
  rotation:{valid:true,fresh:true,rotation_state:'SHIPPING_LEADING'},
  sectors:{rows:[
    ['電子工業類指數',-.8265584366399896,-.08215566245668326,2],
    ['半導體類指數',-.865937602431537,-.12153482824823059,3],
    ['金融保險類指數',-1.3885451284119148,-.6441423542286084,5],
    ['電子零組件類指數',-.9152354146322731,-.17083264044896673,4],
    ['航運類指數',.7454431779925854,1.4898459521758918,1]
  ].map(([name,return_day,relative_to_taiex,rank])=>({name,return_day,relative_to_taiex,rank,valid:true,fresh:true,quote_at:'2026-10-08T11:17:45+08:00'}))}
});
