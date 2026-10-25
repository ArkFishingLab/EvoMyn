'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {DEFAULT_UPDATE_FEED,WINDOWS_UPDATE_FEED,defaultUpdateFeed,resolveUpdateFeed}=require('../update-source.cjs');

test('fresh and legacy empty preferences use the public EvoMyn release feed',()=>{
 const expected='https://github.com/ArkFishingLab/EvoMyn/releases/latest/download/latest.json';
 assert.equal(WINDOWS_UPDATE_FEED,expected);
 assert.equal(defaultUpdateFeed('win32','x64'),expected);
 for(const value of [undefined,null,'','   '])assert.equal(resolveUpdateFeed(value,'win32','x64'),expected);
});
test('saved former official feeds migrate to the current repository',()=>{
 for(const value of [
  'https://github.com/clover-Saber/EvoMyn/releases/latest/download/latest.json',
  ' https://github.com/CLOVER-SABER/EVOMYN/releases/latest/download/latest.json ',
 ])assert.equal(resolveUpdateFeed(value),DEFAULT_UPDATE_FEED);
});
test('other paths at the former owner remain custom feeds',()=>{
 const custom='https://github.com/clover-Saber/EvoMyn/releases/download/custom/latest.json';
 assert.equal(resolveUpdateFeed(custom),custom);
});
test('a saved custom HTTPS update source is preserved',()=>{
 assert.equal(resolveUpdateFeed(' https://updates.example.test/latest.json '),'https://updates.example.test/latest.json');
});
test('an invalid saved source falls back safely without preventing app startup',()=>{
 for(const value of [false,42,'http://updates.example.test/feed','file:///local','https://user:password@updates.example.test/feed','invalid'])assert.equal(resolveUpdateFeed(value),DEFAULT_UPDATE_FEED);
});
