/* ===========================================================================
   Моушн-движок
   ===========================================================================

   Порядок у файлі не випадковий: **перша ж перевірка — `prefers-reduced-motion`**,
   і при ній нічого не ініціалізується взагалі. Ні ScrollTrigger, ні
   спостерігач. Елементи просто ставляться у видимий стан, і сторінка виглядає
   завершеною, а не порожньою.

   Числа: поява 640 мс, секція 800 мс,
   каскад 70 мс, максимум 8 позицій, паралакс не більше 0.2.

   Бібліотеки «плавного скролу» тут немає свідомо. Спершу був Lenis, і він
   підміняв рідну прокрутку: разом із `scroll-behavior: smooth` сторінку
   згладжували двічі, і три оберти колеса давали 108 px замість ~300 та
   доїжджали 640 мс (зміряно). Магазин гортають, щоб знайти, а не щоб
   милуватись інерцією, — тому скрол рідний, а рух лише в появах і паралаксі.

   SplitText із GSAP тут не використовується навмисно: це платний плагін
   GSAP Club. Розбиття написане своє — і воно **зберігає пробіли й переноси**,
   бо саме на цьому ламається більшість самописних сплітерів: слова
   склеюються, і на вузькому екрані заголовок перетворюється в одне довге
   слово без можливості перенесення.
   =========================================================================== */

