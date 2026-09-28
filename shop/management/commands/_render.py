"""Рейтрейсер флаконів на numpy: SDF-геометрія, скло, студійне світло.

Без сторонніх 3D-бібліотек і без мережі —
проєкт має підніматись із нуля будь-де.

Модуль починається з підкреслення, тому Django не вважає його командою.
"""

import numpy as np

# ---------------------------------------------------------------------------
# Палітра бренду (лінійний простір, не sRGB)
# ---------------------------------------------------------------------------


def srgb_to_linear(hex_color):
    """HEX → лінійний RGB. Освітлення рахується лише в лінійному просторі."""
    value = hex_color.lstrip('#')
    rgb = np.array([int(value[i : i + 2], 16) for i in (0, 2, 4)], dtype=np.float32) / 255.0
    return np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)


NOIR = srgb_to_linear('#0A090C')
SMOLA = srgb_to_linear('#16131B')
BRASS = srgb_to_linear('#C8A45C')
BONE = srgb_to_linear('#EFE9E1')

# Колір рідини за ольфакторною родиною.
LIQUID_COLORS = {
    'amber': np.array([0.72, 0.38, 0.10], dtype=np.float32),
    'gourmand': np.array([0.66, 0.34, 0.12], dtype=np.float32),
    'citrus': np.array([0.78, 0.68, 0.24], dtype=np.float32),
    'woody': np.array([0.42, 0.30, 0.20], dtype=np.float32),
    'floral': np.array([0.74, 0.46, 0.40], dtype=np.float32),
    'leather': np.array([0.40, 0.20, 0.09], dtype=np.float32),
    'aquatic': np.array([0.28, 0.40, 0.48], dtype=np.float32),
    'neutral': np.array([0.52, 0.44, 0.34], dtype=np.float32),
}

GLASS_IOR = 1.5
# Наскільки густо товща поглинає світло. Пара (ABSORPTION, BACK_COLOR)
# підібрана заміром, а не на око: за менших значень корпус іде в насичення
# ACES, і різниця товщі між центром і краєм зникає — скло виглядає
# керамікою. За більших — флакон чорніє, бо заломленому променю нічого
# доносити до камери. При 4.8 центр дає sRGB ≈ 0.34, край ≈ 0.45.
ABSORPTION = 4.8

MAX_STEPS = 84
MAX_DIST = 24.0
SURFACE_EPS = 0.0009


# ---------------------------------------------------------------------------
# Векторна арифметика
# ---------------------------------------------------------------------------


def normalize(v):
    length = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.maximum(length, 1e-9)


def dot(a, b):
    return np.sum(a * b, axis=-1, keepdims=True)


# ---------------------------------------------------------------------------
# Знакові функції відстані
# ---------------------------------------------------------------------------


def sd_round_box(p, half, radius):
    q = np.abs(p) - half
    outside = np.linalg.norm(np.maximum(q, 0.0), axis=-1)
    inside = np.minimum(np.max(q, axis=-1), 0.0)
    return outside + inside - radius


def sd_capped_cylinder(p, height, radius):
    d_xz = np.linalg.norm(p[..., [0, 2]], axis=-1) - radius
    d_y = np.abs(p[..., 1]) - height
    outside = np.linalg.norm(np.stack([np.maximum(d_xz, 0.0), np.maximum(d_y, 0.0)], -1), axis=-1)
    return np.minimum(np.maximum(d_xz, d_y), 0.0) + outside


def sd_elliptic_prism(p, semi_x, semi_z, height, radius):
    """Призма з еліптичним перерізом — форма реального флакона.

    Паралелепіпед тут не годиться принципово: у нього однакова товща по всій
    площі, тому поглинання в товщі скрізь однакове і скло виглядає керамікою.
    В еліпса шлях променя максимальний у центрі й прямує до нуля до країв —
    саме цей градієнт око читає як скло.
    """
    axes = np.array([semi_x, semi_z], dtype=np.float32)
    plane = p[..., [0, 2]]

    # Стандартне наближення SDF еліпса: точне на осях, трохи занижене по діагоналі.
    k1 = np.linalg.norm(plane / axes, axis=-1)
    k2 = np.linalg.norm(plane / (axes * axes), axis=-1)
    d_xz = k1 * (k1 - 1.0) / np.maximum(k2, 1e-6)

    d_y = np.abs(p[..., 1]) - height
    outside = np.linalg.norm(np.stack([np.maximum(d_xz, 0.0), np.maximum(d_y, 0.0)], -1), axis=-1)
    return np.minimum(np.maximum(d_xz, d_y), 0.0) + outside - radius


