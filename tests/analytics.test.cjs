const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const vm=require('node:vm');const path=require('node:path');
function setup(stored={}){
  const values=new Map(Object.entries(stored)),events={},calls=[];
  const buttons={};for(const selector of ['[data-analytics-accept]','[data-analytics-reject]'])buttons[selector]={focus(){},addEventListener:(_,fn)=>events[selector]=fn};
  const panel={hidden:true,querySelector:key=>buttons[key]};
  const settings={addEventListener:(_,fn)=>events.settings=fn};
  const context={URL,URLSearchParams,location:{search:'',pathname:'/courses/cheer.html'},document:{referrer:'',querySelector:key=>key==='#analytics-consent'?panel:settings,querySelectorAll:()=>[]},window:{},innerWidth:390,localStorage:{getItem:k=>values.get(k),setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)},crypto:require('node:crypto').webcrypto,AbortController,setTimeout,clearTimeout,fetch:async(url,o)=>{calls.push({url,body:JSON.parse(o.body)});return {ok:true,json:async()=>({ok:true})}}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../dist/assets/analytics.js'),'utf8'),context);return {values,events,calls,panel,api:context.window.jiuyueAnalytics};
}
test('no consent means no visitor ID and no event request',()=>{const s=setup();assert.equal(s.calls.length,0);assert.equal(s.values.has('jiuyueVisitor'),false);assert.equal(s.panel.hidden,false)});
test('accept enables tracking; rejecting afterwards clears identification and stops requests',()=>{const s=setup();s.events['[data-analytics-accept]']();assert.equal(s.calls.length,1);assert.equal(s.calls[0].body.analyticsConsent,true);s.events['[data-analytics-reject]']();s.api.track('page_view');assert.equal(s.calls.length,1);assert.equal(s.values.has('jiuyueVisitor'),false);assert.equal(s.api.hasConsent(),false)});
test('an obsolete consent version is not silently reused',()=>{const s=setup({jiuyueAnalyticsConsent:'yes',jiuyueAnalyticsConsentVersion:'2020-01-01',jiuyueAnalyticsConsentAt:'2020-01-01'});assert.equal(s.calls.length,0);assert.equal(s.panel.hidden,false)});
