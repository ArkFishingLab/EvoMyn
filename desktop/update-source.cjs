'use strict';
const {httpsUrl}=require('./updater.cjs');
const DEFAULT_UPDATE_FEED='https://github.com/ArkFishingLab/EvoMyn/releases/latest/download/latest.json';
const LEGACY_UPDATE_FEED='https://github.com/clover-saber/evomyn/releases/latest/download/latest.json';
function resolveUpdateFeed(value){
 if(typeof value!=='string'||!value.trim())return DEFAULT_UPDATE_FEED;
 try{
  const url=httpsUrl(value.trim());
  return url.toLowerCase()===LEGACY_UPDATE_FEED?DEFAULT_UPDATE_FEED:url;
 }catch{return DEFAULT_UPDATE_FEED;}
}
module.exports={DEFAULT_UPDATE_FEED,resolveUpdateFeed};