def smooth_union(a, b, k):
    """М'яке об'єднання: шийка вростає в корпус, а не приклеюється до нього."""
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0.0, 1.0)
    return b * (1 - h) + a * h - k * h * (1 - h)


class Bottle:
    """Геометрія флакона. Пропорції залежать від концентрації та slug-а."""

    def __init__(self, shape):
        self.body_half = np.array(shape['body'], dtype=np.float32)
        self.body_radius = shape['body_radius']
        self.neck_radius = shape['neck_radius']
        self.neck_height = shape['neck_height']
        self.cap_half = np.array(shape['cap'], dtype=np.float32)
        self.cap_radius = shape['cap_radius']

        self.body_top = self.body_half[1]
        self.neck_center = self.body_top + self.neck_height
        self.cap_center = self.neck_center + self.neck_height + self.cap_half[1]

        # Куля, що охоплює всю сцену — дешевий тест для відсіювання фону.
        self.bound_center = np.array([0.0, self.cap_center * 0.45, 0.0], dtype=np.float32)
        self.bound_radius = float(np.linalg.norm(self.body_half) + self.cap_center * 0.6 + 0.35)

    def glass(self, p):
        """SDF скляної частини: корпус плюс шийка."""
        body = sd_elliptic_prism(
            p,
            self.body_half[0],
            self.body_half[2],
            self.body_half[1],
            self.body_radius,
        )

        neck_p = p - np.array([0.0, self.neck_center, 0.0], dtype=np.float32)
        neck = sd_capped_cylinder(neck_p, self.neck_height, self.neck_radius)

        return smooth_union(body, neck, 0.12)

    def cap(self, p):
        cap_p = p - np.array([0.0, self.cap_center, 0.0], dtype=np.float32)
        return sd_round_box(cap_p, self.cap_half, self.cap_radius)

    @property
    def floor_y(self):
        """Рівень підлоги: трохи нижче дна, щоб між ними лишалася тінь."""
        return float(-(self.body_half[1] + 0.015))

    def scene(self, p):
        """Тіла сцени без підлоги. Повертає (відстань, ідентифікатор матеріалу).

        Підлога сюди навмисно не входить: вона нескінченна площина, і її
        перетин рахується аналітично в `render_frame`. Поки вона була в SDF,
        нижня половина кадру марширувала по 84 кроки на піксель — це і був
        головний споживач часу.
        """
        glass = self.glass(p)
        cap = self.cap(p)

        distance = np.minimum(glass, cap)
        material = np.where(glass <= cap, 0, 1).astype(np.int8)
        return distance, material

    def normal(self, p, field):
        """Нормаль центральними різницями — класика для SDF."""
        eps = 0.0012
        offsets = np.eye(3, dtype=np.float32) * eps
        grad = np.stack(
            [field(p + offsets[i]) - field(p - offsets[i]) for i in range(3)],
            axis=-1,
        )
        return normalize(grad)


# ---------------------------------------------------------------------------
# Освітлення
# ---------------------------------------------------------------------------

# Триточкове світло: ключове, заповнювальне й контурне.
KEY_DIR = normalize(np.array([-0.62, 0.58, 0.53], dtype=np.float32))
FILL_DIR = normalize(np.array([0.78, 0.12, 0.42], dtype=np.float32))
RIM_DIR = normalize(np.array([0.18, 0.52, -0.86], dtype=np.float32))
# Контрова панель (скрим) прямо за предметом. Без неї заломленому променю
# нічого доносити до камери, і скло виглядає чорною плитою.
BACK_DIR = normalize(np.array([-0.10, 0.20, -1.0], dtype=np.float32))

