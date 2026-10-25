'use strict';
const {httpsUrl}=require('./updater.cjs');
const WINDOWS_UPDATE_FEED='https://github.com/ArkFishingLab/EvoMyn/releases/latest/download/latest.json';
function defaultUpdateFeed(platform=process.platform,arch=process.arch){
 if(platform==='darwin'){
  if(!['arm64','x64'].includes(arch))throw new Error('Unsupported macOS architecture');
  return `https://github.com/ArkFishingLab/EvoMyn/releases/latest/download/latest-darwin-${arch}.json`;
 }
 return WINDOWS_UPDATE_FEED;
}
const DEFAULT_UPDATE_FEED=defaultUpdateFeed();
const LEGACY_UPDATE_FEED='https://github.com/clover-saber/evomyn/releases/latest/download/latest.json';
function resolveUpdateFeed(value,platform=process.platform,arch=process.arch){
 const fallback=defaultUpdateFeed(platform,arch);
 if(typeof value!=='string'||!value.trim())return fallback;
 try{
  const url=httpsUrl(value.trim());
  return [LEGACY_UPDATE_FEED,WINDOWS_UPDATE_FEED.toLowerCase()].includes(url.toLowerCase())?fallback:url;
 }catch{return fallback;}
}
module.exports={DEFAULT_UPDATE_FEED,WINDOWS_UPDATE_FEED,defaultUpdateFeed,resolveUpdateFeed};
