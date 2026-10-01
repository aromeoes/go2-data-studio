function allowPermission(origin, url, permission, details = {}) {
  try {
    if (new URL(url).origin !== origin) return false;
    if (details.origin && new URL(details.origin).origin !== origin) return false;
    if (details.requestingUrl && new URL(details.requestingUrl).origin !== origin) return false;
    if (details.securityOrigin && new URL(details.securityOrigin).origin !== origin) return false;
    if (details.isMainFrame === false) return false;
  } catch { return false; }
  if (permission === 'media') {
    if (details.mediaTypes) return details.mediaTypes.length === 1 && details.mediaTypes[0] === 'audio';
    return details.mediaType === 'audio';
  }
  return ['fullscreen', 'clipboard-sanitized-write'].includes(permission);
}
module.exports = { allowPermission };
