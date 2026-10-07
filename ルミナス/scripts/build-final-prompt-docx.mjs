// prompts/ルミナス_最終プロンプト.md → ☆ルミナス_最終プロンプト.docx
// 対応する Markdown: 見出し(#/##/###)、箇条書き(-)、番号付き(1.)、引用(>)、区切り(---)、段落、**太字**、`コード`
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");
const SRC = path.join(root, "prompts", "ルミナス_最終プロンプト.md");
const OUT = path.join(root, "☆ルミナス_最終プロンプト.docx");

let docx;
try {
  docx = createRequire(import.meta.url)("docx");
} catch {
  console.error("docx パッケージが見つかりません。フォルダ直下で `npm install` を一度実行してください。");
  process.exit(1);
}
const { Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType, LevelFormat, BorderStyle } = docx;

const md = fs.readFileSync(SRC, "utf8").split(/\r?\n/);
const FONT = "Hiragino Mincho ProN";

function runs(text) {
  // **太字** と `コード` だけを解釈する
  const out = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(new TextRun({ text: text.slice(last, m.index), font: FONT }));
    const tok = m[0];
    if (tok.startsWith("**")) out.push(new TextRun({ text: tok.slice(2, -2), bold: true, font: FONT }));
    else out.push(new TextRun({ text: tok.slice(1, -1), font: "Menlo", size: 20 }));
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(new TextRun({ text: text.slice(last), font: FONT }));
  return out;
}

const children = [];
let para = [];
let numBlock = 0;          // 番号付きリストのかたまり番号
let inNumBlock = false;    // 直前の行が番号付き項目だったか
const flushPara = () => {
  if (para.length) {
    children.push(new Paragraph({ children: runs(para.join("")), spacing: { after: 120 } }));
    para = [];
  }
};

for (const raw of md) {
  const line = raw.replace(/\s+$/, "");
  if (!line.trim()) { flushPara(); inNumBlock = false; continue; }
  let m;
  const isNum = /^\d+\.\s+/.test(line);
  if (isNum && !inNumBlock) numBlock += 1;
  inNumBlock = isNum;
  if ((m = line.match(/^(#{1,3})\s+(.*)$/))) {
    flushPara();
    const lvl = m[1].length;
    const heading = lvl === 1 ? HeadingLevel.TITLE : lvl === 2 ? HeadingLevel.HEADING_1 : HeadingLevel.HEADING_2;
    children.push(new Paragraph({ heading, children: runs(m[2]), spacing: { before: lvl === 1 ? 0 : 240, after: 120 } }));
  } else if (line === "---") {
    flushPara();
    children.push(new Paragraph({ border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: "999999", space: 1 } }, spacing: { after: 120 } }));
  } else if ((m = line.match(/^>\s?(.*)$/))) {
    flushPara();
    children.push(new Paragraph({ children: runs(m[1]).map(r => r), indent: { left: 567 }, spacing: { after: 60 },
      border: { left: { style: BorderStyle.SINGLE, size: 12, color: "888888", space: 8 } } }));
  } else if ((m = line.match(/^-\s+(.*)$/))) {
    flushPara();
    children.push(new Paragraph({ children: runs(m[1]), numbering: { reference: "bullets", level: 0 }, spacing: { after: 60 } }));
  } else if ((m = line.match(/^\d+\.\s+(.*)$/))) {
    flushPara();
    children.push(new Paragraph({ children: runs(m[1]), numbering: { reference: `numbers-${numBlock}`, level: 0 }, spacing: { after: 60 } }));
  } else {
    para.push(line);
  }
}
flushPara();

const doc = new Document({
  creator: "ルミナス（Luminous）",
  title: "☆ルミナス 最終プロンプト",
  styles: {
    default: { document: { run: { font: FONT, size: 21 } } },
    paragraphStyles: [
      { id: "Title", name: "Title", basedOn: "Normal", next: "Normal", run: { size: 36, bold: true, font: FONT }, paragraph: { alignment: AlignmentType.LEFT, spacing: { after: 200 } } },
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 28, bold: true, font: FONT, color: "1c3626" } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 24, bold: true, font: FONT } },
    ],
  },
  numbering: {
    config: [
      { reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 567, hanging: 283 } } } }] },
      ...Array.from({ length: numBlock }, (_, i) => ({
        reference: `numbers-${i + 1}`,
        levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 567, hanging: 283 } } } }],
      })),
    ],
  },
  sections: [{ properties: { page: { margin: { top: 1134, bottom: 1134, left: 1134, right: 1134 } } }, children }],
});

const buf = await Packer.toBuffer(doc);
fs.writeFileSync(OUT, buf);
console.log(`generated: ${path.relative(root, OUT)} (${buf.length} bytes) from ${path.relative(root, SRC)}`);
