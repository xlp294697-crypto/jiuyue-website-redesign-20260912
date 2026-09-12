'use strict';
(() => {
  const form=document.querySelector('#booking-form');
  if(!form)return;
  const course=form.elements.course;
  const chosen=new URLSearchParams(location.search).get('course');
  if([...course.options].some(option=>option.value===chosen))course.value=chosen;
  const submit=document.querySelector('#booking-submit');
  const status=document.querySelector('#form-status');
  let submitting=false;
  submit.disabled=false;
  form.addEventListener('submit',async event=>{
    event.preventDefault();
    if(submitting||!form.reportValidity())return;
    const fields=Object.fromEntries(new FormData(form));
    const analytics=window.jiuyueAnalytics;
    const attributed=analytics?.hasConsent()===true;
    const body={parentName:fields.parentName,phone:fields.phone,grade:fields.grade,
      course:course.selectedOptions[0].textContent,concern:fields.concern,
      preferredTime:fields.preferredTime,website:fields.website||'',
      privacyConsent:fields.privacyConsent==='yes',analyticsConsent:attributed,
      sourcePage:attributed?location.pathname:'',sourceSection:attributed?'booking':'',
      ...(attributed?analytics.attribution():{})};
    submitting=true;submit.disabled=true;submit.textContent='正在提交…';
    status.hidden=false;status.textContent='正在提交，请稍候。';status.classList.remove('error');
    const controller=new AbortController();
    const timeout=setTimeout(()=>controller.abort(),15000);
    try{
      let response,data;
      try{
        response=await fetch('/api/inquiries',{method:'POST',credentials:'same-origin',headers:{'content-type':'application/json'},body:JSON.stringify(body),signal:controller.signal});
        data=await response.json();
      }catch{
        throw new Error('网络连接异常或请求超时，预约可能已提交。请勿连续重复提交，可致电 180 6173 6378 确认。');
      }
      if(!response.ok)throw new Error(data.error?.message||data.error||'提交失败，请稍后重试。');
      form.reset();
      status.textContent='预约已提交，我们会尽快与您电话联系，确认课程、体测和到店安排。';
      analytics?.track('booking_success',{section:'booking'});
    }catch(error){status.textContent=error.message;status.classList.add('error');}
    finally{clearTimeout(timeout);submitting=false;submit.disabled=false;submit.textContent='提交预约　↗';status.focus();}
  });
})();
