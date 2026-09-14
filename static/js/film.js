/* ===========================================================================
   Плівкове зерно: мерехтіння на 12 кадрах/с
   ===========================================================================

   Чому не CSS-анімація. Анімація з 12 ключовими кадрами на секунду все одно
   інтерполюється браузером **між** кадрами, тож рвана частота губиться і
   виходить плавне ковзання зерна — те саме, що й на 60 кадрах.

   Чому не 60 кадрів. Справжня плівка мерехтить рвано. Зерно, що змінюється
   кожен кадр, око читає не як плівку, а як брудний або несправний екран:
   воно «шипить». Побічна вигода 12 кадрів — удвадцятеро менше роботи для
   композитора браузера.

   Чому `background-position`, а не перемальовування шуму. Позиція зсуває
   готовий тайл, тобто робота лишається на композиторі й не торкається
   компонування. Генерація нового шуму на кожному кадрі — це вже завдання
   для головного потоку.
   =========================================================================== */

(function () {
  'use strict';

  var FPS = 12;
  var INTERVAL = 1000 / FPS;
  var STEPS = 8;

  var layer = document.querySelector('.film-grain');
  if (!layer) {
    return;
  }

  // Прохання прибрати рух стосується й зерна: мерехтіння в спокої — саме те,
  // від чого просять звільнити. Шар лишається, але стоїть.
  var calm = window.matchMedia('(prefers-reduced-motion: reduce)');
  if (calm.matches) {
    return;
  }

  // Набір заздалегідь порахованих зсувів. Випадкове число на кожному кадрі
  // дало б те саме візуально, але зайву роботу — а тут її і так небагато.
  var offsets = [];
  for (var i = 0; i < STEPS; i++) {
    offsets.push(
      Math.round((i * 37) % 128) + 'px ' + Math.round((i * 71) % 128) + 'px'
    );
  }

  var index = 0;
  var timer = null;

  function tick() {
    index = (index + 1) % STEPS;
    layer.style.setProperty('--grain-shift', offsets[index]);
  }

  function start() {
    if (timer === null) {
      timer = window.setInterval(tick, INTERVAL);
    }
  }

  function stop() {
    if (timer !== null) {
      window.clearInterval(timer);
      timer = null;
    }
  }

  // У прихованій вкладці зерно нікому не потрібне, а таймер там усе одно
  // працює і тримає процесор.
  document.addEventListener('visibilitychange', function () {
    if (document.hidden) {
      stop();
    } else {
      start();
    }
  });

  // Якщо користувач змінить налаштування руху, не перезавантажуючи сторінку.
  calm.addEventListener('change', function (event) {
    if (event.matches) {
      stop();
      layer.style.removeProperty('--grain-shift');
    } else {
      start();
    }
  });

  start();
})();
