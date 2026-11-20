import fs from "node:fs/promises";
import path from "node:path";
import {fileURLToPath} from "node:url";
import {createRequire} from "node:module";
import {build, transform} from "esbuild";
import postcss from "postcss";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(import.meta.url);
const output = path.join(root, "app/frontend/vendor/astryx");
await fs.mkdir(output, {recursive: true});

// Astryx's native CSS is page-oriented. Flatten its theme scopes into ordinary
// ancestor selectors for isolated React islands and older embedded browsers.
// Tokens live on island roots; no reset or typography escapes into the host app.
function scopedCSS(css, filename) {
  const sheet = postcss.parse(css, {from: filename});
  sheet.walkRules(rule => {
    let parent = rule.parent;
    let themeScope = "";
    let isKeyframe = false;
    while (parent) {
      if (parent.type === "atrule" && /keyframes$/i.test(parent.name)) isKeyframe = true;
      if (parent.type === "atrule" && parent.name === "scope") {
        const match = parent.params.match(/^\(([^)]+)\)/);
        if (!match) throw new Error(`Unsupported Astryx scope: ${parent.params}`);
        themeScope = match[1];
      }
      parent = parent.parent;
    }
    if (isKeyframe) return;
    const selectors = rule.selectors.filter(selector => !/^html(?:\[|\s|$)/.test(selector));
    if (!selectors.length) { rule.remove(); return; }
    rule.selectors = selectors.map(selector => {
      if (selector === ":root") return "[data-listok-astryx]";
      const local = themeScope
        ? (selector.includes(":scope") ? selector.replaceAll(":scope", themeScope) : `${themeScope} ${selector}`)
        : selector;
      return `[data-listok-astryx] ${local}`;
    });
  });
  sheet.walkAtRules(at => {
    // Preserve Astryx's base/theme layer order: its atomic classes deliberately
    // carry high specificity and theme or app overrides belong above that layer.
    if (at.name === "scope") {
      if (at.nodes) at.replaceWith(...at.nodes);
      else at.remove();
    }
  });
  return sheet.toString();
}

const sources = ["@astryxdesign/core/astryx.css", "@astryxdesign/theme-neutral/theme.css"];
const css = await Promise.all(sources.map(async name => {
  const filename = require.resolve(name);
  return scopedCSS(await fs.readFile(filename, "utf8"), filename);
}));
css.push(await fs.readFile(path.join(root, "ui/listok-ui.css"), "utf8"));
const compiledCSS = await transform(css.join("\n"), {loader: "css", minify: true, target: "es2020", legalComments: "none"});
await fs.writeFile(path.join(output, "listok-ui.css"), compiledCSS.code);
const result = await build({
  absWorkingDir: root,
  entryPoints: ["ui/listok-ui.jsx"],
  outfile: path.join(output, "listok-ui.js"),
  bundle: true,
  minify: true,
  format: "iife",
  platform: "browser",
  target: ["es2020"],
  jsx: "automatic",
  define: {"process.env.NODE_ENV": '"production"'},
  legalComments: "external",
  metafile: true,
});
const packageJSON = JSON.parse(await fs.readFile(path.join(root, "package.json"), "utf8"));
const dependencies = Object.fromEntries(Object.entries(packageJSON.devDependencies).filter(([name]) => /astryx|react|stylex/.test(name)));
const manifest = {description: "Locally bundled Astryx React islands for the ListOK formula editor and variant picker", build: "npm ci --ignore-scripts && npm run build:ui", source: "https://github.com/meta/astryx", dependencies, files: ["listok-ui.js", "listok-ui.css"]};
await fs.writeFile(path.join(output, "manifest.json"), JSON.stringify(manifest, null, 2) + "\n");
const notices = ["ListOK UI: real Astryx components, locally bundled. No runtime CDN dependencies.", "Astryx and StyleX / Meta Platforms, Inc. and affiliates — MIT", await fs.readFile(path.join(root, "node_modules/@astryxdesign/theme-neutral/LICENSE"), "utf8"), "React / Meta Platforms, Inc. and affiliates — MIT", await fs.readFile(path.join(root, "node_modules/react/LICENSE"), "utf8"), "Additional bundled copyright notices: listok-ui.js.LEGAL.txt"];
await fs.writeFile(path.join(output, "NOTICE.txt"), notices.join("\n\n"));
for (const filename of ["listok-ui.js", "listok-ui.css"]) {
  const stat = await fs.stat(path.join(output, filename));
  console.log(`${filename}: ${(stat.size / 1024).toFixed(1)} KiB`);
}
console.log(`Built from ${Object.keys(result.metafile.inputs).length} modules, including Astryx ${dependencies["@astryxdesign/core"]}.`);
