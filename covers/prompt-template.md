# Обложка «Editorial-панель» — рабочий рецепт

Формат обложки, на котором я остановился. Одна готовая картинка на статью,
рисуется целиком нейросетью (текст включительно).

Пришёл к нему после комплекта из четырёх разных промптов на статью: возни много,
а выбирать из четырёх посредственных вариантов хуже, чем сделать один хороший.

---

## Чем рисуем

```
модель: google/gemini-3-pro-image
output_path: <временная папка>/cover-<slug>.png
```

Цена одной генерации ~$0.14. Рисуем **во временную папку**, глазами проверяем, и
только исправную копируем к статье. Отбраковку не копим.

⚠️ **Проверка глазами обязательна.** После генерации открой PNG и вычитай каждое
русское слово по буквам. Кириллица — единственное место, где модель регулярно
врёт, и заметить это можно только посмотрев.

---

## Анатомия кадра

| Зона | Доля | Что внутри |
|---|:-:|---|
| Панель слева | 42% ширины, во всю высоту | бейдж-рубрика + заголовок в 3 строки |
| Сцена справа | 58% ширины, **в полный вылет** | герой + предметная метафора + насыщенный фон |

Пять вещей, без которых обложка выглядит пустой (все пять проверены на провальных
вариантах):

1. **Человек в кадре.** Даже когда статья про отсутствие человека — прячем лицо,
   а не убираем героя. Запрет `no people` в промпте даёт натюрморт и мёртвый кадр.
2. **Сцена в полный вылет.** Явно писать `FULL BLEED, edge to edge, no empty
   margin`. Иначе модель оставит предмет на столе и воздух вокруг.
3. **Насыщенный задний план.** Перечислить предметно: полка с книгами, растение,
   картина на стене, свет из окна, мягкая расфокусировка. Не заказал среду —
   получил пустоту.
4. **Заголовок в 3 строки на ~65% высоты панели.** Две строки мелким кеглем
   не держат плакатную плотность.
5. **Тугой красный круг вокруг мелкой детали**, а не вокруг крупного объекта.
   Деталь должна нести смысл статьи.

---

## Кириллица: как не получить мусор

Главный риск формата. Что наблюдал:

- **Чем больше отдельных русских строк, тем выше шанс распада.** Держим четыре
  строки максимум: бейдж + три строки заголовка.
- **Дефис внутри слова провоцирует распад сильнее всего.** «ИИ-АВАТАР» вышло как
  «РФИ-РЂАВУТРАЙ». Убрали дефис — слово встало с первого раза.
- **Буква И получает краткую** и превращается в Й («ПОЛОВИНА» → «ПОЛОВЙНА»).
- **Модель вставляет и подменяет буквы** в середине длинного слова
  («НАПРОКАТ» → «НАПИРОКУТ»).
- **Последняя буква удваивается** («ПАМЯТЬ» → «ПАМЯТЬЬ»).

Три приёма, которые это лечат (применять все сразу):

1. Общая шапка перед блоками текста:
   > ALL LETTERING IS RUSSIAN CYRILLIC AND MUST BE SPELLED CHARACTER BY CHARACTER
   > EXACTLY AS LISTED. Render only the listed characters, in the listed order, with
   > nothing inserted, nothing omitted and nothing substituted. Before finishing,
   > verify each word letter by letter against the list.
2. Каждое слово задавать побуквенно с указанием позиций:
   > Line 2 is exactly eight characters followed by a full stop: Н, А, П, Р, О, К,
   > А, Т, then a period. The second character is А, the third is П, the fourth is Р...
3. Негативное указание по буквам, которые модель любит подставлять:
   > Line 2 contains no И and no У.
   > Every Cyrillic И must be a bare plain И with a completely flat clean top and
   > NO breve, NO curved mark, NO accent, NO diacritic of any kind above it.
   > It must NOT be the letter Й.

Не помогло за две попытки — накладываем текст сами через Pillow
([`stopper_overlay.py`](stopper_overlay.py) в этой же папке), арт при этом просим
без текста.

---

## Ротация, чтобы выпуски не сливались

Перед сборкой промпта посмотри обложки двух прошлых выпусков и не повторяй:

- **Цвет панели.** Использованы: forest green, petrol blue, dark plum, dark teal,
  deep indigo.
- **Героя** — веди свой список типажей (возраст, пол, образ) и не повторяй два
  выпуска подряд.
- **Предметную метафору** и то, что обводит красный круг.

Постоянные величины серии, их не трогаем: панель слева, бейдж сверху, заголовок
в три строки, последняя строка коралловая, ровно один красный круг, карандашно-
штриховой editorial-стиль на тёплой бумаге.

---

