/* ===========================================================================
   SILLAGE — поведінка інтерфейсу
   ===========================================================================

   Без фреймворків і без jQuery. Усе на делегуванні від `document`: розмітка
   drawer-а приходить із сервера **і** підміняється з JSON-відповіді
   (`docs/frontend-api.md`), тож обробники, навішані на конкретні вузли при
   завантаженні, після першої ж підміни зникли б.

   Публічний інтерфейс — `window.SILLAGE`: його використовують `motion.js` і
   сторінкові скрипти.
   =========================================================================== */

(function () {
  'use strict';

  var doc = document;
  var body = doc.body;

  doc.documentElement.classList.add('js');

  /* =======================================================================
     CSRF і запити
     ======================================================================= */

  function getCookie(name) {
    var prefix = name + '=';
    var found = null;

    doc.cookie.split(';').forEach(function (raw) {
      var cookie = raw.trim();
      if (cookie.indexOf(prefix) === 0) {
        found = decodeURIComponent(cookie.slice(prefix.length));
      }
    });

    return found;
  }

  /* POST із CSRF-токеном.

     `X-Requested-With` тут обовʼязковий: саме за ним бекенд відрізняє запит
     на JSON від звичайного сабміту форми і віддає payload замість редіректу
     (див. `cart/services.wants_json`).

     Відмова за бізнес-правилом приходить зі статусом 200 і `ok: false` —
     наприклад «на складі лишилось 2 од.». Це нормальна відповідь, і ловити
     її в `catch` не треба; `catch` лишається для мережі й 4xx/5xx. */
  function postJSON(url, data) {
    var payload = new FormData();

    Object.keys(data || {}).forEach(function (key) {
      payload.append(key, data[key]);
    });

    return fetch(url, {
      method: 'POST',
      body: payload,
      credentials: 'same-origin',
      headers: {
        'X-Requested-With': 'XMLHttpRequest',
        'X-CSRFToken': getCookie('csrftoken') || '',
      },
    }).then(function (response) {
      if (!response.ok) {
        throw new Error('HTTP ' + response.status);
      }
      return response.json();
    });
  }

  /* =======================================================================
     Фокус-трап
     ======================================================================= */

  var FOCUSABLE = [
    'a[href]',
    'button:not([disabled])',
    'input:not([disabled]):not([type="hidden"])',
    'select:not([disabled])',
    'textarea:not([disabled])',
    '[tabindex]:not([tabindex="-1"])',
  ].join(',');

  /* Замикає Tab усередині контейнера і повертає фокус туди, звідки прийшли.

     Повернення фокуса — не дрібниця: без нього після закриття drawer-а Tab
     продовжує з початку документа, і той, хто працює з клавіатури, щоразу
     проходить усю шапку заново. */
  function trapFocus(container) {
    var previous = doc.activeElement;

    function items() {
      return Array.prototype.filter.call(
        container.querySelectorAll(FOCUSABLE),
        function (node) {
          return node.offsetParent !== null;
        }
      );
    }

    function onKeydown(event) {
      if (event.key !== 'Tab') {
        return;
      }

      var list = items();
      if (!list.length) {
        return;
      }

      var first = list[0];
      var last = list[list.length - 1];

      if (event.shiftKey && doc.activeElement === first) {
        event.preventDefault();
        last.focus({ preventScroll: true });
      } else if (!event.shiftKey && doc.activeElement === last) {
        event.preventDefault();
        first.focus({ preventScroll: true });
      }
    }

    container.addEventListener('keydown', onKeydown);

    /* `preventScroll` тут обов'язковий, а не «на всяк випадок».

       Оверлей — `position: fixed; inset: 0`, тобто в координатах документа
       він стоїть біля нуля. Звичайний `focus()` тягне елемент у видиму
       область і заради цього прокручує документ на початок — сторінка під
       меню тихо їде вгору, і після закриття користувач опиняється не там,
       де був. Знайшлося вимірюванням: 400 px до відкриття, 0 після. */
    var start = items()[0];
    if (start) {
      start.focus({ preventScroll: true });
    }

    return function release() {
      container.removeEventListener('keydown', onKeydown);
      if (previous && typeof previous.focus === 'function') {
        previous.focus({ preventScroll: true });
      }
    };
  }

  /* =======================================================================
     Блокування скролу
     ======================================================================= */

  /* Ширина скролбару компенсується падінгом.

     Без цього `overflow: hidden` на body забирає 15-17 px, які займав
     скролбар, сторінка стає ширшою — і весь вміст стрибає вбік у момент
     відкриття меню. Це найпомітніший дефект мобільних меню взагалі, і
     помічають його навіть ті, хто не розуміє, що саме сталося. */
  var scrollLocks = 0;
  var lockedAt = 0;

  function lockScroll() {
    scrollLocks += 1;
    if (scrollLocks > 1) {
      return;
    }

    /* Позицію запам'ятовуємо, бо `overflow: hidden` її стирає.

       Документ перестає прокручуватись, і браузер притискає зсув до нуля —
       не як анімацію, а миттєво. Видно це так: відкрив меню на середині
       каталогу, закрив — і ти на початку сторінки. Тест зловив саме це:
       400 px до відкриття, 0 під час і 0 після. */
    lockedAt = window.scrollY || doc.documentElement.scrollTop || 0;

    var gap = window.innerWidth - doc.documentElement.clientWidth;
    body.style.paddingRight = gap > 0 ? gap + 'px' : '';
    body.style.overflow = 'hidden';
  }

  function unlockScroll() {
    scrollLocks = Math.max(scrollLocks - 1, 0);
    if (scrollLocks > 0) {
      return;
    }

    body.style.paddingRight = '';
    body.style.overflow = '';

    if (!lockedAt) {
      return;
    }

    // Повертаємо позицію без плавності: інакше сторінка після закриття
    // меню сама їде вгору-вниз, і це читається як збій, а не як рух.
    // `behavior: 'instant'` обовʼязковий: у `html` стоїть `scroll-behavior:
    // smooth`, і звичайний `scrollTo` теж поїхав би анімацією.
    window.scrollTo({ top: lockedAt, behavior: 'instant' });

    lockedAt = 0;
  }

  /* =======================================================================
     Оверлеї: drawer і мобільне меню
     ======================================================================= */

  var openOverlay = null;

  function showOverlay(node, options) {
    if (openOverlay) {
      hideOverlay();
    }

    var settings = options || {};
    var scrim = doc.querySelector('.scrim');

    node.hidden = false;
    node.setAttribute('aria-hidden', 'false');
    // Наступний кадр: клас, доданий у тому ж кадрі, що й знятий `hidden`,
    // не дає переходу — початкового стану браузер ще не бачив.
    requestAnimationFrame(function () {
      node.classList.add('is-open');
    });

    if (settings.scrim !== false && scrim) {
      scrim.hidden = false;
      requestAnimationFrame(function () {
        scrim.classList.add('is-open');
      });
    }

    if (settings.blur !== false) {
      body.classList.add('has-overlay');
    }

    lockScroll();

    openOverlay = {
      node: node,
      scrim: settings.scrim !== false ? scrim : null,
      release: trapFocus(node),
      trigger: settings.trigger || null,
    };
  }

  function hideOverlay() {
    if (!openOverlay) {
      return;
    }

    var current = openOverlay;
    openOverlay = null;

    current.node.classList.remove('is-open');
    current.node.setAttribute('aria-hidden', 'true');

    if (current.scrim) {
      current.scrim.classList.remove('is-open');
    }

    body.classList.remove('has-overlay');
    unlockScroll();
    current.release();

    // `hidden` ставимо лише після переходу, інакше він не відтвориться.
    window.setTimeout(function () {
      if (!current.node.classList.contains('is-open')) {
        current.node.hidden = true;
        if (current.scrim) {
          current.scrim.hidden = true;
        }
      }
    }, 320);
  }

  /* =======================================================================
     Шапка: ховається на скрол униз
     ======================================================================= */

  function initHeader() {
    var header = doc.querySelector('[data-header]');
    if (!header) {
      return;
    }

    var lastY = window.scrollY;
    var ticking = false;

    // Читаємо позицію в rAF, а не в самому обробнику скролу: інакше на
    // кожну подію йде читання layout-властивості, і браузер змушений
    // синхронно перераховувати компонування.
    function update() {
      var y = window.scrollY;

      header.classList.toggle('is-stuck', y > 40);

      // Поки меню або оверлей відкриті, шапку не ховаємо: панель меню
      // прикріплена до неї й поїхала б за межі екрана.
      var locked = body.classList.contains('has-overlay') || header.querySelector('[open]');

      if (!locked && y > 160) {
        header.classList.toggle('is-hidden', y > lastY);
      } else {
        header.classList.remove('is-hidden');
      }

      lastY = y;
      ticking = false;
    }

    window.addEventListener(
      'scroll',
      function () {
        if (!ticking) {
          ticking = true;
          requestAnimationFrame(update);
        }
      },
      { passive: true }
    );

    update();
  }

  /* =======================================================================
     Мега-меню
     ======================================================================= */

  function initMega() {
    var mega = doc.querySelector('[data-mega]');
    if (!mega) {
      return;
    }

    var closeTimer = null;

    function open() {
      window.clearTimeout(closeTimer);
      mega.open = true;
    }

    function scheduleClose() {
      window.clearTimeout(closeTimer);
      // 150 мс: між пунктом меню і панеллю є щілина, і курсор, який її
      // перетинає, на мить виходить з обох. Без затримки меню зникає
      // просто тому, що мишу вели по прямій.
      closeTimer = window.setTimeout(function () {
        mega.open = false;
      }, 150);
    }

    mega.addEventListener('mouseenter', open);
    mega.addEventListener('mouseleave', scheduleClose);

    // Клавіатура: `<details>` розкривається Enter/Space сам, нам лишається
    // закриття по Esc і по виходу фокуса за межі.
    mega.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && mega.open) {
        mega.open = false;
        mega.querySelector('summary').focus();
      }
    });

    mega.addEventListener('focusout', function (event) {
      if (!mega.contains(event.relatedTarget)) {
        mega.open = false;
      }
    });

    doc.addEventListener('click', function (event) {
      if (mega.open && !mega.contains(event.target)) {
        mega.open = false;
      }
    });
  }

  /* =======================================================================
     Мобільне меню
     ======================================================================= */

  function initMobileMenu() {
    var menu = doc.querySelector('[data-mobile-menu]');
    var burger = doc.querySelector('[data-menu-open]');
    if (!menu || !burger) {
      return;
    }

    burger.addEventListener('click', function () {
      burger.setAttribute('aria-expanded', 'true');
      // Меню перекриває весь екран, тож розмивати контент під ним нема сенсу.
      showOverlay(menu, { scrim: false, blur: false, trigger: burger });
    });

    doc.addEventListener('click', function (event) {
      if (event.target.closest('[data-menu-close]')) {
        burger.setAttribute('aria-expanded', 'false');
        hideOverlay();
      }
    });
  }

  /* =======================================================================
     Drawer кошика
     ======================================================================= */

  function initDrawer() {
    var drawer = doc.querySelector('[data-drawer]');
    if (!drawer) {
      return;
    }

    doc.addEventListener('click', function (event) {
      var trigger = event.target.closest('[data-drawer-open]');
      if (trigger) {
        // Посилання лишається робочим без JS — тут перехоплюємо.
        event.preventDefault();
        showOverlay(drawer, { trigger: trigger });
        return;
      }

      if (event.target.closest('[data-overlay-close]')) {
        hideOverlay();
      }
    });
  }

  /* Підміна вмісту drawer-а розміткою з відповіді. */
  function renderCart(payload) {
    var holder = doc.querySelector('[data-drawer-content]');
    if (holder && payload.cart_html) {
      holder.innerHTML = payload.cart_html;
      // Розмітка приїхала з бекенду, тобто з кнопкою для роботи без JS.
      holder.querySelectorAll('.cart-row__apply').forEach(function (node) {
        node.hidden = true;
      });
    }

    if (typeof payload.count === 'number') {
      window.dispatchEvent(
        new CustomEvent('cart:updated', { detail: { count: payload.count } })
      );
    }
  }

  /* =======================================================================
     Степери й видалення позицій
     ======================================================================= */

  function initCartForms() {
    /* Кнопка «Оновити» існує для роботи без JS: там степер — це форма, і
       без сабміту зміна кількості нікуди не поїде. З JS вона зайва й
       збиває з пантелику — кількість уже застосована. Ховаємо її звідси, а
       не в CSS, бо `hidden` тут означає саме «JS працює». */
    doc.querySelectorAll('.cart-row__apply').forEach(function (node) {
      node.hidden = true;
    });

    doc.addEventListener('click', function (event) {
      var stepBtn = event.target.closest('[data-qty-form] .stepper__btn');
      if (stepBtn) {
        event.preventDefault();
        submitQuantity(stepBtn.closest('[data-qty-form]'), stepBtn.value);
        return;
      }

      var removeBtn = event.target.closest('[data-remove-form] button');
      if (removeBtn) {
        event.preventDefault();
        removeRow(removeBtn.closest('[data-remove-form]'));
      }
    });

    /* Додавання в кошик — тим самим запитом, що й решта кошика.

       Без цього кнопка «Додати в кошик» відкидала на сторінку кошика, і
       drawer, зроблений рівно для цього, не бачив ніхто: користувач і так
       уже опинявся там, куди drawer мав зайвий раз не водити. */
    doc.addEventListener('submit', function (event) {
      var form = event.target.closest('[data-add-form]');
      if (!form) {
        return;
      }

      event.preventDefault();

      var input = form.querySelector('[name="quantity"]');
      var button = form.querySelector('[type="submit"]');

      if (button) {
        button.disabled = true;
      }

      postJSON(form.action, { quantity: input ? input.value : 1 })
        .then(function (payload) {
          if (button) {
            button.disabled = false;
          }

          if (!payload.ok) {
            SILLAGE.toast(payload.error, 'error');
            return;
          }

          renderCart(payload);

          var drawer = doc.querySelector('[data-drawer]');
          if (drawer) {
            showOverlay(drawer, { trigger: doc.querySelector('[data-cart-trigger]') });
          }
        })
        .catch(function () {
          if (button) {
            button.disabled = false;
          }
          // Запит не дійшов — віддаємо форму браузеру, щоб товар усе ж
          // потрапив у кошик, навіть якщо сторінка при цьому перезавантажиться.
          form.submit();
        });
    });
  }

  /* Оптимістичне оновлення: число змінюється одразу, а не після відповіді.

     Старе значення зберігається, і при помилці повертається на місце —
     інакше інтерфейс показував би кількість, якої в кошику немає. Саме
     відкат, а не «сподіваємось, що вийде», робить оптимізм безпечним. */
  function submitQuantity(form, value) {
    if (!form) {
      return;
    }

    var row = form.closest('[data-cart-row]');
    var input = form.querySelector('[data-qty-input]');
    var previous = input ? input.value : null;
    var next = parseInt(value, 10);

    if (input) {
      input.value = next;
    }

    if (row) {
      row.classList.add('is-busy');
    }

    postJSON(form.action, { quantity: next })
      .then(function (payload) {
        if (payload.ok) {
          renderCart(payload);
          return;
        }

        // Відмова за бізнес-правилом: повертаємо число і показуємо причину.
        if (input && previous !== null) {
          input.value = previous;
        }
        if (row) {
          row.classList.remove('is-busy');
        }
        SILLAGE.toast(payload.error, 'error');
      })
      .catch(function () {
        if (input && previous !== null) {
          input.value = previous;
        }
        if (row) {
          row.classList.remove('is-busy');
        }
        SILLAGE.toast('Не вдалося оновити кошик. Спробуйте ще раз.', 'error');
      });
  }

  /* Видалення: рядок згортається, і лише потім приходить нова розмітка. */
  function removeRow(form) {
    if (!form) {
      return;
    }

    var row = form.closest('[data-cart-row]');

    postJSON(form.action, {})
      .then(function (payload) {
        if (!row) {
          renderCart(payload);
          return;
        }

        // Висоту фіксуємо в пікселях: анімувати `height: auto` неможливо,
        // а `max-height` із запасом дає ривок на початку.
        row.style.height = row.offsetHeight + 'px';
        row.classList.add('is-removing');

        requestAnimationFrame(function () {
          row.style.height = '0px';
        });

        window.setTimeout(function () {
          renderCart(payload);
        }, 250);
      })
      .catch(function () {
        SILLAGE.toast('Не вдалося видалити позицію.', 'error');
      });
  }

  /* =======================================================================
     Тости
     ======================================================================= */

  var TOAST_LIFE = 5000;
  var TOAST_MAX = 3;

  function initToasts() {
    var stack = doc.querySelector('[data-toast-stack]');
    if (!stack) {
      return;
    }

    Array.prototype.forEach.call(stack.querySelectorAll('[data-toast]'), armToast);

    doc.addEventListener('click', function (event) {
      var close = event.target.closest('[data-toast-close]');
      if (close) {
        dismissToast(close.closest('[data-toast]'));
      }
    });
  }

  function armToast(toast) {
    requestAnimationFrame(function () {
      toast.classList.add('is-visible');
    });

    var timer = window.setTimeout(function () {
      dismissToast(toast);
    }, TOAST_LIFE);

    // Пауза при наведенні: інакше тост із важливим текстом зникає саме тоді,
    // коли його почали читати.
    toast.addEventListener('mouseenter', function () {
      window.clearTimeout(timer);
    });

    toast.addEventListener('mouseleave', function () {
      timer = window.setTimeout(function () {
        dismissToast(toast);
      }, TOAST_LIFE);
    });
  }

  function dismissToast(toast) {
    if (!toast) {
      return;
    }

    toast.classList.remove('is-visible');
    window.setTimeout(function () {
      toast.remove();
    }, 240);
  }

  function toast(text, kind) {
    var stack = doc.querySelector('[data-toast-stack]');
    if (!stack || !text) {
      return;
    }

    // Стек до трьох: четвертий тост витісняє найстаріший, інакше серія
    // швидких дій заліплює півекрана.
    var existing = stack.querySelectorAll('[data-toast]');
    if (existing.length >= TOAST_MAX) {
      dismissToast(existing[0]);
    }

    var node = doc.createElement('div');
    node.className = 'toast toast--' + (kind || 'info');
    node.setAttribute('data-toast', '');

    var span = doc.createElement('span');
    span.className = 'toast__text';
    span.textContent = text;

    var close = doc.createElement('button');
    close.type = 'button';
    close.className = 'toast__close';
    close.setAttribute('data-toast-close', '');
    close.setAttribute('aria-label', 'Закрити повідомлення');
    close.textContent = '×';

    node.appendChild(span);
    node.appendChild(close);
    stack.appendChild(node);

    armToast(node);
  }

  /* =======================================================================
     Лічильник кошика
     ======================================================================= */

  function initCartCount() {
    window.addEventListener('cart:updated', function (event) {
      var counter = doc.querySelector('[data-cart-count]');
      if (!counter || !event.detail) {
        return;
      }

      counter.textContent = event.detail.count;

      counter.classList.remove('is-bumped');
      // Читання `offsetWidth` перезапускає анімацію: без цього повторне
      // додавання того самого класу нічого не робить.
      void counter.offsetWidth;
      counter.classList.add('is-bumped');
    });
  }

  /* =======================================================================
     Підписка в підвалі
     ======================================================================= */

  function initSubscribe() {
    var form = doc.querySelector('[data-subscribe]');
    if (!form) {
      return;
    }

    var input = form.querySelector('[data-subscribe-input]');
    var error = form.querySelector('[data-subscribe-error]');

    form.addEventListener('submit', function (event) {
      var value = input.value.trim();

      // Перевірка інлайн, біля поля — не списком угорі сторінки, до якого
      // треба вертатись очима.
      if (!value || value.indexOf('@') < 1 || value.indexOf('.') < 0) {
        event.preventDefault();
        input.setAttribute('aria-invalid', 'true');
        error.textContent = 'Перевірте адресу: потрібен формат name@example.com';
        error.hidden = false;
        input.focus();
        return;
      }

      input.removeAttribute('aria-invalid');
      error.hidden = true;
    });

    input.addEventListener('input', function () {
      if (input.getAttribute('aria-invalid')) {
        input.removeAttribute('aria-invalid');
        error.hidden = true;
      }
    });
  }

  /* =======================================================================
     Акордеон
     ======================================================================= */

  function initAccordion() {
    doc.addEventListener('click', function (event) {
      var trigger = event.target.closest('.accordion__trigger');
      if (!trigger) {
        return;
      }

      var item = trigger.closest('.accordion__item');
      var open = item.classList.toggle('is-open');
      trigger.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
  }

  /* =======================================================================
     Esc закриває все відкрите
     ======================================================================= */

  doc.addEventListener('keydown', function (event) {
    if (event.key !== 'Escape') {
      return;
    }

    if (openOverlay) {
      var burger = doc.querySelector('[data-menu-open]');
      if (burger) {
        burger.setAttribute('aria-expanded', 'false');
      }
      hideOverlay();
    }
  });

  /* =======================================================================
     Публічний інтерфейс і старт
     ======================================================================= */

  window.SILLAGE = {
    getCookie: getCookie,
    postJSON: postJSON,
    trapFocus: trapFocus,
    lockScroll: lockScroll,
    unlockScroll: unlockScroll,
    closeOverlay: hideOverlay,
    renderCart: renderCart,
    toast: toast,
  };

  initHeader();
  initMega();
  initMobileMenu();
  initDrawer();
  initCartForms();
  initToasts();
  initCartCount();
  initSubscribe();
  initAccordion();
})();
