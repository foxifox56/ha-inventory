# ZXing browser bundle

`zxing-browser.mjs` is a locally bundled, minified browser ES module generated from:

- `@zxing/browser` 0.2.1 (MIT)
- `@zxing/library` 0.23.0 (Apache-2.0)
- `@zxing/text-encoding` 0.9.0 (Unlicense OR Apache-2.0)
- `ts-custom-error` 3.3.1 (MIT)

The bundle was produced with esbuild 0.27.2 targeting ES2020. The app does not fetch these packages from a CDN at runtime. Keep the matching license files in this directory when updating the bundle. The source entry point exports only `BrowserMultiFormatReader` from `@zxing/browser`.

Build outline (from an npm project with the pinned packages installed):

```sh
printf "export { BrowserMultiFormatReader } from '@zxing/browser';\\n" > entry.mjs
npx esbuild entry.mjs --bundle --format=esm --platform=browser --target=es2020 --minify --legal-comments=none --outfile=zxing-browser.mjs
```
