// 给已生成Markmap留出控件区，只改派生排版，不改节点、关系或中央输出。
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const input=process.argv[2];
if(!input||!fs.existsSync(input))throw new Error('传入Markmap MCP实际返回的HTML绝对路径。');
const source=fs.readFileSync(input,'utf8');
if(!source.includes('window.mm')||!source.includes('svg#mindmap'))throw new Error('输入不是已生成的Markmap HTML');
const output=source.replace('<html>','<html lang="zh-CN">').replace('<title>Markmap</title>','<title>MedAxis 医枢 · 产品思维导图</title>').replace('</head>','<style id="medaxis-reading-layout">#mindmap{height:calc(100vh - 88px)}body{background:#fff;font-family:"Microsoft YaHei",sans-serif}</style></head>');
fs.writeFileSync(path.join(root,'visuals/product-mindmap.html'),output,'utf8');
console.log(JSON.stringify({source:input,output:'visuals/product-mindmap.html',layout:'reserved-toolbar-space',semanticChanges:0}));
