/* TripMind AI — shared UI behaviour (design-system runtime)
 * No dependencies. Safe to load on every page: every hook is optional.
 *   window.TM.reveal / drawer / drop / toast / forms / button / progress
 */
(function (global) {
  'use strict';

  var TM = {};
  global.TM = TM;

  /* ---------------------------------------------------------- motion prefs */
  var mqReduce = global.matchMedia ? global.matchMedia('(prefers-reduced-motion: reduce)') : { matches: false };
  TM.reducedMotion = function () { return !!mqReduce.matches; };
  if (mqReduce.addEventListener) {
    mqReduce.addEventListener('change', function () { if (mqReduce.matches) TM.showAll(); });
  }

  function onReady(fn) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn, { once: true });
    else fn();
  }
  TM.onReady = onReady;

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  TM.$ = $; TM.$$ = $$;

  function el(tag, cls, html) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html != null) n.innerHTML = html;
    return n;
  }
  TM.el = el;

  /* --------------------------------------------------------------- reveals */
  function initReveal(root) {
    var items = $$('[data-reveal], [data-stagger]', root || document);
    if (!items.length) return;
    if (TM.reducedMotion() || !('IntersectionObserver' in global)) { TM.showAll(); return; }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { e.target.classList.add('is-in'); io.unobserve(e.target); }
      });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.06 });
    items.forEach(function (n) { if (!n.classList.contains('is-in')) io.observe(n); });
  }
  TM.reveal = initReveal;
  TM.showAll = function () { $$('[data-reveal], [data-stagger]').forEach(function (n) { n.classList.add('is-in'); }); };

  /* ---------------------------------------------------------------- splash */
  /* Shown once per browser session, capped, and never blocks navigation.
   * Marks itself done on window load OR after maxWait, whichever is first. */
  function initSplash() {
    var node = $('[data-tm-splash]');
    if (!node) return;
    var seen = false;
    try { seen = !!global.sessionStorage.getItem('tmSplash'); } catch (e) { seen = false; }
    if (seen || TM.reducedMotion()) { node.remove(); return; }
    try { global.sessionStorage.setItem('tmSplash', '1'); } catch (e) { /* private mode */ }
    var maxWait = parseInt(node.getAttribute('data-tm-splash-max') || '1500', 10);
    var done = false;
    function finish() {
      if (done) return;
      done = true;
      node.setAttribute('data-done', 'true');
      global.setTimeout(function () { if (node.parentNode) node.parentNode.removeChild(node); }, 400);
    }
    var t0 = Date.now();
    function untilMax() { global.setTimeout(finish, Math.max(0, maxWait - (Date.now() - t0))); }
    if (document.readyState === 'complete') untilMax();
    else global.addEventListener('load', untilMax, { once: true });
    global.setTimeout(finish, maxWait + 900); // hard safety net
  }

  /* ------------------------------------------------------- navigation UI */
  function initNav() {
    // New .tm-nav drawer
    $$('[data-tm-drawer-open]').forEach(function (btn) {
      var id = btn.getAttribute('data-tm-drawer-open');
      var drawer = document.getElementById(id);
      if (!drawer) return;
      btn.addEventListener('click', function () { TM.drawer(drawer, true, btn); });
    });
    $$('.tm-drawer').forEach(function (drawer) {
      $$('[data-tm-drawer-close], .tm-drawer__scrim', drawer).forEach(function (n) {
        n.addEventListener('click', function () { TM.drawer(drawer, false); });
      });
      drawer.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') TM.drawer(drawer, false);
      });
    });

    // Legacy .navbar toggle (kept working, now animated)
    $$('.navbar .nav-toggle').forEach(function (btn) {
      var links = btn.parentNode.querySelector('.navbar-links');
      if (!links) return;
      btn.addEventListener('click', function () {
        var open = links.classList.toggle('open');
        btn.setAttribute('aria-expanded', open ? 'true' : 'false');
      });
      links.addEventListener('click', function (e) {
        if (e.target.tagName === 'A') { links.classList.remove('open'); btn.setAttribute('aria-expanded', 'false'); }
      });
    });

    // Sticky nav shadow
    var nav = $('.tm-nav');
    if (nav) {
      var onScroll = function () { nav.classList.toggle('tm-nav--scrolled', global.scrollY > 8); };
      global.addEventListener('scroll', onScroll, { passive: true });
      onScroll();
    }

    // Mark the active section
    var here = (global.location.pathname.split('/').pop() || 'index.html').toLowerCase();
    $$('.tm-nav__link, .tm-drawer__link').forEach(function (a) {
      var href = (a.getAttribute('href') || '').split('?')[0].split('/').pop().toLowerCase();
      if (href && href === here) a.setAttribute('aria-current', 'page');
    });
  }

  TM.drawer = function (drawer, open, trigger) {
    if (!drawer) return;
    drawer.setAttribute('data-open', open ? 'true' : 'false');
    if (trigger) trigger.setAttribute('aria-expanded', open ? 'true' : 'false');
    document.body.classList.toggle('tm-lock', open);
    var panel = $('.tm-drawer__panel', drawer);
    if (panel) {
      if (open) {
        var first = panel.querySelector('a, button');
        if (first && !TM.reducedMotion()) global.setTimeout(function () { first.focus(); }, 120);
      } else if (trigger) { trigger.focus(); }
    }
  };

  /* ------------------------------------------------------------- dropdowns */
  function initDrops() {
    $$('.tm-drop').forEach(function (drop) {
      var trigger = $('.tm-drop__trigger', drop);
      if (!trigger) return;
      trigger.addEventListener('click', function (e) {
        e.stopPropagation();
        var open = drop.getAttribute('data-open') === 'true';
        closeAllDrops();
        drop.setAttribute('data-open', open ? 'false' : 'true');
        trigger.setAttribute('aria-expanded', open ? 'false' : 'true');
      });
      drop.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') { drop.setAttribute('data-open', 'false'); trigger.setAttribute('aria-expanded', 'false'); trigger.focus(); }
      });
      // Summarise selected values into the closed trigger
      var summary = $('.tm-drop__summary', trigger);
      if (summary) {
        var sync = function () {
          var picked = $$('input:checked', drop);
          summary.textContent = picked.length
            ? picked.length + ' selected · ' + picked.slice(0, 2).map(function (i) { return i.dataset.label || i.value; }).join(', ') + (picked.length > 2 ? '…' : '')
            : 'None selected';
        };
        $$('input', drop).forEach(function (i) { i.addEventListener('change', sync); });
        sync();
        drop.addEventListener('change', function (e) {
          if (e.target.matches('input')) drop.dispatchEvent(new CustomEvent('tm:change', { bubbles: true, detail: { input: e.target } }));
        });
      }
    });
    document.addEventListener('click', function (e) {
      if (!e.target.closest('.tm-drop')) closeAllDrops();
    });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeAllDrops(); });
  }
  function closeAllDrops() {
    $$('.tm-drop[data-open="true"]').forEach(function (d) {
      d.setAttribute('data-open', 'false');
      var t = $('.tm-drop__trigger', d);
      if (t) t.setAttribute('aria-expanded', 'false');
    });
  }
  TM.closeDrops = closeAllDrops;

  /* ----------------------------------------------------------------- chips */
  TM.chipToggle = function (chip, on) {
    chip.setAttribute('aria-pressed', on ? 'true' : 'false');
    chip.classList.toggle('is-on', !!on);
  };

  /* ---------------------------------------------------------------- toasts */
  function toastHost() {
    var host = $('.tm-toasts');
    if (!host) {
      host = el('div', 'tm-toasts');
      host.setAttribute('role', 'status');
      host.setAttribute('aria-live', 'polite');
      document.body.appendChild(host);
    }
    return host;
  }
  TM.toast = function (message, kind, ms) {
    var host = toastHost();
    var node = el('div', 'tm-toast' + (kind ? ' tm-toast--' + kind : ''));
    node.appendChild(el('div', '', String(message == null ? '' : message)));
    var close = el('button', 'tm-toast__x', '&times;');
    close.type = 'button';
    close.setAttribute('aria-label', 'Dismiss');
    close.addEventListener('click', function () { node.remove(); });
    node.appendChild(close);
    host.appendChild(node);
    global.setTimeout(function () {
      node.style.transition = 'opacity .25s, transform .25s';
      node.style.opacity = '0';
      node.style.transform = 'translateY(8px)';
      global.setTimeout(function () { node.remove(); }, 260);
    }, ms || (kind === 'error' ? 6000 : 3600));
    return node;
  };

  /* --------------------------------------------------------- button states */
  TM.button = function (btn, loading) {
    if (!btn) return;
    btn.classList.toggle('is-loading', !!loading);
    if (loading) { btn.setAttribute('aria-busy', 'true'); btn.disabled = true; }
    else { btn.removeAttribute('aria-busy'); btn.disabled = false; }
  };

  /* ------------------------------------------------------------- validation */
  var EMAIL = /^[^\s@]+@[^\s@]+\.[a-z]{2,}$/i;
  TM.rules = {
    required: function (v) { return v.trim().length > 0 || 'This field is required.'; },
    email: function (v) { return EMAIL.test(v.trim()) || 'Enter a valid email address.'; },
    minlen: function (n) { return function (v) { return v.length >= n || 'Use at least ' + n + ' characters.'; }; },
    match: function (other) {
      return function (v, form) {
        var f = form.querySelector(other);
        return !f || v === f.value || 'Passwords do not match.';
      };
    }
  };

  function fieldError(input, message) {
    var wrap = input.closest('.tm-field') || input.parentNode;
    var box = wrap ? wrap.querySelector('.tm-error') : null;
    input.setAttribute('aria-invalid', message ? 'true' : 'false');
    if (box) {
      box.textContent = message || '';
      box.setAttribute('data-show', message ? 'true' : 'false');
    }
    if (message && box) input.setAttribute('aria-describedby', box.id || (box.id = 'err-' + Math.random().toString(36).slice(2, 8)));
    return !message;
  }
  TM.fieldError = fieldError;

  /* Attach inline validation.
   * opts: { onSubmit(values, form) } ; rules read from data-validate="required,email" */
  TM.forms = function (form, opts) {
    if (!form) return;
    opts = opts || {};
    var fields = $$('[data-validate]', form);

    function validateOne(input) {
      var spec = (input.getAttribute('data-validate') || '').split(',').map(function (s) { return s.trim(); }).filter(Boolean);
      var value = input.type === 'checkbox' ? (input.checked ? 'on' : '') : input.value;
      for (var i = 0; i < spec.length; i++) {
        var part = spec[i];
        var name = part.split(':')[0];
        var arg = part.slice(name.length + 1);
        var fn = TM.rules[name];
        if (!fn) continue;
        // minlen:8  /  match:#otherId  — parameters after the rule name
        var res = (name === 'minlen' || name === 'match') ? fn(arg, name) : fn(value, form);
        if (res !== true) return fieldError(input, res);
      }
      return fieldError(input, '');
    }

    fields.forEach(function (input) {
      var ev = (input.tagName === 'SELECT' || input.type === 'checkbox' || input.type === 'radio') ? 'change' : 'blur';
      input.addEventListener(ev, function () { validateOne(input); });
      input.addEventListener('input', function () {
        if (input.getAttribute('aria-invalid') === 'true') validateOne(input);
      });
    });

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var ok = true, firstBad = null;
      fields.forEach(function (input) {
        if (!validateOne(input) && ok) { ok = false; firstBad = input; }
      });
      if (!ok) {
        if (firstBad && firstBad.focus) firstBad.focus();
        TM.toast('Please fix the highlighted fields.', 'error');
        return;
      }
      var values = {};
      fields.forEach(function (i) { values[i.name || i.id] = i.type === 'checkbox' ? i.checked : i.value; });
      if (opts.onSubmit) opts.onSubmit(values, form);
    });
    return form;
  };

  /* -------------------------------------------------------- AI progress UI */
  /* Honest staged feedback: steps are marked done only when the caller says so. */
  TM.progress = function (root) {
    root = typeof root === 'string' ? $(root) : root;
    if (!root) return null;
    var steps = $$('.tm-pstep', root);
    var bar = $('.tm-progress__bar i', root);
    var api = {
      start: function () { api.set(0, 'active'); },
      set: function (index, state) {
        steps.forEach(function (s, i) {
          var st = i < index ? 'done' : i === index ? (state || 'active') : 'idle';
          s.setAttribute('data-state', st);
        });
        if (bar) bar.style.width = Math.max(6, Math.min(100, ((index + (state === 'done' ? 1 : 0.4)) / steps.length) * 100)) + '%';
      },
      finish: function () {
        steps.forEach(function (s) { s.setAttribute('data-state', 'done'); });
        if (bar) bar.style.width = '100%';
      }
    };
    return api;
  };

  /* ------------------------------------------------------------- utilities */
  TM.fmtMoney = function (n) {
    var v = Number(n);
    if (!isFinite(v)) return '—';
    return '₹' + Math.round(v).toLocaleString('en-IN');
  };
  TM.fmtTime = function (mins) {
    var h = Math.floor(mins / 60), m = Math.round(mins % 60);
    var ap = h >= 12 ? 'PM' : 'AM';
    var hh = h % 12; if (hh === 0) hh = 12;
    return (m ? hh + ':' + String(m).padStart(2, '0') : String(hh)) + ' ' + ap;
  };
  TM.esc = function (s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  };
  TM.slug = function (s) {
    return String(s == null ? '' : s).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  };

  /* -------------------------------------------------------------- autofocus */
  function initAutofocus() {
    var node = $('[data-tm-autofocus]');
    if (node && !TM.reducedMotion()) {
      global.setTimeout(function () { try { node.focus({ preventScroll: true }); } catch (e) { node.focus(); } }, 120);
    }
  }

  onReady(function () {
    initSplash();
    initNav();
    initDrops();
    initReveal();
    initAutofocus();
  });
})(window);
