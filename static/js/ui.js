/* ===========================================================================
   Дрібна поведінка компонентів: оверлеї, акордеон, тости, лічильник кошика
   ===========================================================================
   Усе на делегуванні від `document`: розмітка приходить і з сервера, і з
   fetch (drawer кошика), тож навішувати обробники на конкретні вузли при
   завантаженні не можна — після підміни HTML вони зникнуть.
   =========================================================================== */

(function () {
  'use strict';

  var body = document.body;

  /* --- оверлеї: drawer і модалка ------------------------------------- */

  // Клас на <body> вмикає blur контенту: оверлей змінює фокусну відстань,
  // а не просто гасить світло.
  function openOverlay(node) {
    node.classList.add('is-open');
    body.classList.add('has-overlay');

    var scrim = document.querySelector('.scrim');
    if (scrim) {
      scrim.classList.add('is-open');
    }

    var focusable = node.querySelector(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    if (focusable) {
      focusable.focus();
    }
  }

  function closeOverlays() {
    document.querySelectorAll('.drawer.is-open, .modal.is-open').forEach(function (node) {
      node.classList.remove('is-open');
    });

    var scrim = document.querySelector('.scrim');
    if (scrim) {
      scrim.classList.remove('is-open');
    }

    body.classList.remove('has-overlay');
  }

  document.addEventListener('click', function (event) {
    var opener = event.target.closest('[data-open]');
    if (opener) {
      var target = document.querySelector(opener.getAttribute('data-open'));
      if (target) {
        event.preventDefault();
        openOverlay(target);
      }
      return;
    }

    if (event.target.closest('[data-close], .scrim')) {
      closeOverlays();
    }
  });

  // Escape закриває оверлей. Без цього модалка стає пасткою для клавіатури.
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') {
      closeOverlays();
    }
  });

  /* --- акордеон ------------------------------------------------------ */

  document.addEventListener('click', function (event) {
    var trigger = event.target.closest('.accordion__trigger');
    if (!trigger) {
      return;
    }

    var item = trigger.closest('.accordion__item');
    var open = item.classList.toggle('is-open');
    trigger.setAttribute('aria-expanded', open ? 'true' : 'false');
  });

  /* --- тости --------------------------------------------------------- */

  document.addEventListener('click', function (event) {
    var close = event.target.closest('[data-toast-close]');
    if (!close) {
      return;
    }

    var toast = close.closest('.toast');
    toast.classList.remove('is-visible');
    // Прибираємо з DOM лише після переходу, інакше він не відтвориться.
    toast.addEventListener(
      'transitionend',
      function () {
        toast.remove();
      },
      { once: true }
    );
  });

  /* --- лічильник кошика ---------------------------------------------- */

  // Єдине місце на сайті з перельотом, і не більше 6%. Він тут доречний,
  // бо повідомляє «число змінилось»; деінде переліт нічого не повідомляє.
  window.addEventListener('cart:updated', function (event) {
    var counter = document.querySelector('[data-cart-count]');
    if (!counter) {
      return;
    }

    if (event.detail && typeof event.detail.count === 'number') {
      counter.textContent = event.detail.count;
    }

    counter.classList.remove('is-bumped');
    // Читання `offsetWidth` перезапускає анімацію: без цього повторне
    // додавання того самого класу нічого не робить.
    void counter.offsetWidth;
    counter.classList.add('is-bumped');
  });
})();
