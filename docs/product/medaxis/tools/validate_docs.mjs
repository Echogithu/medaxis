// 产品文档门禁：真实文件/链接/路由覆盖/图源/机器契约/阅读版真源校验。
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..'),project=path.resolve(root,'../../..');
const errors=[],stats={markdown:0,links:0,sourceLines:0,routes:0,requirements:0,diagrams:0,phases:0,readerDocuments:0};
const check=(ok,message)=>{if(!ok)errors.push(message)};
const read=p=>fs.readFileSync(p,'utf8');
const slug=s=>s.toLowerCase().replace(/<[^>]*>/g,'').replace(/[^\p{L}\p{N}\s_-]/gu,'').trim().replace(/\s+/g,'-');
function walk(dir){return fs.readdirSync(dir,{withFileTypes:true}).flatMap(e=>e.isDirectory()?walk(path.join(dir,e.name)):[path.join(dir,e.name)])}
const markdown=walk(root).filter(p=>p.endsWith('.md'));
for(const file of markdown){
 const raw=fs.readFileSync(file),source=raw.toString('utf8');stats.markdown++;
 check(!(raw[0]===0xef&&raw[1]===0xbb&&raw[2]===0xbf),`${file}: BOM`);
 check(!source.includes('\ufffd'),`${file}: UTF-8替换字符`);
 for(const m of source.matchAll(/!?\[[^\]]*\]\(<?([^\s)>]+)>?\)/g)){
  const href=m[1]; if(/^(https?:|mailto:)/.test(href))continue;stats.links++;
  const [dest,anchor]=href.split('#'),target=dest?path.resolve(path.dirname(file),decodeURIComponent(dest)):file;
  check(fs.existsSync(target),`${path.basename(file)}: 缺失链接 ${href}`);
  if(!fs.existsSync(target)||!anchor)continue;
  if(/^L\d+$/.test(anchor)){const line=Number(anchor.slice(1));check(line>0&&line<=read(target).split('\n').length,`${href}: 行号越界`);stats.sourceLines++}
  else if(target.endsWith('.md')){const ids=[...read(target).matchAll(/^#{1,6}\s+(.+)$/gm)].map(x=>slug(x[1]));check(ids.includes(decodeURIComponent(anchor)),`${path.basename(file)}: 无标题锚点 ${href}`)}
 }
}
const prd=read(path.join(root,'PRD.md')),spec=read(path.join(root,'PRODUCT_SPEC.md')),evidence=read(path.join(root,'EVIDENCE.md'));
const req=[...prd.matchAll(/^\| (MX-\d\d) \|/gm)].map(x=>x[1]),specIds=[...spec.matchAll(/^### (MX-\d\d)$/gm)].map(x=>x[1]);
check(req.length===19&&new Set(req).size===req.length,'需求目录必须19项且唯一');
check(JSON.stringify(req)===JSON.stringify(specIds),'PRD与SPEC需求覆盖不同');stats.requirements=req.length;
const app=read(path.join(project,'frontend/src/App.tsx')),routes=[],parents=[''];
for(const line of app.split('\n')){
 if(line.includes('</Route>'))parents.pop();
 if(/<Route\s/.test(line)){
  const m=line.match(/path="([^"]+)"/),base=parents.at(-1)||'';
  const route=m?(m[1].startsWith('/')||m[1]==='*'?m[1]:base+'/'+m[1]):base;
  if(m)routes.push(route);if(!line.trim().endsWith('/>'))parents.push(route);
 }
}
const routeRows=[...evidence.matchAll(/^\| `([^`]+)` \|/gm)].map(x=>x[1]);
check(JSON.stringify([...routes].sort())===JSON.stringify([...routeRows].sort()),'页面矩阵与App.tsx路由不一致: '+JSON.stringify({routes,routeRows}));stats.routes=routes.length;
const graphs=JSON.parse(read(path.join(root,'visuals/diagram-manifest.json'))),flows=[...read(path.join(root,'USER_FLOWS.md')).matchAll(/```mermaid\n([\s\S]*?)\n```/g)].map(x=>x[1]);
for(const [i,name] of ['patient-flow','report-consent','doctor-consultation'].entries())check(read(path.join(root,'visuals',name+'.mmd')).trim().replaceAll('\r\n','\n')===flows[i].replaceAll('\r\n','\n'),`${name}: 派生图源未同步`);
for(const g of graphs){
 const source=read(path.join(root,'visuals',g.name+'.mmd'));
 const nodeIds=new Set([...source.matchAll(/(\w+)[\[{]"[^"]+"[\]}]/g)].map(x=>x[1]));
 check(nodeIds.size===g.nodes,`${g.name}: 节点数不匹配`);
 const edges=source.split('\n').filter(s=>s.includes('-->')).length;check(edges===g.edges,`${g.name}: 边数不匹配`);
 const png=fs.readFileSync(path.join(root,'visuals',g.name+'.png'));
 check(png.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10]))&&png.readUInt32BE(16)===g.width&&png.readUInt32BE(20)===g.height,`${g.name}: PNG尺寸/签名错误`);
 const svg=read(path.join(root,'visuals',g.name+'.svg'));check(svg.includes(`<title>`)&&svg.includes(`viewBox="0 0 ${g.width} ${g.height}"`),`${g.name}: SVG未匹配`);stats.diagrams++;
}
const args=process.argv.slice(2),at=args.indexOf('--yaml');
if(at<0||!args[at+1])errors.push('缺少 --yaml，未执行manifest解析');
else{
 const modulePath=path.resolve(args[at+1]),entry=fs.statSync(modulePath).isDirectory()?path.join(modulePath,'dist/index.js'):modulePath;
 const yaml=await import(pathToFileURL(entry));const manifest=yaml.parse(read(path.join(root,'phase-manifest.yaml')));
 for(const key of ['workflow','project_docs','policies','phases'])check(Object.hasOwn(manifest,key),'manifest缺 '+key);
 check(manifest.phases.length===8,'manifest必须8阶段');check(manifest.workflow.current_phase===0&&manifest.workflow.status==='active','生命周期应停留Phase0评审');
 for(const [i,p] of manifest.phases.entries()){
  for(const key of ['id','name','applicability','status','entry_gate','exit_gate','source_docs','output_docs','verification','reopen_when','next_phase'])check(Object.hasOwn(p,key),`Phase${i}缺 ${key}`);
  check(p.id===i,`Phase${i}编号漂移`);check(['required','merged','optional','not_applicable','deferred'].includes(p.applicability),`Phase${i}适用性非法`);check(['pending','active','completed','blocked'].includes(p.status),`Phase${i}状态非法`);
  for(const key of ['source_docs','output_docs','verification','reopen_when'])check(Array.isArray(p[key]),`Phase${i}.${key}须为列表`);
  if(['merged','not_applicable','deferred'].includes(p.applicability))check(p.reopen_when.length>0,`Phase${i}无恢复触发`);
  if(p.applicability==='merged')check(Number.isInteger(p.merged_into),`Phase${i}无合并目标`);
  if(p.applicability==='not_applicable')check(!!p.rationale,`Phase${i}无事实理由`);
  for(const file of [...p.source_docs,...p.output_docs])check(fs.existsSync(path.join(project,file)),`Phase${i}指针缺失 ${file}`);
  stats.phases++;
 }
 for(const file of Object.values(manifest.project_docs).filter(x=>typeof x==='string'))check(fs.existsSync(path.join(project,file)),`project_docs指针缺失 ${file}`);
}
check(!fs.existsSync(path.join(root,'DEVELOPMENT_HANDOFF.md')),'未批准产品不能生成正式开发handoff');
const reader=read(path.join(root,'index.html')),payload=reader.match(/const documents=(\[[\s\S]*?\]);let current=/);
check(!!payload,'阅读版没有可解析文档数据');
if(payload){const data=JSON.parse(payload[1]);for(const doc of data)check(doc.search===read(path.join(root,doc.id+'.md')).toLowerCase(),`${doc.id}: 阅读版未同步真源`);stats.readerDocuments=data.length;check(data.length===10,'阅读版应有10篇文档');}
const output={status:errors.length?'FAIL':'PASS',...stats,errors};console.log(JSON.stringify(output,null,2));process.exitCode=errors.length?1:0;
