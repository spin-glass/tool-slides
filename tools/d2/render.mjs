// D2 → SVG。parts.flow から呼ぶ: node render.mjs <in.d2> <out.svg> <regular.ttf> <bold.ttf> [layout]
// フォントは parts.flow が図の文字だけに絞った静的フォント（400/700）を渡す（D2 は文字幅をこのフォントで測る）
import { D2 } from "@terrastruct/d2";
import { readFileSync, writeFileSync } from "node:fs";
const [, , input, output, regular, bold, layout = "elk"] = process.argv;
const d2 = new D2();
const r = Array.from(readFileSync(regular)), b = Array.from(readFileSync(bold));   // Uint8Array は worker へ渡すと壊れる（実測）
const res = await d2.compile(readFileSync(input, "utf8"), {
  layout, pad: 8, center: false, fontRegular: r, fontBold: b, fontSemibold: b, fontItalic: r,
});
writeFileSync(output, await d2.render(res.diagram, res.renderOptions));
process.exit(0);
