/* TripMind AI - PWA glue: service worker registration + the browser
 * "Download / Install app" affordance.
 *
 * Browsers do not allow a page to install itself silently, so:
 *   - Chromium (Android/Edge/Chrome desktop) fires `beforeinstallprompt`; we
 *     stash the event and show an Install button that triggers the real
 *     browser dialog.
 *   - iOS Safari has no such event, so we show instructions
 *     (Share -> Add to Home Screen) instead of pretending an install is possible.
 *   - If the app is already installed (standalone display mode) nothing shows.
 */
(function () {
  'use strict';

  var DISMISS_KEY = 'tripmind.install.dismissed';
  var INSTALLED_KEY = 'tripmind.install.done';

  function isStandalone() {
    return (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches) ||
      window.navigator.standalone === true;
  }

  function isIOS() {
    return /iphone|ipad|ipod/i.test(window.navigator.userAgent) ||
      (window.navigator.platform === 'MacIntel' && window.navigator.maxTouchPoints > 1);
  }

  function dismissed() {
    try { return sessionStorage.getItem(DISMISS_KEY) === '1'; } catch (e) { return false; }
  }

  function markDismissed() {
    try { sessionStorage.setItem(DISMISS_KEY, '1'); } catch (e) { /* private mode */ }
  }

  function markInstalled() {
    try { localStorage.setItem(INSTALLED_KEY, '1'); } catch (e) { /* ignore */ }
  }

  function alreadyInstalled() {
    try { return localStorage.getItem(INSTALLED_KEY) === '1'; } catch (e) { return false; }
  }

  /* ---------------------------------------------------------------- banner */
  var banner = null;
  var bannerMode = null;

  /* Browsers with no install API get honest instructions instead of a button
   * that could not possibly work. */
  var MANUAL_HINT = {
    ios: 'Tap the Share button, then "Add to Home Screen".',
    firefox: 'Open the browser menu and choose "Install" (or pin this page).',
    safari: 'Open the File menu and choose "Add to Dock".',
    generic: 'Open your browser menu and choose "Install app".',
  };

  function manualHint() {
    if (isIOS()) return MANUAL_HINT.ios;
    var ua = window.navigator.userAgent || '';
    if (/firefox/i.test(ua)) return MANUAL_HINT.firefox;
    if (/safari/i.test(ua) && !/chrome|chromium|edg|crios/i.test(ua)) return MANUAL_HINT.safari;
    return MANUAL_HINT.generic;
  }

  function runInstall() {
    if (!deferred) { closeBanner(); return; }
    deferred.prompt();
    deferred.userChoice.then(function (choice) {
      if (choice && choice.outcome === 'accepted') markInstalled();
      deferred = null;
      closeBanner();
    });
  }

  /* mode: 'native' -> Install opens the real browser dialog
   *       'manual' -> no install API here, instructions only               */
  function buildBanner(mode) {
    if (banner) {
      // The browser only became installable after we already showed the
      // manual banner: upgrade it so the user still gets a working button.
      if (mode === 'native') upgradeBanner();
      return;
    }
    if (isStandalone() || alreadyInstalled() || dismissed()) return;

    bannerMode = mode;
    banner = document.createElement('div');
    banner.className = 'pwa-install';
    banner.setAttribute('role', 'dialog');
    banner.setAttribute('aria-label', 'Install TripMind AI');
    banner.innerHTML =
      '<div class="pwa-install-body">' +
      '<span class="pwa-install-icon" aria-hidden="true">' +
      '<img src="/img/favicon-32.png" alt="" width="34" height="34"></span>' +
      '<div class="pwa-install-text">' +
      '<strong>Get the TripMind AI app</strong>' +
      '<span>' + (mode === 'native'
        ? 'Install it for full screen and offline access.'
        : manualHint()) + '</span>' +
      '</div></div>' +
      '<div class="pwa-install-actions">' +
      (mode === 'native'
        ? '<button type="button" class="pwa-install-btn pwa-install-btn--primary pwa-install-yes">Install</button>'
        : '') +
      '<button type="button" class="pwa-install-btn pwa-install-no" aria-label="Dismiss">Not now</button>' +
      '</div>';

    document.body.appendChild(banner);

    var yes = banner.querySelector('.pwa-install-yes');
    if (yes) yes.addEventListener('click', runInstall);
    banner.querySelector('.pwa-install-no').addEventListener('click', function () {
      markDismissed();
      closeBanner();
    });
  }

  function upgradeBanner() {
    if (!banner || bannerMode === 'native') return;
    var hint = banner.querySelector('.pwa-install-text span');
    if (hint) hint.textContent = 'Install it for full screen and offline access.';
    var actions = banner.querySelector('.pwa-install-actions');
    if (actions && !actions.querySelector('.pwa-install-yes')) {
      var yes = document.createElement('button');
      yes.type = 'button';
      yes.className = 'pwa-install-btn pwa-install-btn--primary pwa-install-yes';
      yes.textContent = 'Install';
      actions.insertBefore(yes, actions.firstChild);
      yes.addEventListener('click', runInstall);
    }
    bannerMode = 'native';
  }

  function closeBanner() {
    if (banner && banner.parentNode) banner.parentNode.removeChild(banner);
    banner = null;
    bannerMode = null;
  }

  /* ------------------------------------------------- beforeinstallprompt */
  var deferred = null;

  window.addEventListener('beforeinstallprompt', function (e) {
    // Chrome: stop the mini-infobar, we render our own affordance.
    e.preventDefault();
    deferred = e;
    whenBodyReady(function () {
      buildBanner('native');
    });
  });

  window.addEventListener('appinstalled', function () {
    markInstalled();
    closeBanner();
  });

  function whenBodyReady(fn) {
    if (document.body) return fn();
    document.addEventListener('DOMContentLoaded', fn);
  }

  whenBodyReady(function () {
    /* Never leave the user with no install affordance at all. Chromium fires
     * `beforeinstallprompt` a beat after the page becomes eligible (and only
     * once a service worker is controlling), so give it a short grace period
     * and then fall back to the manual instructions. */
    setTimeout(function () {
      if (deferred || isStandalone() || alreadyInstalled() || dismissed()) return;
      buildBanner('manual');
    }, 2500);
  });

  /* ------------------------------------------------ service worker wiring */
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('/sw.js', { scope: '/' })
        .then(function (reg) {
          reg.addEventListener('updatefound', function () {
            var sw = reg.installing;
            if (!sw) return;
            sw.addEventListener('statechange', function () {
              // A new build is waiting: activate it so the next open is fresh.
              if (sw.state === 'installed' && navigator.serviceWorker.controller) {
                sw.postMessage('skip-waiting');
              }
            });
          });
        })
        .catch(function (err) {
          // http:// on a LAN address, or a browser without SW support.
          if (window.console && console.warn) {
            console.warn('[TripMind] service worker not registered:', err && err.message);
          }
        });
    });
  }
})();