# Інтенсивності HDR: значення набагато більші за одиницю — їх стисне
# тонмапінг. Саме вони дають склу те, що можна відбити й пронести крізь товщу.
# Із «правильними» значеннями до 1.0 флакон виходить чорним силуетом.
KEY_COLOR = (BRASS * 0.55 + BONE * 0.45) * 26.0
FILL_COLOR = (BONE * 0.55 + BRASS * 0.15) * 5.0
RIM_COLOR = np.array([0.70, 0.76, 0.92], dtype=np.float32) * 18.0
# 0.5 — не «тьмяно», а свідомо: за яскравішої панелі ACES заганяє весь
# корпус у насичення, і градієнт товщі (центр темніший за край) зникає.
BACK_COLOR = (BONE * 0.75 + BRASS * 0.25) * 0.5


def environment(direction, backlit=False):
    """Що «бачить» промінь, який пішов у порожнечу.

    Не чорнота: тьмяний градієнт бренду плюс студійні джерела. Ключове
    зроблене софтбоксом, а не точкою, — від цього блік на плечі флакона
    стає видовженим, як у предметній зйомці, а не круглою цяткою.

    `backlit=True` вмикає контрову панель (скрим). У справжній студії вона
    стоїть за флаконом і закрита ним від камери; у нашій моделі геометрії
    джерел немає, тому оклюзію замінює цей прапорець — панель бачать лише
    промені, що вийшли крізь скло. Інакше вона світить прямо в об'єктив
    і кадр вибілюється.
    """
    up = np.clip(direction[..., 1:2] * 0.5 + 0.5, 0.0, 1.0)
    # Фон навмисно темний: кадр має жити в нуарі, а не на сірому папері.
    # Світло приходить із джерел нижче, а не з неба.
    sky = SMOLA * (0.10 + 0.55 * up) + NOIR * (1.0 - up) * 0.5

    def lobe(light_dir, color, tightness):
        angle = np.clip(dot(direction, light_dir.reshape(1, 3)), 0.0, 1.0)
        return color.reshape(1, 3) * (angle**tightness)

    glow = (
        # Софтбокс: помірно широка пляма плюс вузьке ядро. Ширшу за це
        # робити не можна — вона заливає весь фон і кадр сіріє.
        lobe(KEY_DIR, KEY_COLOR, 14.0) * 0.30
        + lobe(KEY_DIR, KEY_COLOR, 90.0) * 1.6
        + lobe(FILL_DIR, FILL_COLOR, 9.0) * 0.55
        + lobe(RIM_DIR, RIM_COLOR, 60.0) * 1.3
    )

    if backlit:
        # Широка й помірна: вона світить крізь товщу, а не в кадр.
        glow = glow + lobe(BACK_DIR, BACK_COLOR, 4.0) * 1.0

    return sky + glow


def soft_shadow(bottle, origin, direction, k=26.0):
    """М'яка тінь: чим ближче промінь проходить до тіла, тим темніше."""
    result = np.ones((origin.shape[0], 1), dtype=np.float32)
    travelled = np.full((origin.shape[0], 1), 0.06, dtype=np.float32)

    for _ in range(16):
        point = origin + direction * travelled
        distance = np.minimum(bottle.glass(point), bottle.cap(point))[..., None]
        result = np.minimum(result, np.clip(k * distance / np.maximum(travelled, 1e-4), 0.0, 1.0))
        travelled += np.clip(distance, 0.012, 0.30)

    return np.clip(result, 0.0, 1.0)


# ---------------------------------------------------------------------------
# Трасування
# ---------------------------------------------------------------------------


def march(bottle, origin, direction, sign=1.0, max_dist=MAX_DIST):
    """Сферичне трасування. `sign=-1` іде всередині скла.

    Марширують лише активні промені — інакше 7 мільйонів пікселів по сто
    кроків рахувалися б годинами.
    """
    count = origin.shape[0]
    travelled = np.zeros((count, 1), dtype=np.float32)
    hit = np.zeros(count, dtype=bool)
    material = np.zeros(count, dtype=np.int8)
    active = np.ones(count, dtype=bool)

    for _ in range(MAX_STEPS):
        if not active.any():
            break

        point = origin[active] + direction[active] * travelled[active]

        if sign > 0:
            distance, mat = bottle.scene(point)
        else:
            # Усередині скла цікавить лише його ж поверхня, і знак інвертовано.
            distance = -bottle.glass(point)
            mat = np.zeros(distance.shape, dtype=np.int8)

        reached = distance < SURFACE_EPS
        escaped = travelled[active, 0] > max_dist

        idx = np.flatnonzero(active)
        hit[idx[reached]] = True
        material[idx[reached]] = mat[reached]

        travelled[active, 0] += np.maximum(distance, SURFACE_EPS * 0.5)

        still = ~(reached | escaped)
        active[idx] = still

    return travelled, hit, material


