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

  function buildBanner(mode, onInstall) {
    if (banner || isStandalone() || alreadyInstalled() || dismissed()) return;

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
      '<span>' + (mode === 'ios'
        ? 'Tap the Share button, then "Add to Home Screen".'
        : 'Install it for full screen and offline access.') + '</span>' +
      '</div></div>' +
      '<div class="pwa-install-actions">' +
      (mode === 'ios' ? '' : '<button type="button" class="btn btn-primary btn-sm pwa-install-yes">Install</button>') +
      '<button type="button" class="btn btn-sm pwa-install-no" aria-label="Dismiss">Not now</button>' +
      '</div>';

    document.body.appendChild(banner);

    var yes = banner.querySelector('.pwa-install-yes');
    if (yes) {
      yes.addEventListener('click', function () {
        if (onInstall) onInstall();
        else closeBanner();
      });
    }
    banner.querySelector('.pwa-install-no').addEventListener('click', function () {
      markDismissed();
      closeBanner();
    });
  }

  function closeBanner() {
    if (banner && banner.parentNode) banner.parentNode.removeChild(banner);
    banner = null;
  }

  /* ------------------------------------------------- beforeinstallprompt */
  var deferred = null;

  window.addEventListener('beforeinstallprompt', function (e) {
    // Chrome: stop the mini-infobar, we render our own affordance.
    e.preventDefault();
    deferred = e;
    whenBodyReady(function () {
      buildBanner('native', function () {
        if (!deferred) return closeBanner();
        deferred.prompt();
        deferred.userChoice.then(function (choice) {
          if (choice && choice.outcome === 'accepted') markInstalled();
          deferred = null;
          closeBanner();
        });
      });
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
    // iOS never fires beforeinstallprompt: offer the manual steps instead.
    if (isIOS() && !isStandalone()) buildBanner('ios', null);
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
