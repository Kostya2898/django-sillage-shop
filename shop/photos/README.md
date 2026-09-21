# Фото каталогу

Справжні фотографії з [Unsplash](https://unsplash.com). Ліцензія
[Unsplash License](https://unsplash.com/license) дозволяє безкоштовне
використання, зокрема комерційне, без дозволу й без обов'язкової атрибуції.
Автори все одно вказані нижче.

## Як відбиралися

Бренди в каталозі вигадані, тому на кадрі не має бути чужого логотипа:
флакон Chanel під назвою «Бергамот і папір» виглядав би як підробка.
Відсів ішов у три кроки:

1. **Автоматично**: лише безкоштовні фото (не Unsplash+), без назв брендів в
   описі, з темним домінантним кольором — під нуарну палітру сайту.
2. **Очима, мініатюрами**: відкинуто все, що не флакон. Описи Unsplash
   генеровані й брешуть: «флаконами» виявились шахова королева, вейп,
   пивна пляшка й свічник.
3. **Очима, на повний розмір**: відкинуто кадри, де читається справжній
   бренд. Таких знайшлося 18 — Chloé, Armani Sì та Acqua di Giò, Hermès H24,
   Margiela Replica, Diptyque, Chanel Chance, Lancôme Trésor, Le Labo
   Santal 33, doTERRA, Ashton & Moore та інші. На мініатюрах і в описах їх
   не було видно.

Для свічок, дифузорів і спрею підбиралися свічки, дифузори й спрей, а не
флакони парфуму.

## Як влаштовано

| Що | Де |
|---|---|
| Звідки кадри (вхід конвеєра) | `sources.json` |
| Готові кадри для проду | `catalogue/<slug>/{cover,thumb,angle,macro}.webp` |
| Опис готових кадрів | `catalogue/manifest.json` |

Прод заводить `catalogue/` командою `load_product_photos` на кожному старті
контейнера (`docker/entrypoint.sh`). Команда без numpy, тож працює в
полегшеному образі, і відновлює файли, які безкоштовний Render стирає при
перезапуску.

## Як відтворити або замінити фото

```powershell
.\.venv\Scripts\python.exe manage.py fetch_product_photos --from-urls shop/photos/sources.json --force --as-is
.\.venv\Scripts\python.exe manage.py export_product_photos
```

`--as-is` — без грейду. Грейд конвеєра писався під синтетичні рендери з
кольоровим тлом; на живих фото він малював сірі ореоли навколо предмета й
постеризував фактури.

## Автори

| Товар | Автор | Джерело |
|---|---|---|
| `ambra-1908` | [Fulvio Ciccolo](https://unsplash.com/@scentspiracy) | [сторінка фото](https://unsplash.com/photos/a-bottle-of-perfume-sitting-on-top-of-a-table-eX-FeKAgPe0) |
| `bergamot-i-papir` | [Fulvio Ciccolo](https://unsplash.com/@scentspiracy) | [сторінка фото](https://unsplash.com/photos/clear-glass-bottle-on-white-textile-BU46fEYMbsQ) |
| `discovery-set-visim-slidiv` | [Lera Ginzburg](https://unsplash.com/@ginzburg_l) | [сторінка фото](https://unsplash.com/photos/a-group-of-perfume-bottles-sitting-on-top-of-a-table-N8WxMVijPKw) |
| `dyfuzor-iris-i-pudra` | [GALINA BOGDANOVA](https://unsplash.com/@galibagi) | [сторінка фото](https://unsplash.com/photos/reed-diffuser-with-dried-flowers-on-black-background-TDYS1JOtNA0) |
| `dyfuzor-smereka-i-moh` | [Mindaugas Norvilas](https://unsplash.com/@norvilas) | [сторінка фото](https://unsplash.com/photos/a-black-vase-filled-with-white-flowers-on-top-of-a-table-6SM2hsGgOeI) |
| `hirkyi-apelsyn` | [Rae Wallis](https://unsplash.com/@raewallis) | [сторінка фото](https://unsplash.com/photos/clear-glass-bottle-with-orange-liquid-6uNdAlvwf98) |
| `inzhyrne-varennya` | [HACA Wedding](https://unsplash.com/@hacawedding) | [сторінка фото](https://unsplash.com/photos/two-small-glass-bottles-with-white-ribbons-on-green-moss-XOgMeL8ORg8) |
| `iris-siryi` | [HI! ESTUDIO](https://unsplash.com/@hiestudio) | [сторінка фото](https://unsplash.com/photos/a-green-glass-bottle-sitting-on-top-of-a-table-vPKQbgdaIo0) |
| `kava-z-kardamonom` | [Moon Moons](https://unsplash.com/@moonmoons_days) | [сторінка фото](https://unsplash.com/photos/a-small-bottle-sitting-on-top-of-a-pile-of-coffee-beans--yEm-sUarwY) |
| `kedrova-tysha` | [Viki C](https://unsplash.com/@vikic) | [сторінка фото](https://unsplash.com/photos/a-couple-of-empty-glass-bottles-sitting-on-top-of-a-moss-covered-ground-uKnm981Yufc) |
| `limoncello-opivdni` | [Fulvio Ciccolo](https://unsplash.com/@scentspiracy) | [сторінка фото](https://unsplash.com/photos/a-bottle-of-perfume-sitting-on-top-of-a-table-AdfA5C0c12M) |
| `myhdaleve-moloko` | [Muhammad Sulyman](https://unsplash.com/@msulyman) | [сторінка фото](https://unsplash.com/photos/a-clear-glass-bottle-with-a-silver-top-MDMrNFnyFQk) |
| `pivnichnyi-lis` | [Tuccera LLC](https://unsplash.com/@tuccera) | [сторінка фото](https://unsplash.com/photos/a-bottle-of-cologne-next-to-a-pine-cone-lB2pf0uuty0) |
| `refil-ambra-1908-100` | [Alexandr Popadin](https://unsplash.com/@irrabagon) | [сторінка фото](https://unsplash.com/photos/amber-glass-bottle-on-wooden-shelf-CXoRpXCD8ds) |
| `sandal-07` | [Manuel Gast](https://unsplash.com/@gama26) | [сторінка фото](https://unsplash.com/photos/a-glass-bottle-sitting-on-top-of-a-rock--UGWh_1rg3c) |
| `shkiryana-paliturka` | [Virender Singh](https://unsplash.com/@virender833) | [сторінка фото](https://unsplash.com/photos/a-bottle-of-perfume-with-a-rock-in-the-background-e4zT41x1btw) |
| `smola-i-sil` | [East Graphic](https://unsplash.com/@eastgraphic20) | [сторінка фото](https://unsplash.com/photos/a-perfume-bottle-rests-amongst-rocks-qvPAHCH6egM) |
| `solonyi-kamin` | [Niamh Wynne](https://unsplash.com/@niamhwynne) | [сторінка фото](https://unsplash.com/photos/a-cookie-sitting-on-top-of-a-glass-jar-80aqIQgbHrY) |
| `sprei-bila-shavliya` | [feey](https://unsplash.com/@feeypflanzen) | [сторінка фото](https://unsplash.com/photos/a-person-spraying-a-brown-bottle-with-a-sprayer-Qn5ZHJkF07Y) |
| `svichka-kedr-i-popil` | [Marc Ignacio](https://unsplash.com/@marcignacio_) | [сторінка фото](https://unsplash.com/photos/lighted-candle-7P4_9JxGcDc) |
| `svichka-ladan-i-smola` | [Andres F. Uran](https://unsplash.com/@andresuran) | [сторінка фото](https://unsplash.com/photos/selective-focus-photography-of-red-candle-2qP_xM2mWCY) |
| `svichka-lymonnyi-hai` | [David Tomaseti](https://unsplash.com/@dtomaseti) | [сторінка фото](https://unsplash.com/photos/close-up-of-lighted-candle-AaZlf5FgUws) |
| `tepla-kimnata` | [amir maleky](https://unsplash.com/@amirmaleky) | [сторінка фото](https://unsplash.com/photos/a-bottle-of-perfume-sitting-on-top-of-a-table-0GwwKISlBpg) |
| `travel-vetiver-obscure-10` | [Sven Alex](https://unsplash.com/@salex_productphoto) | [сторінка фото](https://unsplash.com/photos/a-clear-bottle-with-cork-on-a-wooden-board-M-ZOxnH0Fdk) |
| `troyanda-o-shostiy` | [Muhammad Sulyman](https://unsplash.com/@msulyman) | [сторінка фото](https://unsplash.com/photos/a-red-glass-bottle-with-a-red-cap-S6QxcHThViw) |
| `tuberoza-pislya-doschu` | [Kelly Sikkema](https://unsplash.com/@kellysikkema) | [сторінка фото](https://unsplash.com/photos/clear-drop-raaOq1ZZgnc) |
| `tuman-nad-fiordom` | [Joppe Spaa](https://unsplash.com/@spaablauw) | [сторінка фото](https://unsplash.com/photos/clear-glass-perfume-bottle-with-black-background-Y8kwv9_Vay8) |
| `tyutyun-i-med` | [Masoud Nikookalam](https://unsplash.com/@msdnikoo) | [сторінка фото](https://unsplash.com/photos/a-bottle-of-perfume-sitting-on-top-of-a-table-bgM0Pj1DK64) |
| `vetiver-obscure` | [Kelly Sikkema](https://unsplash.com/@kellysikkema) | [сторінка фото](https://unsplash.com/photos/selective-focus-photography-of-brown-tinted-glass-bottle-fQucGYNXAG8) |
| `zamshevyi-vechir` | [Shubham Dhage](https://unsplash.com/@theshubhamdhage) | [сторінка фото](https://unsplash.com/photos/a-black-and-red-background-with-a-bottle-NnXAJPo3bb0) |