def shade_opaque(bottle, point, normal, view, base_color, roughness, is_floor):
    """Матова поверхня: латунна кришка й підлога сцени."""
    ambient = environment(normal) * 0.06
    color = base_color * ambient

    # Тінь рахуємо один раз — від ключового світла. Заповнююче й контрове
    # широкі, власної читабельної тіні не дають, а кожне коштувало б ще
    # один повний обхід SDF на кожен піксель.
    key_shadow = soft_shadow(
        bottle, point + normal * 0.03, np.broadcast_to(KEY_DIR.reshape(1, 3), point.shape)
    )

    for light_dir, light_color, strength, shadowed in (
        (KEY_DIR, KEY_COLOR, 1.0, True),
        (FILL_DIR, FILL_COLOR, 1.0, False),
        (RIM_DIR, RIM_COLOR, 0.7, False),
    ):
        direction = np.broadcast_to(light_dir.reshape(1, 3), point.shape)
        lambert = np.clip(dot(normal, direction), 0.0, 1.0)
        shadow = key_shadow if shadowed else 0.55 + 0.45 * key_shadow

        diffuse = base_color * light_color.reshape(1, 3) * lambert * shadow * strength * 0.045

        half = normalize(direction - view)
        gloss = 2.0 / max(roughness, 0.03) ** 2
        spec = np.clip(dot(normal, half), 0.0, 1.0) ** gloss
        specular = light_color.reshape(1, 3) * spec * shadow * (0.02 if is_floor else 0.12)

        color = color + diffuse + specular

    if not is_floor:
        # Латунь — метал: вона переважно відбиває, а не розсіює.
        reflected = normalize(view - 2.0 * dot(view, normal) * normal)
        grazing = fresnel(np.clip(dot(normal, -view), 0.0, 1.0), f0=0.55)
        color = color + environment(reflected) * base_color * grazing * 0.35

    return color


def refract(direction, normal, eta):
    """Заломлення за Снеллом. Повертає (напрямок, чи сталося повне відбиття)."""
    cos_i = -dot(direction, normal)
    k = 1.0 - eta * eta * (1.0 - cos_i * cos_i)
    total_internal = k < 0.0
    safe_k = np.maximum(k, 0.0)
    refracted = eta * direction + (eta * cos_i - np.sqrt(safe_k)) * normal
    return normalize(refracted), total_internal[..., 0]


def fresnel(cos_theta, f0=0.04):
    """Апроксимація Шліка: під гострим кутом скло відбиває майже все."""
    return f0 + (1.0 - f0) * np.power(np.clip(1.0 - cos_theta, 0.0, 1.0), 5.0)


def shade_glass(bottle, point, normal, view, liquid_color):
    """Скло: Френель, заломлення, два внутрішні відбиття, поглинання товщі."""
    cos_theta = np.clip(dot(normal, -view), 0.0, 1.0)
    reflectance = fresnel(cos_theta)

    reflected_dir = normalize(view - 2.0 * dot(view, normal) * normal)
    reflected = environment(reflected_dir)

    inside_dir, _ = refract(view, normal, 1.0 / GLASS_IOR)
    origin = point - normal * 0.004
    transmitted = np.zeros_like(point)
    throughput = np.ones_like(point)

    for _ in range(2):
        travelled, hit, _ = march(bottle, origin, inside_dir, sign=-1.0, max_dist=14.0)
        exit_point = origin + inside_dir * travelled

        # Бугер — Ламберт: що довший шлях у склі, то темніша і кольоровіша товща.
        absorbed = np.exp(-ABSORPTION * travelled * (1.0 - liquid_color.reshape(1, 3)))
        throughput = throughput * absorbed

        exit_normal = -bottle.normal(exit_point, bottle.glass)
        out_dir, total_internal = refract(inside_dir, exit_normal, GLASS_IOR)

        escaping = ~total_internal & hit
        transmitted = np.where(
            escaping[..., None],
            # backlit=True: промінь, що вийшов крізь скло, бачить контрову
            # панель. Саме вона робить товщу видимою і кольоровою.
            transmitted + throughput * environment(out_dir, backlit=True),
            transmitted,
        )

        # Ті, що зазнали повного відбиття, роблять ще один прохід усередині.
        bounce_dir = normalize(inside_dir - 2.0 * dot(inside_dir, exit_normal) * exit_normal)
        inside_dir = np.where(total_internal[..., None], bounce_dir, inside_dir)
        origin = exit_point + inside_dir * 0.006

        if not total_internal.any():
            break

    return reflected * reflectance + transmitted * (1.0 - reflectance)


