// 把 chunk 服务器地址写进安卓壳。纯 Node，无依赖。
//
// 仓库里只提交 templates/ 下的模板，里面是占位地址 https://your-server.example。
// 这个脚本按模板生成 capacitor.config.json、www/index.html、www/error.html，
// 生成物在 apk/.gitignore 里，不进仓库，所以真实地址不会被误提交。
//
// 用法（在 apk/ 目录）：
//   node configure.mjs https://你的地址     用这个地址生成
//   node configure.mjs                      读 server.config.json（{"url": "..."}，不进仓库）
//   node configure.mjs --reset              用占位地址生成（模板原样）
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const PLACEHOLDER = "https://your-server.example";
const FILES = ["capacitor.config.json", "www/index.html", "www/error.html"];
const LOCAL = join(HERE, "server.config.json");

function fail(msg) {
  console.error(`configure: ${msg}`);
  process.exit(1);
}

function pickUrl(arg) {
  if (arg === "--reset") return PLACEHOLDER;
  if (arg) return arg;
  if (!existsSync(LOCAL)) {
    fail(`没有给地址，也没有 server.config.json。\n  用法：node configure.mjs https://你的地址\n  或者新建 ${LOCAL}，内容 {"url": "https://你的地址"}`);
  }
  let conf;
  try {
    conf = JSON.parse(readFileSync(LOCAL, "utf8"));
  } catch (e) {
    fail(`server.config.json 不是合法 JSON：${e.message}`);
  }
  if (!conf || typeof conf.url !== "string" || !conf.url) fail('server.config.json 里要有 "url" 字段');
  return conf.url;
}

function normalize(raw) {
  let u;
  try {
    u = new URL(raw);
  } catch {
    fail(`地址不合法：${raw}`);
  }
  if (u.protocol !== "https:") fail(`地址要用 https://（安卓壳关了明文 HTTP）：${raw}`);
  if ((u.pathname !== "/" && u.pathname !== "") || u.search || u.hash) fail(`只填域名，不要带路径或参数：${raw}`);
  return u.origin;
}

const arg = process.argv[2];
const url = normalize(pickUrl(arg));

for (const rel of FILES) {
  const tpl = join(HERE, "templates", rel);
  if (!existsSync(tpl)) fail(`缺模板 ${tpl}`);
  const text = readFileSync(tpl, "utf8");
  if (!text.includes(PLACEHOLDER)) fail(`模板里没有占位地址 ${PLACEHOLDER}：${tpl}`);
  const out = join(HERE, rel);
  mkdirSync(dirname(out), { recursive: true });
  writeFileSync(out, text.split(PLACEHOLDER).join(url));
}

console.log(`configure: 服务器地址 ${url}，已写入 ${FILES.join("、")}`);
