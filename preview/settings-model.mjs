const DEFAULTS = { wifiEnabled: true, volume: 60, brightness: 80 };
function level(value, fallback, minimum) {
  return typeof value === 'number' && Number.isFinite(value)
    ? Math.min(100, Math.max(minimum, Math.round(value))) : fallback;
}
export function updateSettings(current = {}, patch = {}) {
  const value = { ...current, ...patch };
  return {
    wifiEnabled: typeof value.wifiEnabled === 'boolean' ? value.wifiEnabled : DEFAULTS.wifiEnabled,
    volume: level(value.volume, DEFAULTS.volume, 0),
    brightness: level(value.brightness, DEFAULTS.brightness, 5),
  };
}
export function loadSettings(raw) {
  try {
    const value = JSON.parse(raw);
    return updateSettings(value && typeof value === 'object' && !Array.isArray(value) ? value : {});
  } catch { return updateSettings(); }
}
