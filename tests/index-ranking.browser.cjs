/* Run with Playwright available: node tests/index-ranking.browser.cjs [base URL]. */
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const source = JSON.parse(fs.readFileSync(path.join(root, 'data/index_memberships.json')));
const api = require('../index-memberships.js').create(source);
const base = process.argv[2] || 'http://127.0.0.1:8765';
const snapshots = process.env.SCREENSHOT_DIR;
const fresh = data => ({...data, fetch_status:'ok', fetched_at:new Date().toISOString(),valid_until:new Date(Date.now()+3600000).toISOString()});
const feeds = Object.fromEntries(['japan_stocks','pts_ranking'].map(key=>[key,fresh(JSON.parse(fs.readFileSync(path.join(root,`data/${key}.json`))))]));
const errors=[];
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 try {
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',async route=>{
   const url=new URL(route.request().url());
   if(url.origin!==base)return route.abort();
   const name=url.pathname.match(/\/data\/(japan_stocks|pts_ranking)\.json/);
   if(name)return route.fulfill({json:feeds[name[1]]});
   return route.continue();
 });
 await page.goto(base);
 await page.waitForFunction(()=>!document.querySelector('#rankIndexFilter').disabled && document.querySelectorAll('#rankBody tbody tr').length===30);
 const headers=await page.locator('#rankBody th').allTextContents();
 assert.equal(headers[headers.indexOf('市場')+1],'指数');
 const report={};
 for(const market of ['tse','pts']){
   await page.locator(`[data-market="${market}"]`).click();
   const rows=feeds[market==='tse'?'japan_stocks':'pts_ranking'].all_stocks.filter(s=>s.change_pct!=null).sort((a,b)=>Number(b.change_pct)-Number(a.change_pct)).slice(0,30);
   report[market]={};
   for(const condition of ['all','transition','topix_new','topix','nikkei225']){
     await page.selectOption('#rankIndexFilter',condition);
     const expected=api.filter(rows,condition);
     report[market][condition]=expected.length;
     assert.deepEqual(await page.locator('#rankBody .t-code').allTextContents(),expected.map(s=>s.code));
     assert.deepEqual(await page.locator('#rankBody .rank-no').allTextContents(),expected.map(s=>String(rows.indexOf(s)+1)));
     if(!expected.length)assert.match(await page.locator('#rankBody').innerText(),/該当する銘柄はありません/);
     for(const [i,row] of expected.entries()){
       const tags=await page.locator('#rankBody tbody tr').nth(i).locator('[data-index-filter]').evaluateAll(nodes=>nodes.map(n=>n.dataset.indexFilter));
       assert.deepEqual(tags,api.memberships(row.code));
       assert.ok((await page.locator('#rankBody tbody tr').nth(i).innerText()).includes(Number(row.price).toLocaleString('en-US',{minimumFractionDigits:0,maximumFractionDigits:0})+'円'));
     }
   }
 }
 await page.locator('[data-market="tse"]').click();
 await page.selectOption('#rankIndexFilter','all');
 for(const condition of ['transition','topix_new','topix']){
   await page.selectOption('#rankIndexFilter','all');
   await page.locator(`#rankBody [data-index-filter="${condition}"]`).first().click();
   assert.equal(await page.inputValue('#rankIndexFilter'),condition);
   assert.equal(await page.locator('dialog[open]').count(),0);
 }
 await page.selectOption('#rankIndexFilter','transition');
 await page.locator('[data-v="chart"]').click();
 assert.equal(await page.locator('.rank-chart-card').count(),report.tse.transition);
 assert.ok(await page.locator('.mini-candle').count()>0);
 await page.locator('[data-market="pts"]').click();
 assert.equal(await page.inputValue('#rankIndexFilter'),'transition');
 assert.equal(await page.locator('.rank-chart-card').count(),report.pts.transition);
 await page.evaluate(()=>boot());
 assert.equal(await page.inputValue('#rankIndexFilter'),'transition');
 assert.equal(await page.locator('.rank-chart-card').count(),report.pts.transition);
 await page.locator('[data-market="tse"]').click();
 await page.locator('[data-v="table"]').click();
 await page.locator('#rankBody .company-trigger').first().click();
 assert.equal(await page.locator('dialog[open]').count(),1);
 await page.locator('.company-close').click();
 for(const width of [1440,768,390,320]){
   await page.setViewportSize({width,height:900});
   await page.locator('#rank').scrollIntoViewIfNeeded();
   await page.evaluate(()=>{document.documentElement.style.scrollBehavior='auto';document.querySelector('#rank').scrollIntoView();window.scrollBy(0,-110)});
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`body overflow at ${width}`);
   if(snapshots)await page.screenshot({path:path.join(snapshots,`topix-${width}.png`)});
   await page.locator('[data-v="chart"]').click();
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`chart overflow at ${width}`);
   if(width===390&&snapshots)await page.screenshot({path:path.join(snapshots,'topix-mobile-chart.png')});
   await page.locator('[data-v="table"]').click();
 }
 // Non-empty Nikkei overlap and label click, even when today's leaders contain none.
 await page.evaluate(()=>{rankData={...rankData,all_stocks:[{code:'7203',name:'トヨタ自動車',change_pct:2,price:100}]};rankMarket='tse';rankIndexFilter='all';renderRank();});
 await page.locator('#rankBody [data-index-filter="nikkei225"]').click();
 assert.equal(await page.inputValue('#rankIndexFilter'),'nikkei225');
 assert.equal(await page.locator('#rankBody tbody tr').count(),1);
 assert.equal(await page.locator('#rankBody [data-index-filter="topix"]').count(),1);
 // More than 30 source rows must not backfill a filtered top 30 with the 31st.
 await page.evaluate(()=>{rankData={...rankData,all_stocks:Array.from({length:31},(_,i)=>({code:i===30?'1301':'0000',change_pct:31-i,price:100}))};rankMarket='tse';rankIndexFilter='transition';renderRank();});
 assert.equal(await page.locator('#rankBody tbody tr').count(),0);
 assert.match(await page.locator('#rankIndexCount').innerText(),/0 \/ 30/);
 // Invalid classification never prevents fresh quote rendering.
 await page.route('**/data/index_memberships.json?*',route=>route.fulfill({json:{schema_version:1,securities:{}}}));
 await page.reload();
 await page.waitForFunction(()=>document.querySelector('#rankIndexNote').textContent.includes('取得できません'));
 assert.equal(await page.locator('#rankBody tbody tr').count(),30);
 assert.equal(await page.locator('#rankIndexFilter').isDisabled(),true);
 // Stale quote data remains suppressed even with valid classification.
 await page.unroute('**/data/index_memberships.json?*');
 await page.reload();
 await page.waitForFunction(()=>!document.querySelector('#rankIndexFilter').disabled);
 await page.evaluate(()=>{rankData={...rankData,fetch_status:'stale'};renderRank();});
 assert.equal(await page.locator('#rankBody tbody tr').count(),0);
 assert.match(await page.locator('#rankBody').innerText(),/古いランキングは表示していません/);
 assert.deepEqual(errors,[]);
 console.log(JSON.stringify({passed:true,counts:report,viewports:[1440,768,390,320],pageErrors:errors}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