# ---------------------------------------------------------------------------
# Камера і кадр
# ---------------------------------------------------------------------------


def make_rays(width, height, camera_pos, target, fov_deg, roll=0.0):
    """Промені від камери. Вузький кут = телефото, менше спотворень."""
    aspect = width / height
    forward = normalize(target - camera_pos)
    world_up = np.array([np.sin(roll), np.cos(roll), 0.0], dtype=np.float32)
    right = normalize(np.cross(forward, world_up))
    up = np.cross(right, forward)

    # Пікселі беремо по центрах, інакше кадр зсувається на півпікселя.
    xs = (np.arange(width, dtype=np.float32) + 0.5) / width * 2.0 - 1.0
    ys = 1.0 - (np.arange(height, dtype=np.float32) + 0.5) / height * 2.0
    grid_x, grid_y = np.meshgrid(xs * aspect, ys)

    scale = np.tan(np.radians(fov_deg) * 0.5)
    directions = forward + right * (grid_x[..., None] * scale) + up * (grid_y[..., None] * scale)
    return normalize(directions.reshape(-1, 3).astype(np.float32))


def render_frame(bottle, liquid_color, width, height, camera_pos, target, fov, roll=0.0):
    """Один кадр у лінійному просторі, ще без плівкової обробки."""
    directions = make_rays(width, height, camera_pos, target, fov, roll)
    origins = np.broadcast_to(camera_pos.reshape(1, 3), directions.shape).astype(np.float32)

    color = environment(directions)
    count = directions.shape[0]

    # --- підлога: аналітичний перетин з площиною, без жодного маршу ---
    down = directions[..., 1] < -1e-5
    t_floor = np.full(count, np.inf, dtype=np.float32)
    t_floor[down] = (bottle.floor_y - origins[down, 1]) / directions[down, 1]
    t_floor[t_floor <= 0.0] = np.inf

    # --- тіла: марширують лише промені, що влучили в обмежувальну кулю ---
    to_center = bottle.bound_center.reshape(1, 3) - origins
    proj = dot(directions, to_center)
    perp_sq = dot(to_center, to_center) - proj * proj
    candidate = ((perp_sq < bottle.bound_radius**2) & (proj > 0))[..., 0]

    t_body = np.full(count, np.inf, dtype=np.float32)
    material = np.full(count, -1, dtype=np.int8)

    if candidate.any():
        travelled, hit, mat = march(bottle, origins[candidate], directions[candidate])
        idx = np.flatnonzero(candidate)[hit]
        t_body[idx] = travelled[hit, 0]
        material[idx] = mat[hit]

    # --- що ближче до камери, те й бачимо ---
    body_visible = t_body < t_floor
    floor_visible = np.isfinite(t_floor) & ~body_visible

    for mat_id, field, base, roughness in (
        (0, bottle.glass, None, None),
        (1, bottle.cap, BRASS * 0.85, 0.28),
    ):
        mask = body_visible & (material == mat_id)
        if not mask.any():
            continue

        p = origins[mask] + directions[mask] * t_body[mask, None]
        n = bottle.normal(p, field)

        if mat_id == 0:
            color[mask] = shade_glass(bottle, p, n, directions[mask], liquid_color)
        else:
            color[mask] = shade_opaque(
                bottle, p, n, directions[mask], base, roughness, is_floor=False
            )

    if floor_visible.any():
        floor_idx = np.flatnonzero(floor_visible)
        p_all = origins[floor_visible] + directions[floor_visible] * t_floor[floor_visible, None]

        # Підлога — світлова пляма під предметом, а не площина до горизонту.
        # Без швидкого згасання в кадрі видно її край і лінію горизонту.
        radius = np.linalg.norm(p_all[..., [0, 2]], axis=-1)
        fade = np.exp(-((radius / 1.5) ** 2))

        color[floor_idx] = environment(directions[floor_visible])

        # Далі за пляму підлога невідрізненна від фону, тож там не рахуємо ані
        # освітлення, ані мʼяку тінь. Це була найдорожча частина кадру: тінь
        # коштує повний обхід SDF на кожен піксель, а таких пікселів — пів кадру.
        lit = fade > 0.02
        if lit.any():
            visible_idx = floor_idx[lit]
            p = p_all[lit]
            n = np.broadcast_to(np.array([0.0, 1.0, 0.0], dtype=np.float32), p.shape)
            floor_color = shade_opaque(
                bottle, p, n, directions[visible_idx], BONE * 0.08, 0.5, is_floor=True
            )
            blend = fade[lit][..., None]
            color[visible_idx] = floor_color * blend + environment(directions[visible_idx]) * (
                1 - blend
            )

    return color.reshape(height, width, 3)


