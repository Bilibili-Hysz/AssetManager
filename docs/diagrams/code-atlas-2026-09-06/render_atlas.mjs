import { createRequire } from 'node:module';
import { readFile, writeFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const output = dirname(fileURLToPath(import.meta.url));
const root = resolve(output, '../../..');
const require = createRequire(join(root, 'webui/package.json'));
const { chromium } = require('@playwright/test');
const inventory = JSON.parse(await readFile(join(output, 'source-inventory.json'), 'utf8'));
const escape = value => value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
// Keep identifiers intact while wrapping display labels at natural separators.
const wrapLabels = source => source.replace(/\["([^"]+)"\]|\(\("([^"]+)"\)\)/g, (match, rect, cylinder) => {
  const label = rect ?? cylinder;
  const chunks = label.split(/(?<=\s|\/|\+)/u);
  const lines = [];
  let line = '';
  const width = text => [...text].reduce((sum, char) => sum + (char.codePointAt(0) > 255 ? 2 : 1), 0);
  for (const chunk of chunks) {
    if (line && width(line + chunk) > 33) {
      lines.push(line.trim());
      line = '';
    }
    line += chunk;
  }
  if (line.trim()) lines.push(line.trim());
  return rect !== undefined ? `["${lines.join('<br/>')}"]` : `(("${lines.join('<br/>')}"))`;
});
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
  await page.setContent('<!doctype html><html><head><meta charset="utf-8"></head><body></body></html>');
  await page.addScriptTag({ url: 'https://cdn.jsdelivr.net/npm/mermaid@10.9.3/dist/mermaid.min.js' });
  await page.evaluate(() => mermaid.initialize({
    startOnLoad: false, securityLevel: 'strict', theme: 'base',
    themeVariables: {
      fontFamily: 'Microsoft YaHei, Arial, sans-serif', fontSize: '16px',
      primaryColor: '#e8f2ee', primaryTextColor: '#202722', primaryBorderColor: '#628775',
      secondaryColor: '#eef2f8', tertiaryColor: '#faf4ec', lineColor: '#62716d',
      clusterBkg: '#f7f9f8', clusterBorder: '#bccbc3', edgeLabelBackground: '#ffffff',
    },
    flowchart: { useMaxWidth: false, htmlLabels: false, curve: 'linear', nodeSpacing: 30, rankSpacing: 48 },
    sequence: { useMaxWidth: false, wrap: true, actorMargin: 45, messageMargin: 40 },
  }));
  const sections = [];
  const dimensions = [];
  for (const diagram of inventory.diagrams) {
    const source = wrapLabels(await readFile(join(output, diagram.file), 'utf8'));
    const svg = await page.evaluate(async ({ source, id }) => {
      await mermaid.parse(source);
      return (await mermaid.render(`atlas${id}`, source)).svg;
    }, { source, id: diagram.id });
    await writeFile(join(output, `${diagram.id}.svg`), svg, 'utf8');
    const viewBox = svg.match(/viewBox="([^"]+)"/)?.[1];
    dimensions.push({ id: diagram.id, bytes: Buffer.byteLength(svg), viewBox });
    const minimumWidth = Math.ceil(Number(viewBox.split(' ')[2]) * 0.8);
    sections.push(`<section id="diagram-${diagram.id}"><h2>${diagram.id} ${escape(diagram.title)}</h2><p class="links"><a href="${diagram.id}.svg" target="_blank">打开原尺寸图</a><a href="${diagram.file}">Mermaid 图源</a></p><div class="diagram" style="--diagram-min:${minimumWidth}px">${svg}</div></section>`);
  }
  const navigation = inventory.diagrams.map(d => `<a href="#diagram-${d.id}">${d.id} ${escape(d.title)}</a>`).join('\n');
  const html = `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>AssetManager 当前代码架构图册</title>
<style>
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#fff;color:#202722;font:15px/1.7 "Microsoft YaHei",Arial,sans-serif;letter-spacing:0}header,main,nav{max-width:1440px;margin:auto;padding:24px 32px}header{border-bottom:1px solid #d9e3dd}h1{font-size:28px;margin:0 0 8px}h2{font-size:21px;margin:0 0 8px}p{margin:8px 0}a{color:#236b55;text-underline-offset:3px}nav{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px 20px;border-bottom:1px solid #d9e3dd}nav a{overflow-wrap:anywhere}section{padding:24px 0 40px;border-bottom:1px solid #d9e3dd;scroll-margin-top:16px}.links{display:flex;gap:24px;font-size:14px}.diagram{overflow:auto;max-width:100%;padding:12px 0}.diagram svg{display:block;max-width:100%;min-width:var(--diagram-min);height:auto;margin:auto}footer{padding:24px 32px;color:#526258;font-size:13px}code{overflow-wrap:anywhere} @media(max-width:720px){header,main,nav{padding:18px 16px}h1{font-size:23px}nav{grid-template-columns:repeat(2,minmax(0,1fr))}} @media print{nav,.links{display:none}section{break-inside:avoid}header,main{padding:8px}.diagram{overflow:visible}.diagram svg{max-width:100%;min-width:0}}
</style></head><body><header><h1>AssetManager 当前代码架构图册</h1><p>2026-09-06 · ${inventory.diagrams.length} 张分图 · 桌面、LAN 与 WebUI</p><p><a href="../../architecture-code-atlas-2026-09-06.md">架构说明与开发定位表</a> · <a href="README.md">源码与路由索引</a></p><p>代码基准：<code>${escape(inventory.head)}</code> + 捕获时的未提交工作区</p></header><nav aria-label="架构分图">${navigation}</nav><main>${sections.join('\n')}</main><footer>分图表达调用、数据流与所有权。虚线含义以正文说明为准；详细边界、未接通能力和源码入口见配套说明。</footer></body></html>`;
  await writeFile(join(output, 'index.html'), html, 'utf8');
  await page.goto(pathToFileURL(join(output, '01.svg')).href);
  const overviewBox = dimensions[0].viewBox.split(' ').map(Number);
  await page.setViewportSize({ width: Math.ceil(overviewBox[2]), height: Math.ceil(overviewBox[3]) });
  await page.locator('svg').screenshot({ path: join(output, 'overview.png') });
  await page.goto(pathToFileURL(join(output, 'index.html')).href);
  const checks = [];
  for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    const result = await page.evaluate(() => ({
      width: innerWidth, documentWidth: document.documentElement.scrollWidth,
      rendered: document.querySelectorAll('section .diagram > svg').length,
      blank: [...document.querySelectorAll('section .diagram > svg')].filter(svg => !svg.querySelector('text')).length,
      externalResources: performance.getEntriesByType('resource').filter(r => /^https?:/.test(r.name)).length,
    }));
    if (result.documentWidth > result.width || result.rendered !== 14 || result.blank || result.externalResources) {
      throw new Error(`Invalid offline atlas layout: ${JSON.stringify(result)}`);
    }
    checks.push(result);
  }
  await page.screenshot({ path: join(output, 'mobile-preview.png') });
  await writeFile(join(output, 'render-check.json'), JSON.stringify({ mermaid: '10.9.3', diagrams: dimensions, viewportChecks: checks }, null, 2) + '\n', 'utf8');
  console.log(JSON.stringify({ rendered: sections.length, output: join(output, 'index.html'), dimensions }));
} finally {
  await browser.close();
}
