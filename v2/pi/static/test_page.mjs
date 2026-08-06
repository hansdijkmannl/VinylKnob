// Does the page hold together, without a browser.
//
//     node test_page.mjs
//
// Not a rendering test — it cannot see. What it can see is the class of
// mistake that has actually bitten here: a handler wired to an element id that
// no longer exists, a class the code sets and the stylesheet does not select,
// a template that references a helper defined nowhere. Each of those shipped
// once and looked fine until something quietly stopped working.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import vm from "node:vm";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const html = readFileSync(path.join(HERE, "index.html"), "utf8");

const script = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)]
  .map((m) => m[1]).join("\n");
const style = [...html.matchAll(/<style>([\s\S]*?)<\/style>/g)]
  .map((m) => m[1]).join("\n");

const fails = [];
const check = (ok, what) => { if (!ok) fails.push(what); };

// -- does it parse ----------------------------------------------------------
try {
  new vm.Script(script, { filename: "index.html" });
} catch (e) {
  fails.push(`the script does not parse: ${e.message}`);
}

// -- every $('id') and setText('id') names an element ------------------------
const ids = new Set([...html.matchAll(/\bid="([^"]+)"/g)].map((m) => m[1]));
// Ones built at runtime: `id="play-${p.id}"` and the like.
const madeLater = /\$\{|`/;
for (const m of script.matchAll(/\b(?:\$|setText|on)\(\s*'([^']+)'/g)) {
  if (madeLater.test(m[1])) continue;
  check(ids.has(m[1]), `no element with id "${m[1]}", but the script looks it up`);
}

// -- every class the script sets is one the stylesheet knows -----------------
// The letter highlight broke exactly here: the code set one name and the CSS
// selected another, and nothing anywhere said so.
const styled = new Set([...style.matchAll(/\.([A-Za-z][\w-]*)/g)].map((m) => m[1]));
const inMarkup = new Set([...html.matchAll(/\bclass="([^"$]*)"/g)]
  .flatMap((m) => m[1].split(/\s+/)).filter(Boolean));
for (const m of script.matchAll(/\bclassList\.(?:add|toggle|remove)\('([^']+)'\)/g)) {
  check(styled.has(m[1]) || inMarkup.has(m[1]),
        `class "${m[1]}" is set by the script but styled nowhere`);
}

// -- every data-* the click handlers read is one the markup writes -----------
// One handler serves the whole queue, so a renamed attribute goes silently
// dead rather than throwing. Only inside a handler that aliased the dataset:
// `d` is a perfectly ordinary name for a lump of fetched JSON elsewhere.
const written = new Set([...script.matchAll(/\bdata-([a-z]+)=/g)].map((m) => m[1]));
for (const m of script.matchAll(/const (\w+) = e\.target\.dataset[\s\S]*?\n\}\);/g)) {
  const alias = m[1];
  for (const use of m[0].matchAll(new RegExp(`\\b${alias}\\.([a-z]+)\\b`, "g"))) {
    check(written.has(use[1]),
          `a handler reads ${alias}.${use[1]}, but no markup writes data-${use[1]}`);
  }
}

// -- the functions the templates call actually exist -------------------------
const defined = new Set([
  ...[...script.matchAll(/\bfunction\s+([A-Za-z_]\w*)/g)].map((m) => m[1]),
  // const f = (a) => …, const f = a => …, const f = async (…) => …
  ...[...script.matchAll(/\b(?:const|let)\s+([A-Za-z_]\w*)\s*=\s*(?:async\s+)?(?:\(|\w+\s*=>)/g)]
     .map((m) => m[1]),
]);
for (const name of ["queueRow", "knownRow", "hitList", "showHits", "esc"]) {
  check(defined.has(name), `${name}() is used but not defined`);
}

// -- the queue asks for both kinds of question -------------------------------
// The whole point of the chooser: a track on several of your records is not
// "recognised and done", it is waiting for you, and it waits in the queue.
check(/api\/plays\?status=unknown,choose/.test(script),
      "the queue only asks for unknown plays, so choices never appear in it");
check(/p\.status === 'choose'/.test(script),
      "nothing in the queue treats a 'choose' row differently");
check(/status !== 'choose'/.test(script),
      "'choose' rows would also show up under recognised, as though settled");

// -- and what a queue row actually comes out as ------------------------------
// The two functions run for real, on the shape the brain sends. Everything
// above is about names lining up; this is about the row being a question you
// can answer with one press.
function slice(name) {
  const at = script.indexOf(`function ${name}(`);
  if (at < 0) return "";
  let depth = 0, i = script.indexOf("{", at);
  for (let j = i; j < script.length; j++) {
    if (script[j] === "{") depth++;
    else if (script[j] === "}" && --depth === 0) return script.slice(at, j + 1);
  }
  return "";
}

const box = vm.createContext({ chosen: new Set() });
vm.runInContext(
  "const esc = s => String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;');\n" +
  slice("hitList") + "\n" + slice("queueRow"), box);

const CHOOSE = {
  id: 285, at: "2026-08-06 19:19", status: "choose", engine: "shazamio",
  artist: "Robbie Williams", title: "Let Me Entertain You", album: "Greatest Hits",
  clip: null, choices: [
    { id: 426, artist: "Robbie Williams", title: "Greatest Hits", year: "2004", cover: "/api/cover/426" },
    { id: 429, artist: "Robbie Williams", title: "Life Thru A Lens", year: "2021", cover: "/api/cover/429" },
    { id: 441, artist: "Robbie Williams", title: "XXV", year: "2022", cover: "/api/cover/441" },
  ],
};
const UNKNOWN = { id: 9, at: "2026-08-06 20:00", status: "unknown", artist: "", title: "", clip: "/api/clip/x.wav" };

const asked = box.queueRow(CHOOSE);
check(asked.includes("Let Me Entertain You"),
      "a choice row does not name the track that was recognised");
check(asked.includes("on 3 of your records"),
      "a choice row does not say how many records it could be");
for (const id of [426, 429, 441]) {
  check(asked.includes(`data-link="285:${id}"`),
        `no one-press Link button for release ${id}`);
}
check(!asked.includes("Unknown record"),
      "a recognised track is labelled as an unknown record");

const plain = box.queueRow(UNKNOWN);
check(plain.includes("Unknown record"), "an unrecognised row lost its heading");
check(!/data-link=/.test(plain),
      "an unrecognised row offers links to nothing in particular");
check(plain.includes('data-search="9"'), "an unrecognised row lost its search box");
check(asked.includes('data-search="285"'),
      "a choice row cannot be searched past when none of the three is right");

for (const f of fails) console.log(`  FAIL ${f}`);
console.log(fails.length ? `\n${fails.length} problem(s)` : "  ok   the page holds together");
process.exit(fails.length ? 1 : 0);
