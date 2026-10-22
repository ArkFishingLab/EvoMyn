'use strict';
const crypto=require('node:crypto');
const fs=require('node:fs/promises');
const path=require('node:path');
const {parseArgs}=require('node:util');
const {validateFirmware}=require('../firmware-updater.cjs');
const {verifyFile}=require('../updater.cjs');
async function signFirmwareRelease({manifestFile,url,privateKey,publicKey}){
 const trusted=publicKey.export({format:'der',type:'spki'}),actual=crypto.createPublicKey(privateKey).export({format:'der',type:'spki'});
 if(privateKey.asymmetricKeyType!=='ed25519'||!trusted.equals(actual))throw new Error('Private release key does not match pinned update trust.');
 const source=path.resolve(manifestFile),info=await fs.lstat(source);
 if(!info.isFile()||info.isSymbolicLink()||info.size>16384||path.basename(source)!=='manifest.json')throw new Error('Choose the validated local manifest.json.');
 const local=JSON.parse(await fs.readFile(source,'utf8'));
 if(local.type!==undefined||local.url!=='/updates/firmware/'+local.sha256+'.bin')throw new Error('Local firmware manifest is invalid.');
 const payload=validateFirmware({...local,type:'evomyn-firmware',url});
 await verifyFile(path.join(path.dirname(source),payload.sha256+'.bin'),payload);
 const data=Buffer.from(JSON.stringify(payload));
 return Buffer.from(JSON.stringify({signed:data.toString('base64'),signature:crypto.sign(null,data,privateKey).toString('base64')},null,2)+'\n');
}
async function main(){
 const {values}=parseArgs({options:{manifest:{type:'string'},url:{type:'string'},output:{type:'string'},key:{type:'string'}}});
 if(!values.manifest||!values.url||!values.output)throw new Error('Use --manifest FILE --url HTTPS_VERSIONED_BIN_URL --output FILE. Validate the ESP image with device_updates.py before signing.');
 const desktop=path.resolve(__dirname,'..'),trust=require('../update-trust.json');
 const publicKey=crypto.createPublicKey({key:Buffer.from(trust.publicKey,'base64'),format:'der',type:'spki'});
 const privateKey=crypto.createPrivateKey(await fs.readFile(values.key||path.join(desktop,'../.local/desktop-release/update-key.pem')));
 const envelope=await signFirmwareRelease({manifestFile:values.manifest,url:values.url,privateKey,publicKey});
 await fs.writeFile(path.resolve(values.output),envelope);console.log('Signed firmware update manifest: '+path.resolve(values.output));
}
if(require.main===module)main().catch(error=>{console.error(error.message);process.exitCode=1;});
module.exports={signFirmwareRelease};
