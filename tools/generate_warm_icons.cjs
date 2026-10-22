const fs=require('fs'), path=require('path');
if (process.argv.includes('--help')) {
 console.log('Usage: node tools/generate_warm_icons.cjs [--output-dir DIR] [--icons FILE]');
 process.exit(0);
}
function option(name, fallback) {
 const i=process.argv.indexOf(name);
 if(i<0)return fallback;
 if(!process.argv[i+1] || process.argv[i+1].startsWith('--'))throw new Error(name+' requires a path');
 return path.resolve(process.argv[i+1]);
}
let sharp;
try { sharp=require('sharp'); }
catch { throw new Error('Install development dependencies with npm ci before generating icons.'); }
const board=option('--output-dir',path.resolve(__dirname,'../xiaozhi-firmware/main/boards/round-voice-175c'));
const paths=JSON.parse(fs.readFileSync(option('--icons',path.resolve(__dirname,'../assets/warm-icons.json')),'utf8'));
fs.mkdirSync(board,{recursive:true});
const icons={wifi:[24,'#a7b89a','wifi'],wifi_small:[16,'#b3b8aa','wifi'],settings:[20,'#b8bfae','settings'],back:[24,'#b0b6a8','back'],right:[16,'#5e6d51','right'],link:[24,'#c0c8b5','link'],link_amber:[27,'#e5bb83','link'],volume:[19,'#98a58b','volume'],sun:[19,'#98a58b','sun'],refresh:[17,'#b7c5a8','refresh'],eye:[18,'#a8b697','eye'],stop:[20,'#e3c99e','stop'],lock:[15,'#5c6d4d','lock'],check:[15,'#a4b78b','check']};
(async()=>{
 let code='#include <lvgl.h>\n#include "warm_assets.h"\n';
 let header='#pragma once\n#include <lvgl.h>\nextern "C" {\n';
 for(let size of [11,13,14,15,16,17,18,19,20,27])header+=`LV_FONT_DECLARE(warm_font_${size});\n`;
 for(let size of [31,64])header+=`LV_FONT_DECLARE(warm_digits_${size});\n`;
 header+='}\n';
 for(let [name,[size,color,key]] of Object.entries(icons)){
   const svg=`<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24" color="${color}" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.55">${paths[key]}</svg>`;
   let {data}=await sharp(Buffer.from(svg)).ensureAlpha().raw().toBuffer({resolveWithObject:true});
   // LVGL ARGB8888 is BGRA byte order on little-endian ESP32 and host.
   for(let i=0;i<data.length;i+=4){let r=data[i];data[i]=data[i+2];data[i+2]=r;}
   let variable='warm_icon_'+name;
   code+=`static const uint8_t ${variable}_data[]={${[...data].join(',')}};\n`;
   code+=`const lv_image_dsc_t ${variable}={.header={.magic=LV_IMAGE_HEADER_MAGIC,.cf=LV_COLOR_FORMAT_ARGB8888,.flags=0,.w=${size},.h=${size},.stride=${size*4}},.data_size=${data.length},.data=${variable}_data};\n`;
   header+=`extern const lv_image_dsc_t ${variable};\n`;
 }
 fs.writeFileSync(path.join(board,'warm_icons.cc'),code);
 fs.writeFileSync(path.join(board,'warm_assets.h'),header);
})().catch(error=>{console.error(error.message);process.exitCode=1;});