# ---------------------------------------------------------------------------
# Плівка
# ---------------------------------------------------------------------------


def aces_tonemap(x):
    """ACES-подібна крива Нарковича: стискає яскравості без випалених плям."""
    a, b, c, d, e = 2.51, 0.03, 2.43, 0.59, 0.14
    return np.clip((x * (a * x + b)) / (x * (c * x + d) + e), 0.0, 1.0)


# Параметри плівки. Винесені в константи, бо ними користується не лише
# рейтрейсер: той самий грейд накладається на справжні фотографії
# (`_photos.py`), інакше рендери й фото не лежали б в одному ряду.
FILM_CHROMA = 1.6
FILM_GRAIN = 0.007
FILM_VIGNETTE = 0.26
FILM_VIGNETTE_EXP = 2.2

# Кадр живе всередині палітри бренду: ані чистого чорного, ані білого.
# Нижня межа — Нуар #0A090C, верхня — Кістка #EFE9E1.
BLACK_FLOOR = np.array([0.039, 0.035, 0.047], dtype=np.float32)
WHITE_CEIL = np.array([0.937, 0.914, 0.882], dtype=np.float32)


def apply_film(image, rng, chroma=FILM_CHROMA, grain=FILM_GRAIN, vignette=FILM_VIGNETTE):
    """Тонмапінг → хроматична аберація → віньєтка → зерно → sRGB."""
    height, width, _ = image.shape
    image = aces_tonemap(image)

    ys = np.linspace(-1.0, 1.0, height, dtype=np.float32)[:, None]
    xs = np.linspace(-1.0, 1.0, width, dtype=np.float32)[None, :]
    radius = np.sqrt(xs**2 + ys**2) / np.sqrt(2.0)

    # Аберація тільки на краях — у центрі реальної оптики її немає.
    shift = (radius**2 * chroma).astype(np.int32)
    result = image.copy()
    rows = np.arange(height)[:, None]
    cols = np.arange(width)[None, :]
    result[..., 0] = image[rows, np.clip(cols + shift, 0, width - 1), 0]
    result[..., 2] = image[rows, np.clip(cols - shift, 0, width - 1), 2]

    result *= (1.0 - vignette * radius**FILM_VIGNETTE_EXP)[..., None]
    result += rng.normal(0.0, grain, size=(height, width, 1)).astype(np.float32)

    result = np.clip(result, 0.0, 1.0)
    # Лінійний → sRGB.
    result = np.where(result <= 0.0031308, result * 12.92, 1.055 * result ** (1 / 2.4) - 0.055)

    result = BLACK_FLOOR + result * (WHITE_CEIL - BLACK_FLOOR)

    return (np.clip(result, 0.0, 1.0) * 255.0).astype(np.uint8)
