# Локальные компоненты интерфейса

В `listok-ui.jsx` используются **настоящие React-компоненты Astryx**: `Button`,
`TextInput` и `SegmentedControl`. Они дополняют существующее приложение,
не заменяя работу с файлами, авторизацию или серверные запросы.

- `#latexKeyboard` — формулы с полями для числителя, знаменателя, степени,
  корня, индекса, логарифма; предпросмотр существующим локальным KaTeX.
- `#setupVariants` — исходный select остаётся источником значения формы.
  После успешного запуска компонента отображается переключатель 1–4.
- `sourceText` и `insertLatexSnippet` сохраняют прежние имена и события.
  Выделенный фрагмент заменяется; существующие математические delimiters
  не дублируются. При ошибке запуска доступна обычная клавиатура.

## Сборка

Нужен Node.js 22.13 или новее.

```sh
npm ci --ignore-scripts
npm run build:ui
npm run test:ui
```

Версии зафиксированы в `package-lock.json`. Готовые JS/CSS находятся в
`app/frontend/vendor/astryx/` и входят в Docker-образ вместе с приложением.
В контейнере не требуются Node.js, npm и доступ к CDN.

На странице подключаются `listok-ui.css` после основных стилей и
`listok-ui.js` с `defer` после `latex_keyboard.js`. CSS библиотек ограничен
элементами с `data-listok-astryx`; глобальный reset Astryx не подключается.
Провайдер `ThemeContext` локальный, не меняет тему на `<html>`.
Общие шрифты приложения наследуются; внешние Google Fonts не запрашиваются.

API проверено по CLI `@astryxdesign/cli@0.7.16`:

```sh
npx astryx component Button
npx astryx component TextInput
npx astryx component SegmentedControl
```

Исходная библиотека: https://github.com/meta/astryx, лицензия MIT.
Автоматические проверки: композиция LaTeX, выделение и позиция курсора,
вложенные математические delimiters, ограничение длины поля.
Визуально проверять минимум на ширинах 320, 390, 768 и 1440 пикселей.