(function () {
  'use strict';

  var calm = window.matchMedia('(prefers-reduced-motion: reduce)');

  /* Показати все й вийти. Викликається і при `reduce`, і коли бібліотек
     немає: композиція в обох випадках та сама, зникає лише рух. */
  function revealEverything() {
    document.querySelectorAll('[data-reveal], [data-reveal-stagger]').forEach(function (node) {
      node.classList.add('is-revealed');
    });

    document.querySelectorAll('.reveal-line').forEach(function (node) {
      node.classList.add('is-revealed');
    });

    document.querySelectorAll('[data-parallax]').forEach(function (node) {
      node.style.transform = 'none';
    });
  }

  if (calm.matches) {
    revealEverything();
    return;
  }

  var hasGsap = typeof window.gsap !== 'undefined';
  var hasScrollTrigger = hasGsap && typeof window.ScrollTrigger !== 'undefined';

  if (hasScrollTrigger) {
    window.gsap.registerPlugin(window.ScrollTrigger);
  }

  /* =======================================================================
     Розбиття тексту
     ======================================================================= */

  /* Розбиває вміст на слова або символи, кожен у масці.

     Пробіли лишаються **окремими текстовими вузлами між обгортками**, а не
     всередині них і не викидаються. Через це рядок і далі може переноситись
     по словах: обгортки — `inline-block`, а пробіл між ними — звичайний
     пробіл, який браузер вважає точкою переносу.

     Другий бік тієї ж проблеми — доступність: `aria-label` з оригінальним
     текстом лишає скрінрідеру цілу фразу замість тридцяти окремих літер. */
  function split(node, mode) {
    var source = node.textContent;
    if (!source.trim()) {
      return [];
    }

    node.setAttribute('aria-label', source.trim());
    node.textContent = '';

    var pieces = mode === 'chars' ? Array.from(source) : source.split(/(\s+)/);
    var parts = [];

    pieces.forEach(function (piece) {
      if (!piece) {
        return;
      }

      // Пробіл — окремим текстовим вузлом, поза маскою.
      if (/^\s+$/.test(piece)) {
        node.appendChild(document.createTextNode(piece));
        return;
      }

      var mask = document.createElement('span');
      mask.className = 'split__mask';
      mask.setAttribute('aria-hidden', 'true');

      var inner = document.createElement('span');
      inner.className = 'split__part';
      inner.textContent = piece;

      mask.appendChild(inner);
      node.appendChild(mask);
      parts.push(inner);
    });

    return parts;
  }

  /* =======================================================================
     Гігієна композиторних шарів
     ======================================================================= */

  /* `will-change` ставиться перед анімацією і **знімається після**.

     Якщо лишити його на елементі, браузер тримає окремий шар для кожного.
     На каталозі з тридцяти карток це тридцять шарів, які нікуди не
     зникають, — і сайт починає гальмувати саме там, де мав бути гладким. */
  function withLayer(targets) {
    var list = Array.isArray(targets) ? targets : [targets];

    return {
      onStart: function () {
        list.forEach(function (node) {
          node.style.willChange = 'transform, opacity';
        });
      },
      onComplete: function () {
        list.forEach(function (node) {
          node.style.willChange = '';
        });
      },
    };
  }

  /* =======================================================================
     Один спостерігач на всі reveal-елементи
     ======================================================================= */

  /* Саме один, а не по спостерігачу на елемент: тридцять
     `IntersectionObserver` на сторінці — це тридцять окремих наборів
     колбеків, які браузер обслуговує незалежно. */
  var revealed = new WeakSet();

  var observer = new IntersectionObserver(
    function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting || revealed.has(entry.target)) {
          return;
        }

        revealed.add(entry.target);
        play(entry.target);
        observer.unobserve(entry.target);
      });
    },
    {
      // Трохи раніше, ніж елемент повністю в кадрі: інакше рух починається
      // вже на видимому елементі й читається як запізнення.
      rootMargin: '0px 0px -12% 0px',
      threshold: 0.05,
    }
  );

  function play(node) {
    var stagger = node.hasAttribute('data-reveal-stagger');

    if (!hasGsap) {
      // Без GSAP ту саму появу робить CSS — класом.
      node.classList.add('is-revealed');
      if (stagger) {
        node.querySelectorAll(':scope > *').forEach(function (child) {
          child.classList.add('is-revealed');
        });
      }
      return;
    }

    if (stagger) {
      var children = Array.prototype.slice.call(node.children);
      // Максимум 8 позицій: девʼята із затримкою 630 мс читається вже не як
      // каскад, а як «сайт гальмує». Решта показується групою.
      var cascade = children.slice(0, 8);
      var rest = children.slice(8);

      var layers = withLayer(cascade);
      window.gsap.to(cascade, {
        y: 0,
        opacity: 1,
        duration: 0.64,
        stagger: 0.07,
        ease: 'power3.out',
        onStart: layers.onStart,
        onComplete: layers.onComplete,
      });

      if (rest.length) {
        window.gsap.to(rest, { y: 0, opacity: 1, duration: 0.64, delay: 0.56, ease: 'power3.out' });
      }
      return;
    }

    var single = withLayer(node);
    window.gsap.to(node, {
      y: 0,
      opacity: 1,
      duration: 0.8,
      ease: 'power3.out',
      onStart: single.onStart,
      onComplete: single.onComplete,
    });
  }

  /* =======================================================================
     Ініціалізація утиліт-атрибутів
     ======================================================================= */

  function initReveal() {
    document.querySelectorAll('[data-reveal], [data-reveal-stagger]').forEach(function (node) {
      if (hasGsap) {
        var isStagger = node.hasAttribute('data-reveal-stagger');
        window.gsap.set(isStagger ? node.children : node, { y: 24, opacity: 0 });
      }
      observer.observe(node);
    });
  }

  function initSplit() {
    document.querySelectorAll('[data-split]').forEach(function (node) {
      var parts = split(node, node.getAttribute('data-split'));
      if (!parts.length) {
        return;
      }

      if (!hasGsap) {
        parts.forEach(function (part) {
          part.style.transform = 'none';
        });
        return;
      }

      window.gsap.set(parts, { yPercent: 110 });

      var layers = withLayer(parts);
      window.gsap.to(parts, {
        yPercent: 0,
        duration: 0.64,
        // Символи — швидше за слова: 30 літер по 70 мс це два секунди.
        stagger: node.getAttribute('data-split') === 'chars' ? 0.018 : 0.07,
        ease: 'power3.out',
        onStart: layers.onStart,
        onComplete: layers.onComplete,
        scrollTrigger: hasScrollTrigger
          ? { trigger: node, start: 'top 90%', once: true }
          : undefined,
      });
    });
  }

  function initParallax() {
    if (!hasScrollTrigger) {
      return;
    }

    document.querySelectorAll('[data-parallax]').forEach(function (node) {
      // Обмеження 0.2 — не побажання: більше читається як гойдалка, і
      // предмет починає «відклеюватись» від сторінки.
      var depth = Math.min(Math.abs(parseFloat(node.getAttribute('data-parallax')) || 0), 0.2);
      if (!depth) {
        return;
      }

      window.gsap.to(node, {
        yPercent: depth * -100,
        ease: 'none',
        scrollTrigger: {
          trigger: node,
          start: 'top bottom',
          end: 'bottom top',
          // `scrub: true`, а не число: рух прив'язаний до скролбару без
          // власної інерції — інакше предмет доїжджає вже після зупинки скролу.
          scrub: true,
        },
      });
    });
  }

  /* =======================================================================
     Старт
     ======================================================================= */

  initReveal();
  initSplit();
  initParallax();

  /* `refresh()` після `load`: до завантаження шрифтів і зображень висоти
     ще не остаточні, і всі тригери порахувались би не там, де опиняться. */
  if (hasScrollTrigger) {
    window.addEventListener('load', function () {
      window.ScrollTrigger.refresh();
    });

    // Те саме після AJAX-підміни контенту — каталог підміняє сітку фільтрами.
    window.addEventListener('content:replaced', function () {
      initReveal();
      window.ScrollTrigger.refresh();
    });
  }

  /* Якщо користувач змінить налаштування руху, не перезавантажуючи сторінку. */
  calm.addEventListener('change', function (event) {
    if (!event.matches) {
      return;
    }

    if (hasScrollTrigger) {
      window.ScrollTrigger.getAll().forEach(function (trigger) {
        trigger.kill();
      });
    }
    revealEverything();
  });

  window.SILLAGE = window.SILLAGE || {};
  window.SILLAGE.motion = {
    split: split,
    refresh: function () {
      if (hasScrollTrigger) {
        window.ScrollTrigger.refresh();
      }
    },
  };
})();
