import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadSettings, updateSettings } from '../preview/settings-model.mjs';

test('corrupt saved data restores usable defaults', () => {
  assert.deepEqual(loadSettings('{bad json'), { wifiEnabled: true, volume: 60, brightness: 80 });
  assert.deepEqual(loadSettings('null'), { wifiEnabled: true, volume: 60, brightness: 80 });
});
test('volume supports mute and brightness keeps a minimum visible level', () => {
  assert.deepEqual(updateSettings({}, {volume:-10,brightness:0}), {wifiEnabled:true,volume:0,brightness:5});
  assert.deepEqual(updateSettings({}, {volume:200,brightness:200}), {wifiEnabled:true,volume:100,brightness:100});
});
test('unknown saved fields are discarded and false wifi remains off', () => {
  assert.deepEqual(loadSettings('{"wifiEnabled":false,"volume":30,"brightness":55,"password":"discard"}'),
    {wifiEnabled:false,volume:30,brightness:55});
});
test('changing volume keeps the other settings', () => {
  assert.deepEqual(updateSettings({wifiEnabled:false,volume:60,brightness:70},{volume:0}),
    {wifiEnabled:false,volume:0,brightness:70});
});
test('invalid numeric values cannot blank the preview', () => {
  assert.equal(updateSettings({}, {brightness:NaN}).brightness,80);
  assert.equal(updateSettings({}, {volume:Infinity}).volume,60);
});
