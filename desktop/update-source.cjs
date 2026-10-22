'use strict';
const {httpsUrl}=require('./updater.cjs');
const DEFAULT_UPDATE_FEED='https://github.com/clover-Saber/EvoMyn/releases/latest/download/latest.json';
function resolveUpdateFeed(value){
 if(typeof value!=='string'||!value.trim())return DEFAULT_UPDATE_FEED;
 try{return httpsUrl(value.trim());}catch{return DEFAULT_UPDATE_FEED;}
}
module.exports={DEFAULT_UPDATE_FEED,resolveUpdateFeed};
