'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {contentBounds}=require('../layout.cjs');
test('embedded content fits inside the desktop surface at normal and compact sizes',()=>{
 for(const [width,height,rail] of [[1180,800,208],[880,640,184],[1000,700,184],[1001,700,208]]){
  const b=contentBounds(width,height);
  assert.equal(b.x,rail+1);assert.equal(b.y,9);
  assert.equal(b.x+b.width,width-9);assert.equal(b.y+b.height,height-9);
  assert.ok(b.width>600);assert.ok(b.height>600);
 }
});
test('minimized windows do not replace the last valid content layout with zero-sized bounds',()=>{
 assert.equal(contentBounds(0,0),null);
 assert.equal(contentBounds(1180,0),null);
 assert.equal(contentBounds(0,800),null);
});
