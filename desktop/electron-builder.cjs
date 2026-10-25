'use strict';
const path=require('node:path');
module.exports={
 // Preserve the installed NSIS identity so existing installations upgrade in place.
 appId:'com.personal-memory.desktop',
 productName:'EvoMyn',
 executableName:'EvoMyn',
 artifactName:'EvoMyn-Setup-${version}-${arch}.${ext}',
 electronDist:()=>path.join(path.dirname(require.resolve('electron/package.json')),'dist'),
 asar:true,
 directories:{output:'dist',buildResources:'assets'},
 files:['main.cjs','preload.cjs','attachment-preload.cjs','attachments.cjs','service-client.cjs','connection-flow.cjs','layout.cjs','startup.cjs','platform.cjs','mac-updater.cjs','updater.cjs','firmware-updater.cjs','update-source.cjs','update-transport.cjs','security.cjs','update-trust.json','ui/**/*','assets/icon.*','assets/trayTemplate*.png','package.json'],
 beforePack:require('./scripts/check-runtime.cjs'),
 extraResources:[
  {from:'build/runtime',to:'backend',filter:['**/*','!**/__pycache__/**','!**/*.pyc','!**/*.pyo']},
  {from:'backend',to:'backend/scripts',filter:['*.py']}
 ],
 win:{target:[{target:'nsis',arch:['x64']}],icon:'assets/icon.ico',signExecutable:false},
 mac:{target:['dmg','zip'],icon:'assets/icon.icns',category:'public.app-category.productivity',
  artifactName:'EvoMyn-${version}-mac-${arch}.${ext}',minimumSystemVersion:'14.0',
  hardenedRuntime:process.env.EVOMYN_MAC_ADHOC!=='1',entitlements:'assets/entitlements.mac.plist',entitlementsInherit:'assets/entitlements.mac.plist',
  extendInfo:{NSLocalNetworkUsageDescription:'EvoMyn 为已配对的 ESP 设备提供局域网固件更新。',NSAppTransportSecurity:{NSAllowsLocalNetworking:true}},
  ...(process.env.EVOMYN_MAC_ADHOC==='1'?{identity:'-',notarize:false}:{forceCodeSigning:true})},
 nsis:{oneClick:true,perMachine:false,allowElevation:false,createDesktopShortcut:true,createStartMenuShortcut:true,shortcutName:'EvoMyn',runAfterFinish:true,deleteAppDataOnUninstall:false},
 compression:'normal'
};
