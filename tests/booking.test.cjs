const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');

function setup(fetch){
  const handlers={};
  const selected={value:'cheer',textContent:'啦啦操专项'};
  const form={elements:{course:{value:'cheer',options:[selected],selectedOptions:[selected]},parentName:{focus(){}}},reportValidity:()=>true,addEventListener:(name,fn)=>handlers[name]=fn,reset(){this.resets++;},resets:0};
  const fields={parentName:'测试家长',phone:'13800000000',grade:'小学',course:'cheer',preferredTime:'周末',concern:'咨询班型',privacyConsent:'yes',website:''};
  const nodes={'#booking-form':form,'#booking-submit':{disabled:true,textContent:''},'#form-status':{hidden:true,focus(){},classList:{add(){},remove(){}}},'#confirmation-summary':{},'#booking-again':{addEventListener:(name,fn)=>handlers.again=fn}};
  const calls=[];
  const context={document:{querySelector:key=>nodes[key]},window:{},location:{search:'?course=cheer',pathname:'/booking/index.html'},URLSearchParams,AbortController,setTimeout,clearTimeout,FormData:class{constructor(){}*[Symbol.iterator](){yield* Object.entries(fields)}},fetch:async(url,options)=>{calls.push({url,options});return fetch(url,options)}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../dist/assets/booking.js'),'utf8'),context);
  return {form,fields,nodes,calls,submit:()=>handlers.submit({preventDefault(){}})};
}

test('successful booking sends backend-compatible course and consent, then clears inputs',async()=>{
  const s=setup(async()=>({ok:true,json:async()=>({ok:true})}));
  await s.submit();
  assert.equal(s.calls.length,1);assert.equal(s.calls[0].url,'/api/inquiries');
  const body=JSON.parse(s.calls[0].options.body);
  assert.equal(body.course,'啦啦操专项');assert.equal(body.privacyConsent,true);assert.equal(body.analyticsConsent,false);
  assert.equal(body.sourcePage,'');assert.equal(body.visitorId,undefined);
  assert.equal(s.form.resets,1);assert.match(s.nodes['#form-status'].textContent,/预约已提交/);
});
test('server rejection retains inputs and restores the submit button',async()=>{
  const s=setup(async()=>({ok:false,json:async()=>({error:{message:'请先确认预约信息处理告知。'}})}));
  await s.submit();assert.equal(s.form.resets,0);assert.equal(s.nodes['#booking-submit'].disabled,false);
  assert.match(s.nodes['#form-status'].textContent,/请先确认/);
});
test('a second click cannot submit while the first request is pending',async()=>{
  let resolve;const pending=new Promise(r=>resolve=r);const s=setup(()=>pending);
  const first=s.submit();await s.submit();assert.equal(s.calls.length,1);assert.equal(s.form.resets,0);
  resolve({ok:true,json:async()=>({ok:true})});await first;
  assert.equal(s.form.resets,1);
});
test('network failure never retries automatically or reports success',async()=>{
  const s=setup(async()=>{throw new Error('network')});await s.submit();
  assert.equal(s.calls.length,1);assert.equal(s.form.resets,0);assert.match(s.nodes['#form-status'].textContent,/可能已提交|网络/);
});
