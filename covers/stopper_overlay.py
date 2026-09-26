# -*- coding: utf-8 -*-
"""
Стоппер-панель: накладываем текстовую плашку на ИИ-арт (гибрид).
ИИ рисует сцену БЕЗ текста (кириллицу коверкает) — тег и заголовок пишем сами тут.
Рецепт и логика — в README.md рядом. Меняй блок НАСТРОЙКИ под конкретную обложку.
"""
from PIL import Image, ImageDraw, ImageFont

# ============ НАСТРОЙКИ (правь под обложку) ============
ART_PATH   = r"art-sketch.png"          # исходный арт без текста
OUT_PATH   = r"cover.png"               # куда сохранить результат
TAG        = "НЕЙРОСЕТИ"                # тег темы (верх панели, вразрядку)
HEADLINE   = ["ЯНДЕКС", "ОТДАЛ", "ДАРОМ"]   # заголовок стопкой
RED_WORD   = "ДАРОМ"                    # какое слово из заголовка красным
# =======================================================

# --- палитра (правь под свой бренд) ---
GREEN = (22, 54, 44)     # плашка
WHITE = (245, 245, 240)  # тег + основной заголовок
RED   = (216, 54, 44)    # акцентное слово (в тон красному кругу на арте)

# Шрифты обязаны содержать кириллицу — в этом весь смысл запасного пути.
# Пути указаны под Windows; на macOS/Linux подставь свои.
FB = r"C:\Windows\Fonts\ariblk.ttf"    # Arial Black — тег
FN = r"C:\Windows\Fonts\ARIALNB.TTF"   # Arial Narrow Bold — заголовок

img = Image.open(ART_PATH).convert("RGB")
W, H = img.size
draw = ImageDraw.Draw(img, "RGBA")

# левая сплошная панель ~34% ширины (арт должен держать эту зону спокойной)
PANEL_W = int(W * 0.34)
draw.rectangle([0, 0, PANEL_W, H], fill=GREEN + (255,))

PAD = int(W * 0.028)
inner_w = PANEL_W - PAD * 2


def fit_font(path, text, target_w, start=260):
    """Автоподбор кегля под ширину панели — заголовок всегда влезает."""
    s = start
    while s > 8:
        f = ImageFont.truetype(path, s)
        if draw.textlength(text, font=f) <= target_w:
            return f
        s -= 2
    return ImageFont.truetype(path, 8)


def spaced(t, n=2):
    return (" " * n).join(list(t))


# тег темы (вразрядку) + линия под ним
tag = spaced(TAG, 2)
ftag = fit_font(FB, tag, inner_w, start=60)
y = int(H * 0.10)
draw.text((PAD, y), tag, font=ftag, fill=WHITE)
tb = draw.textbbox((PAD, y), tag, font=ftag)
draw.rectangle([PAD, tb[3] + 10, PAD + inner_w, tb[3] + 13], fill=WHITE + (255,))

# заголовок стопкой: единый кегль по самому широкому слову
biggest = max(HEADLINE, key=len)
fh = fit_font(FN, biggest, inner_w, start=260)
line_h = int(fh.size * 0.94)
y = int(H * 0.30)
for word in HEADLINE:
    draw.text((PAD, y), word, font=fh, fill=(RED if word == RED_WORD else WHITE))
    y += line_h

img.save(OUT_PATH)
print("saved:", OUT_PATH, img.size)
