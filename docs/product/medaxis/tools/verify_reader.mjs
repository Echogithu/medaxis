// 文档浏览验证与受限预览；只服务本产品文档及两张已有合成展示图。
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import assert from 'node:assert/strict';
import {fileURLToPath,pathToFileURL} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..'),args=process.argv.slice(2);
const prefix='/product/medaxis/';
const media=new Map(['case-preparation.png','followup-plans.png'].map(name=>['/media/'+name,path.resolve(root,'../../media',name)]));
const types={'.html':'text/html; charset=utf-8','.md':'text/plain; charset=utf-8','.mmd':'text/plain; charset=utf-8','.svg':'image/svg+xml','.png':'image/png','.json':'application/json','.yaml':'text/plain; charset=utf-8'};
const server=http.createServer((request,response)=>{
 try{
  const pathname=decodeURIComponent(new URL(request.url,'http://127.0.0.1').pathname);
  if(pathname==='/favicon.ico'){response.writeHead(204);response.end();return}
  if(pathname==='/'){response.writeHead(302,{Location:prefix+'index.html'});response.end();return}
  let target=media.get(pathname);
  if(!target&&pathname.startsWith(prefix)){
   target=path.resolve(root,pathname.slice(prefix.length)||'index.html');
   if(!target.startsWith(root+path.sep)||target.includes(path.sep+'tools'+path.sep))target=null;
  }
  if(!target||!fs.existsSync(target)||!fs.statSync(target).isFile()){response.writeHead(404);response.end('文档不存在或不在预览范围');return}
  response.writeHead(200,{'Content-Type':types[path.extname(target)]||'application/octet-stream','Cache-Control':'no-store'});response.end(fs.readFileSync(target));
 }catch{response.writeHead(400);response.end('请求不可用')}
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const origin='http://127.0.0.1:'+server.address().port,url=origin+prefix+'index.html';
if(args.includes('--serve')){console.log(JSON.stringify({url,pid:process.pid,scope:'product docs + 2 synthetic media files'}));process.on('SIGINT',()=>server.close(()=>process.exit(0)));}
else{
 let browser;
 const result={status:'FAIL',desktopDocuments:0,mobileDocuments:0,brokenImages:[],consoleErrors:[],pageErrors:[],externalRequests:[],mindmap:{},screenshots:[]};
 const at=args.indexOf('--playwright'),outAt=args.indexOf('--output');
 const out=outAt>=0?path.resolve(args[outAt+1]):path.resolve(root,'../../../.ai/tasks/2026-10-09-product-dossier/browser');
 fs.mkdirSync(out,{recursive:true});
 try{
  assert(at>=0&&args[at+1],'用 --playwright 指定已有模块，不自动安装');
  const modulePath=path.resolve(args[at+1]),entry=fs.statSync(modulePath).isDirectory()?path.join(modulePath,'index.mjs'):modulePath;
  const {chromium}=await import(pathToFileURL(entry));
  browser=await chromium.launch({channel:'msedge',headless:true});
  const context=await browser.newContext({viewport:{width:1440,height:1000},serviceWorkers:'block'});
  await context.route('**/*',async route=>{const requestUrl=route.request().url();if(requestUrl.startsWith(origin+'/'))await route.continue();else{result.externalRequests.push(requestUrl);await route.abort()}});
  const page=await context.newPage();
  page.on('console',msg=>{if(msg.type()==='error')result.consoleErrors.push(msg.text())});page.on('pageerror',e=>result.pageErrors.push(e.message));
  await page.goto(url);await page.waitForSelector('#article h1');
  assert.equal(await page.locator('nav button').count(),10);
  const ids=await page.locator('nav button').evaluateAll(nodes=>nodes.map(n=>n.dataset.doc));
  for(const id of ids){
   await page.locator('nav button[data-doc="'+id+'"]').click();await page.waitForFunction(id=>document.querySelector('#source').getAttribute('href')===id+'.md',id);
   await page.waitForFunction(()=>[...document.querySelectorAll('#article img')].every(i=>i.complete));
   const bad=await page.locator('#article img').evaluateAll(nodes=>nodes.filter(n=>!n.naturalWidth).map(n=>n.src));result.brokenImages.push(...bad);assert.equal(bad.length,0,id+'有失败图片');
   assert.equal(await page.locator('#article h1').count(),1,id+'正文缺失');result.desktopDocuments++;
  }
  await page.locator('nav button[data-doc="PRD"]').click();
  await page.locator('#article a[href="PRODUCT_SPEC.md#mx-01"]').first().click();
  await page.waitForFunction(()=>location.hash==='#PRODUCT_SPEC~mx-01'&&document.querySelector('#source').getAttribute('href')==='PRODUCT_SPEC.md'&&document.getElementById('mx-01'));assert.equal(await page.locator('#mx-01').count(),1);
  await page.locator('#search').fill('501');const visible=await page.locator('nav button:visible').count();assert(visible>0&&visible<10,'搜索应过滤导航');result.searchFilteredDocuments=visible;await page.locator('#search').fill('');
  await page.locator('nav button[data-doc="README"]').click();await page.waitForFunction(()=>document.querySelector('#source').getAttribute('href')==='README.md'&&scrollY===0);assert((await page.locator('.hero h1').boundingBox()).y<200);await page.screenshot({path:path.join(out,'reader-desktop.png'),animations:'disabled'});result.screenshots.push('reader-desktop.png');
  await page.locator('#map-toggle').click();const frame=page.frameLocator('iframe');await frame.locator('svg .markmap-node').first().waitFor();assert((await frame.locator('svg .markmap-node').count())>20);result.embeddedMindmap=true;
  await page.setViewportSize({width:390,height:844});
  for(const id of ids){
   await page.goto(url+'#'+id);await page.waitForSelector('#article h1');
   const size=await page.evaluate(()=>({scroll:document.documentElement.scrollWidth,viewport:innerWidth}));assert(size.scroll<=size.viewport+1,id+'产生页面横向溢出');result.mobileDocuments++;
  }
  await page.goto(url+'#PRD');await page.waitForFunction(()=>document.querySelector('#source').getAttribute('href')==='PRD.md'&&scrollY===0);assert((await page.locator('.hero h1').boundingBox()).y<200);await page.screenshot({path:path.join(out,'reader-mobile.png'),animations:'disabled'});result.screenshots.push('reader-mobile.png');
  await page.locator('#menu').click();await page.locator('nav button[data-doc="USER_FLOWS"]').click();await page.waitForFunction(()=>document.querySelector('#source').getAttribute('href')==='USER_FLOWS.md');assert.equal(await page.locator('body.menu-open').count(),0);result.mobileMenu=true;
  await page.goto(origin+prefix+'visuals/product-mindmap.html');await page.locator('svg .markmap-node').first().waitFor();
  await page.waitForTimeout(1500);await page.evaluate(async()=>{await document.fonts.ready;await window.mm.fit()});await page.waitForTimeout(400);
  const before=await page.locator('svg .markmap-node').count();assert(before>20);await page.locator('svg .markmap-node circle').first().click();await page.waitForFunction(count=>document.querySelectorAll('svg .markmap-node').length<count,before);const collapsed=await page.locator('svg .markmap-node').count();
  await page.locator('svg .markmap-node circle').first().click();await page.waitForFunction(count=>document.querySelectorAll('svg .markmap-node').length>=count,before);
  const transform=await page.locator('svg > g').first().getAttribute('transform');await page.mouse.move(180,350);await page.mouse.wheel(0,-400);await page.waitForFunction(value=>document.querySelector('svg > g').getAttribute('transform')!==value,transform);
  const scaled=await page.locator('svg > g').first().getAttribute('transform');await page.mouse.move(160,500);await page.mouse.down();await page.mouse.move(220,540,{steps:5});await page.mouse.up();await page.waitForFunction(value=>document.querySelector('svg > g').getAttribute('transform')!==value,scaled);
  result.mindmap={nodes:before,collapsedNodes:collapsed,expand:true,zoom:true,drag:true};
  await page.setViewportSize({width:1440,height:1000});await page.reload();await page.waitForFunction(()=>window.mm&&document.querySelectorAll('svg .markmap-node').length>20);await page.waitForTimeout(1500);await page.evaluate(async()=>{await document.fonts.ready;await window.mm.fit()});await page.waitForTimeout(400);
  const onScreen=await page.locator('svg .markmap-node').evaluateAll(nodes=>nodes.filter(n=>{const r=n.getBoundingClientRect();return r.width>0&&r.height>0&&r.right>0&&r.bottom>0&&r.left<innerWidth&&r.top<innerHeight}).length);assert(onScreen>20,'导图节点虽存在但画面不可见');result.mindmap.visibleNodes=onScreen;
  await page.screenshot({path:path.join(out,'mindmap-desktop.png'),animations:'disabled'});result.screenshots.push('mindmap-desktop.png');
  assert.equal(result.externalRequests.length,0,'产物有外部请求');assert.equal(result.consoleErrors.length,0,'浏览器console error');assert.equal(result.pageErrors.length,0,'浏览器脚本异常');
  const denied=await context.request.get(origin+'/../../backend/.env');assert.equal(denied.status(),404);result.previewScopeRestricted=true;
  result.status='PASS';
 }catch(e){result.error=e.stack;process.exitCode=1}
 finally{if(browser)await browser.close();await new Promise(resolve=>server.close(resolve));fs.writeFileSync(path.join(out,'browser-results.json'),JSON.stringify(result,null,2),'utf8');console.log(JSON.stringify(result,null,2))}
}
