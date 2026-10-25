'use strict';
const fs=require('node:fs');
const path=require('node:path');
module.exports=async context=>{
 const staged=JSON.parse(fs.readFileSync(path.join(__dirname,'../build/runtime/RUNTIME-SOURCES.json'),'utf8'));
 const arch=({0:'ia32',1:'x64',2:'armv7l',3:'arm64',4:'universal'})[context.arch];
 if(staged.platform!==context.electronPlatformName||staged.arch!==arch)throw new Error('Stage Python and dependencies natively for the requested platform/architecture before packaging.');
 if(context.electronPlatformName==='darwin'&&process.env.EVOMYN_MAC_ADHOC!=='1'&&
  !process.env.APPLE_API_KEY&&!process.env.APPLE_ID&&!process.env.APPLE_KEYCHAIN_PROFILE)throw new Error('Public Mac builds require notarization credentials. Use EVOMYN_MAC_ADHOC=1 only for local test builds.');
};
