'use strict';
const path=require('node:path');
module.exports={
 // Preserve the installed NSIS identity so existing installations upgrade in place.
 appId:'com.personal-memory.desktop',
 productName:'EvoMyn',
 executableName:'EvoMyn',
 artifactName:'EvoMyn-Setup-${version}-${arch}.${ext}',
 electronDist:()=>path.dirname(require('electron')),
 asar:true,
 directories:{output:'dist',buildResources:'assets'},
 files:['main.cjs','preload.cjs','service-client.cjs','connection-flow.cjs','layout.cjs','startup.cjs','updater.cjs','firmware-updater.cjs','update-source.cjs','update-transport.cjs','security.cjs','update-trust.json','ui/**/*','assets/icon.*','package.json'],
 extraResources:[
  {from:'build/runtime',to:'backend',filter:['**/*','!**/__pycache__/**','!**/*.pyc','!**/*.pyo']},
  {from:'backend',to:'backend/scripts',filter:['*.py']}
 ],
 win:{target:[{target:'nsis',arch:['x64']}],icon:'assets/icon.ico',signExecutable:false},
 nsis:{oneClick:true,perMachine:false,allowElevation:false,createDesktopShortcut:true,createStartMenuShortcut:true,shortcutName:'EvoMyn',runAfterFinish:true,deleteAppDataOnUninstall:false},
 compression:'normal'
};
