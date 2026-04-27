# Foods Import Guide

## 1) Fill source list

Edit `foods-source.example.js`, then paste your foods into:

- `breakfast`
- `lunch`
- `dinner`
- `nightSnack`

Each item is a plain string, for example:

```js
breakfast: ["花椒叶贝果", "豆浆油条"]
```

## 2) Build JSON

Run:

```bash
node tools/build-foods-json.js
```

Generated file:

- `tools/foods.import.json`

## 3) Import to cloud database

In WeChat DevTools cloud console:

1. Open cloud database
2. Create collection `foods`
3. Click import
4. Choose `tools/foods.import.json`
5. Import mode: insert

The cloud function `getRandomFood` reads from this collection.
