/* ===========================================================================
   Стайлгайд: динамічні зразки, перевірка шрифтів, повтор анімацій
   ===========================================================================

   Кольори зразків і ширини смуг задаються тут, а не в атрибуті `style`:
   інлайн-стилі в шаблонах цього проєкту заборонені. Значення приходять у
   `data-`атрибутах, а фактичний колір ставиться скриптом — на службовій
   сторінці це припустимо, бо йдеться про демонстрацію самих значень.
   =========================================================================== */

(function () {
  'use strict';

  /* --- зразки палітри ------------------------------------------------ */

  document.querySelectorAll('[data-sg-swatch]').forEach(function (node) {
    node.style.background = node.getAttribute('data-sg-swatch');
  });

  /* --- смуги шкали простору ------------------------------------------ */

  document.querySelectorAll('[data-sg-space]').forEach(function (node) {
    var step = node.getAttribute('data-sg-space');
    node.style.width = 'var(--space-' + step + ')';
  });

  /* --- перевірка шрифтів --------------------------------------------- */

  /* Головне: перевірка через `document.fonts.check` із **кириличним**
     рядком, а не на око. Підміна системним шрифтом майже незамітна
     візуально — Georgia замість Prata на дрібному кеглі не впадає в око
     нікому, крім того, хто знає, що шукати. А `font-family` у Computed
     показує те, що **запитали**, не те, що застосували. */

  var report = document.querySelector('[data-font-check]');
  if (report) {
    document.fonts.ready.then(function () {
      /* Літери й символ гривні перевіряються ОКРЕМО, і це не дрібниця.
         Перша версія питала обидва разом рядком «КИЇВ · 4 200 ₴» — і
         звітувала «кирилиця не завантажена», хоч кирилиця була на місці.
         Причина: у Google Fonts `₴` (U+20B4) лежить не в підмножині
         `cyrillic`, а в `cyrillic-ext`, яку браузер тягне окремо й ліниво.
         Об'єднаний рядок перетворював це на хибну тривогу про шрифт, якого
         немає, — а шукати довелося б зовсім не там. */
      var checks = [
        ['Prata · кирилиця', "400 80px 'Prata'", 'Реєстр ароматів'],
        ['Manrope · кирилиця', "400 16px 'Manrope'", 'Тридцять ароматів'],
        ['IBM Plex Mono · кирилиця', "400 11px 'IBM Plex Mono'", 'КИЇВ'],
        ['IBM Plex Mono · ₴ (cyrillic-ext)', "400 11px 'IBM Plex Mono'", '₴'],
      ];

      var lines = checks.map(function (item) {
        var ok = document.fonts.check(item[1], item[2]);
        return (
          '<span class="sg-check ' +
          (ok ? 'sg-check--pass' : 'sg-check--fail') +
          '">' +
          item[0] +
          ' — ' +
          (ok ? 'завантажено' : 'НЕ завантажено') +
          '</span>'
        );
      });

      report.innerHTML =
        'Перевірено <code>document.fonts.check</code> з реальними рядками: ' +
        lines.join(' · ') +
        '. Гривня в <code>cyrillic-ext</code> довантажується ліниво, тож на ' +
        'першому кадрі вона може ще не бути завантаженою — це поведінка ' +
        '<code>display=swap</code>, а не відсутній шрифт.';
    });
  }

  /* --- повтор появи маскою ------------------------------------------- */

  document.addEventListener('click', function (event) {
    if (!event.target.closest('[data-sg-replay]')) {
      return;
    }

    var host = document.querySelector('[data-reveal-immediate]');
    if (!host) {
      return;
    }

    var lines = host.querySelectorAll('.reveal-line');
    lines.forEach(function (line) {
      line.classList.remove('is-revealed');
    });

    // Наступний кадр, щоб браузер застосував початковий стан. Без цього
    // клас знімається й ставиться в межах одного кадру, і переходу немає.
    window.requestAnimationFrame(function () {
      window.requestAnimationFrame(function () {
        lines.forEach(function (line) {
          line.classList.add('is-revealed');
        });
      });
    });
  });

  /* --- лічильник кошика ---------------------------------------------- */

  document.addEventListener('click', function (event) {
    if (!event.target.closest('[data-sg-bump]')) {
      return;
    }

    var counter = document.querySelector('[data-cart-count]');
    var next = (parseInt(counter.textContent, 10) || 0) + 1;

    window.dispatchEvent(
      new CustomEvent('cart:updated', { detail: { count: next } })
    );
  });
})();
