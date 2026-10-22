'use strict';
// Keep the unprivileged dashboard inside the shell's inset content surface.
function contentBounds(width,height){
 if(width<=0||height<=0)return null;
 const rail=width<=1000?184:208;
 return {x:rail+1,y:9,width:Math.max(1,width-rail-10),height:Math.max(1,height-18)};
}
function contentSpacing(width){
 return width<=1000?{x:30,top:30}:{x:40,top:32};
}
module.exports={contentBounds,contentSpacing};
