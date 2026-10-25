'use strict';
const crypto=require('node:crypto');
const fs=require('node:fs');
const path=require('node:path');
const {parseArgs}=require('node:util');
const {httpsUrl}=require('../updater.cjs');
const desktop=path.resolve(__dirname,'..');
const workspace=path.dirname(desktop);
const {values}=parseArgs({options:{'init-key':{type:'boolean'},key:{type:'string'},installer:{type:'string'},version:{type:'string'},url:{type:'string'},notes:{type:'string'},output:{type:'string'},platform:{type:'string',default:'win32'},arch:{type:'string',default:'x64'}}});
const keyPath=path.resolve(values.key||path.join(workspace,'.local/desktop-release/update-key.pem'));
const trustPath=path.join(desktop,'update-trust.json');
function publicDer(key){return crypto.createPublicKey(key).export({type:'spki',format:'der'}).toString('base64');}
if(values['init-key']){
 fs.mkdirSync(path.dirname(keyPath),{recursive:true});
 if(!fs.existsSync(keyPath)){
  if(fs.existsSync(trustPath))throw new Error('A public update key already exists. Restore its matching private key; do not silently rotate installed trust.');
  const {privateKey}=crypto.generateKeyPairSync('ed25519');fs.writeFileSync(keyPath,privateKey.export({type:'pkcs8',format:'pem'}),{flag:'wx',mode:0o600});
 }
 const key=crypto.createPrivateKey(fs.readFileSync(keyPath));
 if(fs.existsSync(trustPath)&&JSON.parse(fs.readFileSync(trustPath,'utf8')).publicKey!==publicDer(key))throw new Error('Private key does not match the existing update trust key.');
 fs.writeFileSync(trustPath,JSON.stringify({algorithm:'ed25519',keyId:'personal-memory-release-1',publicKey:publicDer(key)},null,2)+'\n');
 console.log('Update signing key prepared. Only update-trust.json is public; back up the private key separately.');
}else{
 if(!values.installer||!values.version||!/^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.test(values.version))throw new Error('Use --installer FILE --version X.Y.Z [--url HTTPS_URL].');
 if(!((values.platform==='win32'&&values.arch==='x64')||(values.platform==='darwin'&&['arm64','x64'].includes(values.arch))))throw new Error('Unsupported release platform/architecture.');
 const installer=path.resolve(values.installer);if(path.extname(installer).toLowerCase()!==(values.platform==='darwin'?'.zip':'.exe')||!fs.statSync(installer).isFile())throw new Error('Choose an EXE for Windows or a signed application ZIP for macOS.');
 const key=crypto.createPrivateKey(fs.readFileSync(keyPath));
 const trust=JSON.parse(fs.readFileSync(trustPath,'utf8'));
 if(key.asymmetricKeyType!=='ed25519'||trust.publicKey!==publicDer(key))throw new Error('Private release key does not match the pinned desktop public key.');
 const bytes=fs.readFileSync(installer);
 const payload={version:values.version,platform:values.platform,arch:values.arch,url:values.url?httpsUrl(values.url):null,size:bytes.length,sha256:crypto.createHash('sha256').update(bytes).digest('hex'),notes:values.notes||''};
 if(payload.notes.length>8192)throw new Error('Release notes exceed 8192 characters.');
 const data=Buffer.from(JSON.stringify(payload));
 const envelope={signed:data.toString('base64'),signature:crypto.sign(null,data,key).toString('base64')};
 const output=path.resolve(values.output||path.join(path.dirname(installer),'release-'+values.version+'.json'));
 fs.writeFileSync(output,JSON.stringify(envelope,null,2)+'\n');
 console.log('Signed '+(payload.url?'remote':'offline')+' update manifest: '+output);
}
