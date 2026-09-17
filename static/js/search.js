/* ===========================================================================
   Живий пошук
   ===========================================================================

   Дебаунс 250 мс, від двох символів, з відміною попереднього запиту через
   `AbortController`. Без відміни швидкий набір дає гонку: відповідь на «ір»
   приходить після відповіді на «ірис» і перезаписує правильний результат
   старим.

   Без JS файл ні на що не впливає: форма лишається звичайною і веде на
   сторінку каталогу з `?q=`.
   =========================================================================== */

(function () {
  'use strict';

  var MIN_CHARS = 2;
  var DEBOUNCE = 250;

  var form = document.querySelector('[data-search]');
  if (!form) {
    return;
  }

  var input = form.querySelector('[data-search-input]');
  var results = form.querySelector('[data-search-results]');
  var toggle = form.querySelector('[data-search-toggle]');
  var clear = form.querySelector('[data-search-clear]');
  var submit = form.querySelector('.search__submit');

  // Кнопка «Знайти» потрібна лише без JS: тут Enter і так шукає, а зайва
  // кнопка на 360 px відбирає місце в самого поля.
  if (submit) {
    submit.hidden = true;
  }

  var endpoint = form.dataset.endpoint || form.getAttribute('action');
  var timer = null;
  var controller = null;
  var index = -1;

  /* --- згортання й розгортання на мобільному ------------------------- */

  if (toggle) {
    toggle.addEventListener('click', function () {
      var open = form.classList.toggle('is-open');
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (open) {
        input.focus();
      }
    });
  }

  if (clear) {
    clear.addEventListener('click', function () {
      input.value = '';
      clear.hidden = true;
      hide();
      input.focus();
    });
  }

  /* --- відкриття й закриття списку ----------------------------------- */

  function hide() {
    results.hidden = true;
    results.innerHTML = '';
    input.setAttribute('aria-expanded', 'false');
    index = -1;
  }

  function show(html) {
    results.innerHTML = html;
    results.hidden = false;
    input.setAttribute('aria-expanded', 'true');
    index = -1;
  }

  /* --- підсвітка збігу ------------------------------------------------ */

  /* Текст вставляється як розмітка, тож його треба екранувати вручну:
     назва товару приходить із бази, а база — це дані, не код. Без цього
     назва з `<` ламає дропдаун, а в гіршому випадку вставляє скрипт. */
  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function highlight(text, term) {
    var safe = escapeHtml(text);
    if (!term) {
      return safe;
    }

    var position = safe.toLowerCase().indexOf(term.toLowerCase());
    if (position < 0) {
      return safe;
    }

    return (
      safe.slice(0, position) +
      '<mark class="search__hit">' +
      safe.slice(position, position + term.length) +
      '</mark>' +
      safe.slice(position + term.length)
    );
  }

  /* --- розмітка ------------------------------------------------------- */

  function renderItem(item, term) {
    var thumb = item.image
      ? '<img class="search__thumb" src="' + escapeHtml(item.image) + '" alt="" loading="lazy">'
      : '<span class="search__thumb"></span>';

    return (
      '<a class="search__item" role="option" href="' +
      escapeHtml(item.url) +
      '">' +
      thumb +
      '<span class="search__body">' +
      '<span class="search__name">' +
      highlight(item.name, term) +
      '</span>' +
      '<span class="search__meta">' +
      highlight(item.brand, term) +
      ' · ' +
      escapeHtml(item.price) +
      '</span>' +
      '</span></a>'
    );
  }

  /* Три skeleton-рядки, не спінер.

     Скелет показує майбутню форму списку, тож дропдаун не змінює висоту,
     коли приходять дані. Спінер цього не робить: список «стрибає» з нуля
     на повну висоту рівно в момент, коли по ньому вже ведуть курсор. */
  function renderSkeleton() {
    var row =
      '<div class="search__skeleton">' +
      '<span class="skeleton skeleton--thumb"></span>' +
      '<span class="skeleton--lines">' +
      '<span class="skeleton skeleton--text"></span>' +
      '<span class="skeleton skeleton--text"></span>' +
      '</span></div>';

    return row + row + row;
  }

  function renderEmpty(payload) {
    var html =
      '<p class="search__empty">Нічого не знайшлося на «' +
      escapeHtml(payload.query) +
      '». Можливо, аромат називається інакше — спробуйте пошук за нотою.</p>';

    if (payload.fallback && payload.fallback.length) {
      html +=
        '<div class="search__group-label">Що беруть найчастіше</div>' +
        payload.fallback
          .map(function (item) {
            return renderItem(item, '');
          })
          .join('');
    }

    return html;
  }

  /* --- запит ---------------------------------------------------------- */

  function request(term) {
    if (controller) {
      controller.abort();
    }
    controller = new AbortController();

    fetch(endpoint + '?q=' + encodeURIComponent(term), {
      signal: controller.signal,
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
    })
      .then(function (response) {
        // 429 — не збій, а ліміт: у відповіді вже є текст для людини,
        // і «пошук недоступний» замість нього збрехав би.
        if (response.status === 429) {
          return response.json().then(function (payload) {
            show('<p class="search__empty">' + escapeHtml(payload.error) + '</p>');
            return null;
          });
        }
        if (!response.ok) {
          throw new Error('HTTP ' + response.status);
        }
        return response.json();
      })
      .then(function (payload) {
        if (!payload) {
          return;
        }
        if (payload.results.length) {
          show(
            payload.results
              .map(function (item) {
                return renderItem(item, payload.query);
              })
              .join('')
          );
        } else {
          show(renderEmpty(payload));
        }
      })
      .catch(function (error) {
        // Скасований запит — не помилка, а нормальний хід подій при наборі.
        if (error.name === 'AbortError') {
          return;
        }
        show('<p class="search__empty">Пошук недоступний. Спробуйте ще раз.</p>');
      });
  }

  /* --- ввід ----------------------------------------------------------- */

  input.addEventListener('input', function () {
    var term = input.value.trim();

    if (clear) {
      clear.hidden = !term;
    }

    window.clearTimeout(timer);

    if (term.length < MIN_CHARS) {
      hide();
      return;
    }

    // Скелет показуємо одразу, не чекаючи дебаунсу: інакше між натисканням
    // і появою списку 250 мс порожнечі, і здається, що пошук не працює.
    show(renderSkeleton());

    timer = window.setTimeout(function () {
      request(term);
    }, DEBOUNCE);
  });

  /* --- клавіатура ----------------------------------------------------- */

  function options() {
    return results.querySelectorAll('.search__item');
  }

  function select(next) {
    var list = options();
    if (!list.length) {
      return;
    }

    if (index >= 0 && list[index]) {
      list[index].removeAttribute('aria-selected');
    }

    index = (next + list.length) % list.length;
    var current = list[index];
    current.setAttribute('aria-selected', 'true');
    // Прокручуємо лише всередині дропдауна, не всю сторінку.
    current.scrollIntoView({ block: 'nearest' });
  }

  input.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') {
      hide();
      return;
    }

    if (results.hidden) {
      return;
    }

    if (event.key === 'ArrowDown') {
      event.preventDefault();
      select(index + 1);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      select(index - 1);
    } else if (event.key === 'Enter') {
      var list = options();
      // Enter без вибраного рядка відправляє форму — тобто веде на сторінку
      // результатів. Це навмисно: інакше Enter «нічого не робить».
      if (index >= 0 && list[index]) {
        event.preventDefault();
        list[index].click();
      }
    }
  });

  /* --- закриття ------------------------------------------------------- */

  document.addEventListener('click', function (event) {
    if (!form.contains(event.target)) {
      hide();
    }
  });
})();
