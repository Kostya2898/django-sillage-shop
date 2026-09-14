/* ===========================================================================
   Поява елементів: маска для тексту, зсув для блоків
   ===========================================================================

   Головне рішення тут — `will-change` **знімається після анімації**. Якщо
   лишити його на елементі, браузер тримає окремий композиторний шар для
   кожного з них. На каталозі з тридцяти карток це тридцять шарів, які
   нікуди не зникають, — і сайт починає гальмувати саме там, де мав бути
   найгладкішим. Тому шар створюється перед рухом і прибирається по
   `transitionend`.

   Другий принцип: без JS сторінка мусить бути повністю видимою. Клас `js`
   на <html> ставиться першим рядком, і саме він вмикає початкові
   (приховані) стани в CSS. Скрипт не виконався — класу немає — усе видно.
   =========================================================================== */

(function () {
  'use strict';

  document.documentElement.classList.add('js');

  var calm = window.matchMedia('(prefers-reduced-motion: reduce)');

  function show(element) {
    element.classList.add('is-revealed');
  }

  // Порція елементів, яким треба з'явитись.
  var targets = document.querySelectorAll('.reveal, .reveal-group');

  if (calm.matches || !('IntersectionObserver' in window)) {
    // Рух не потрібен або спостерігач недоступний — показуємо все одразу.
    // Композиція та сама, просто без анімації.
    Array.prototype.forEach.call(targets, show);
    document.querySelectorAll('.reveal-line').forEach(show);
    return;
  }

  function releaseLayer(element) {
    element.style.removeProperty('will-change');
  }

  var observer = new IntersectionObserver(
    function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) {
          return;
        }

        var element = entry.target;

        // Шар — перед рухом.
        element.style.willChange = 'transform, opacity';
        show(element);

        // …і знімається, щойно рух закінчився.
        element.addEventListener(
          'transitionend',
          function handler() {
            releaseLayer(element);
            element.removeEventListener('transitionend', handler);
          },
          { once: true }
        );

        // Страховка: якщо `transitionend` не прийде (елемент прибрали з DOM,
        // анімацію перебили), шар усе одно не лишиться назавжди.
        window.setTimeout(function () {
          releaseLayer(element);
        }, 1200);

        observer.unobserve(element);
      });
    },
    {
      // Запускаємо трохи раніше, ніж елемент з'явиться: інакше рух починається
      // вже в кадрі й читається як запізнення.
      rootMargin: '0px 0px -12% 0px',
      threshold: 0.05,
    }
  );

  Array.prototype.forEach.call(targets, function (element) {
    observer.observe(element);
  });

  // Заголовки в першому екрані показуємо без спостерігача: вони вже в кадрі,
  // і чекати на перетин нема чого.
  var hero = document.querySelector('[data-reveal-immediate]');
  if (hero) {
    // Наступний кадр, щоб браузер встиг застосувати початковий стан —
    // інакше перехід не відбудеться й рядок просто з'явиться на місці.
    window.requestAnimationFrame(function () {
      hero.querySelectorAll('.reveal-line').forEach(show);
    });
  }
})();