## Шаблон промпта

Подставить `{{...}}`, остальное оставить дословно. Em-dash в EN-промпте допустим.

```
Create ONE finished landscape 16:9 magazine-style cover illustration for a
Russian-language article about {{ТЕМА ОДНОЙ ФРАЗОЙ}}. Core idea: {{СТАВКА СТАТЬИ}}.

ART DIRECTION
A rich hand-drawn editorial illustration: colored pencil and graphite with dense
expressive crosshatching, warm ivory paper tooth visible in every stroke, restrained
watercolor washes, soft natural daylight. Looks like a beautifully illustrated
magazine cover fused with bold modern poster typography. Warm, human, tactile,
detailed. NOT minimal, NOT sparse.

LAYOUT
Left side: a solid {{ЦВЕТ ПАНЕЛИ}} color panel occupying 42% of the image width,
full height, top to bottom, with a slightly hand-drawn irregular right boundary.
Right side: the illustrated scene occupies the remaining 58% and MUST be FULL BLEED.
It runs edge to edge and top to bottom with no empty margin and no white gap. The
scene fills its entire area with content.
Do not draw any border or outer frame line around the image.
One single finished cover, not a collage or a sheet of variants.

ALL LETTERING IS RUSSIAN CYRILLIC AND MUST BE SPELLED CHARACTER BY CHARACTER EXACTLY
AS LISTED. Render only the listed characters, in the listed order, with nothing
inserted, nothing omitted and nothing substituted. Before finishing, verify each word
letter by letter against the list.

RUBRIC BADGE
At the top of the panel, a small rounded rectangle badge in a slightly lighter
desaturated shade of the panel color, containing short bold uppercase Russian
lettering in warm white. The badge word is exactly {{N}} characters, no hyphen, no
punctuation: {{Б, У, К, В, Ы}}. The badge is small and modest, about one tenth of
the panel height.

HEADLINE
Below the badge, enormous bold condensed heavy sans-serif Russian lettering stacked
in THREE tight lines with very small line spacing. The headline block is visually
dominant and fills roughly 65% of the panel height, each line stretching nearly the
full usable width of the panel.
Line 1 is exactly {{N}} characters: {{Б, У, К, В, Ы}}
Line 2 is exactly {{N}} characters followed by a full stop: {{Б, У, К, В, Ы}}, then
a period. The second character is {{X}}, the third is {{X}}, the fourth is {{X}}...
Line 2 contains no {{ОПАСНАЯ БУКВА}}.
Line 3 is {{...}} and a question mark.
Lines 1 and 2 in warm white. Line 3 entirely in saturated coral red.
CRITICAL: every Cyrillic И in this image must be a bare plain И with a completely
flat clean top and NO breve, NO curved mark, NO accent, NO diacritic of any kind
above it. It must NOT be the letter Й. No diacritical marks, accents or dots appear
above any letter anywhere.
Never crop letters, never split a word across lines, never hyphenate, never
letter-space a word apart. No other text on the panel.

VISUAL STORY
{{ГЕРОЙ: возраст, причёска, очки, одежда, поза, что делает руками}}
{{ПРЕДМЕТНАЯ МЕТАФОРА: главный объект и почему он читается именно так}}
BACKGROUND, important for richness: a warm lived-in {{ПОМЕЩЕНИЕ}} behind him,
filling the entire background with depth and detail but softly rendered and slightly
out of focus: {{3-4 ПРЕДМЕТА}}, a soft window glow on the left of the scene.

CURIOSITY DETAIL
Exactly ONE hand-drawn coral-red circle, drawn loosely and quickly by hand, TIGHT and
SMALL, closely enclosing only {{МЕЛКАЯ ДЕТАЛЬ}}. The circle is complete all the way
around and stays fully inside the frame. No arrow, no underline, no second circle.

COLOR
{{ЦВЕТ ПАНЕЛИ}} panel. The scene in warm ivory, {{2-3 ЦВЕТА СЦЕНЫ}} and muted natural
pencil tones with gentle daylight shadows. Vivid coral red appears ONLY in the third
headline line and the single small hand-drawn circle.

TEXT INSIDE THE SCENE
No labels, no numbers, no captions, no interface text, no book titles anywhere in the
illustrated scene. Only the panel carries words.

QUALITY CONSTRAINTS
No watermarks, no logos, no robots, no glowing brains, no holograms, no neon, no
cyberpunk, no server rooms, no glossy 3D render, no flat corporate vector stock
illustration, no exaggerated cartoon reaction face.
No malformed hands, no extra fingers, no duplicate objects, no illegible or garbled
lettering, no empty dead space.
```

---

Разборы и вопросы — в канале: https://t.me/ai_styledanila
