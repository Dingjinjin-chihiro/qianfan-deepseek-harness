// asar 读取工具（纯 Node，无依赖）—— 用于在 Electron 应用里定位内置插件源码
//
// 用法：
//   node tools/read-asar.mjs list   <app.asar> [关键字]
//   node tools/read-asar.mjs cat    <app.asar> <asar 内路径>
//   node tools/read-asar.mjs extract<app.asar> <目录前缀> <输出目录>
//
// 例：
//   node tools/read-asar.mjs list "C:\...\app.asar" dsh-llm-deepseek
//   node tools/read-asar.mjs cat  "C:\...\app.asar" /dsh/node_modules/@deepseek-ai/dsh-llm-deepseek/lib/index.js
//
// asar 结构：16 字节头 + JSON 清单 + 文件区
//   0..4   uint32 = 4
//   4..8   uint32 = 文件区起始偏移 - 8
//   8..12  uint32 = 清单区长度（含对齐填充）
//   12..16 uint32 = 清单 JSON 字符串长度
//   16..   清单 JSON
// 文件区起点 = readUInt32LE(4) + 8；每个文件的 offset 相对文件区起点。
// 注意：本仓库实测 offset 被序列化成字符串，必须 Number() 转换。

import fs from 'node:fs';
import path from 'node:path';

const [, , cmd, asarPath, a3, a4] = process.argv;

if (!cmd || !asarPath) {
  console.error('用法: node read-asar.mjs <list|cat|extract> <app.asar> [...]');
  process.exit(2);
}

const fd = fs.openSync(asarPath, 'r');
const head = Buffer.alloc(16);
fs.readSync(fd, head, 0, 16, 0);
const filesBase = head.readUInt32LE(4) + 8;
const hlen = head.readUInt32LE(12);
const hbuf = Buffer.alloc(hlen);
fs.readSync(fd, hbuf, 0, hlen, 16);
const header = JSON.parse(hbuf.toString('utf8'));

const entries = [];
(function walk(node, prefix) {
  for (const [k, v] of Object.entries(node.files || {})) {
    const p = prefix + '/' + k;
    if (v.files) walk(v, p);
    else entries.push({ p, off: Number(v.offset), size: Number(v.size) });
  }
})(header, '');

function read(entry) {
  const b = Buffer.alloc(entry.size);
  fs.readSync(fd, b, 0, entry.size, filesBase + entry.off);
  return b;
}

if (cmd === 'list') {
  const kw = a3 ? new RegExp(a3, 'i') : null;
  const hits = kw ? entries.filter((e) => kw.test(e.p)) : entries;
  console.log(`共 ${entries.length} 个文件，匹配 ${hits.length} 个`);
  for (const e of hits) console.log(String(e.size).padStart(10), e.p);
} else if (cmd === 'cat') {
  const e = entries.find((x) => x.p === a3);
  if (!e) { console.error('未找到:', a3); process.exit(1); }
  process.stdout.write(read(e));
} else if (cmd === 'extract') {
  const outDir = a4;
  let n = 0;
  for (const e of entries) {
    if (!e.p.startsWith(a3 + '/')) continue;
    const dest = path.join(outDir, e.p.replace(/^\//, ''));
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    fs.writeFileSync(dest, read(e));
    n++;
  }
  console.log('已导出', n, '个文件 →', outDir);
} else {
  console.error('未知子命令:', cmd);
  process.exit(2);
}

fs.closeSync(fd);
