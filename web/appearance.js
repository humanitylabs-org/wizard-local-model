// Appearance v1: same-origin host only; no persistent skin state or navigation reload.
(() => {
  'use strict';
  const keys = ['canvas','base','chrome','overlay','surface','surface-raised','text','text-secondary','text-muted','border','accent','accent-soft','on-accent','reader-surface'];
  let revision = -1;
  const hosted = parent !== window;
  function apply(a) {
    if (!a || a.version !== 1 || !Number.isInteger(a.revision) || a.revision < revision || !/^[a-z0-9-]{1,64}$/.test(a.skin) || !['dark','light'].includes(a.colorScheme) || !['window','immersive','standalone'].includes(a.presentation)) return false;
    if (!a.tokens || !keys.every(k => typeof a.tokens[k] === 'string' && a.tokens[k].length < 256 && !/[;{}]|url\s*\(/i.test(a.tokens[k]) && CSS.supports('color', a.tokens[k]))) return false;
    const root = document.documentElement;
    for (const k of keys) root.style.setProperty('--wz-' + k, a.tokens[k]);
    root.style.setProperty('--wz-canvas', hosted ? 'transparent' : a.tokens.base);
    Object.assign(root.dataset,{skin:a.skin,colorScheme:a.colorScheme,presentation:a.presentation,hosted:hosted ? 'true':'false'});
    root.style.colorScheme = a.colorScheme;
    revision = a.revision;
    return true;
  }
  addEventListener('message', e => {
    if (!hosted || e.source !== parent || e.origin !== location.origin || e.data?.type !== 'wizard:appearance') return;
    if (apply(e.data.appearance)) parent.postMessage({type:'wizard:appearance:ack',revision}, location.origin);
  });
  if (hosted) {
    document.documentElement.dataset.hosted = 'true';
    document.documentElement.style.setProperty('--wz-canvas','transparent');
    parent.postMessage({type:'wizard:appearance:ready',version:1}, location.origin);
  }
})();
