'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {DEFAULT_UPDATE_FEED,resolveUpdateFeed}=require('../update-source.cjs');

test('fresh and legacy empty preferences use the public EvoMyn release feed',()=>{
 const expected='https://github.com/clover-Saber/EvoMyn/releases/latest/download/latest.json';
 assert.equal(DEFAULT_UPDATE_FEED,expected);
 for(const value of [undefined,null,'','   '])assert.equal(resolveUpdateFeed(value),expected);
});
test('a saved custom HTTPS update source is preserved',()=>{
 assert.equal(resolveUpdateFeed(' https://updates.example.test/latest.json '),'https://updates.example.test/latest.json');
});
test('an invalid saved source falls back safely without preventing app startup',()=>{
 for(const value of [false,42,'http://updates.example.test/feed','file:///local','https://user:password@updates.example.test/feed','invalid'])assert.equal(resolveUpdateFeed(value),DEFAULT_UPDATE_FEED);
});
