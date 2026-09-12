/* Public website navigation, classroom media, and image galleries. */
// Preserve bookmarked sections from the previous single-page homepage.
const legacyAnchors={assessment:'/booking/index.html#booking-form',courses:'/courses/index.html',team:'/about/index.html#team',qualifications:'/about/index.html#qualifications',achievements:'/about/index.html#achievements'};
const legacySection=location.hash.slice(1);
if((location.pathname==='/'||location.pathname==='/index.html')&&Object.hasOwn(legacyAnchors,legacySection))location.replace(legacyAnchors[legacySection]);
const menu=document.querySelector('.menu-toggle'), nav=document.querySelector('#main-nav');
menu?.addEventListener('click',()=>{const open=menu.getAttribute('aria-expanded')!=='true';menu.setAttribute('aria-expanded',String(open));nav.classList.toggle('open',open);});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&nav?.classList.contains('open')){nav.classList.remove('open');menu.setAttribute('aria-expanded','false');menu.focus();}});
nav?.addEventListener('click',e=>{if(e.target.closest('a')){nav.classList.remove('open');menu.setAttribute('aria-expanded','false');}});

const form=document.querySelector('#booking-form'),courseSelect=form?.querySelector('[name=course]');
if(courseSelect){const requested=new URLSearchParams(location.search).get('course');if([...courseSelect.options].some(o=>o.value===requested)&&requested)courseSelect.value=requested;}
document.querySelectorAll('a[href="#booking-form"]').forEach(link=>link.addEventListener('click',()=>{setTimeout(()=>form?.querySelector('select,input')?.focus({preventScroll:true}),400);}));

const mediaDialog=document.querySelector('#media-dialog'),video=mediaDialog?.querySelector('video');
document.querySelectorAll('[data-video]').forEach(button=>button.addEventListener('click',()=>{
  mediaDialog.querySelector('#media-title').textContent=button.dataset.title;
  video.poster=button.dataset.poster;video.src=button.dataset.video;video.muted=true;mediaDialog.showModal();
  video.play().catch(()=>{ /* Native controls remain available if the browser requires another gesture. */ });
}));
mediaDialog?.addEventListener('close',()=>{video.pause();video.removeAttribute('src');video.load();});
document.querySelectorAll('[data-close-dialog]').forEach(button=>button.addEventListener('click',()=>button.closest('dialog').close()));
document.querySelectorAll('dialog').forEach(dialog=>dialog.addEventListener('click',e=>{if(e.target===dialog){const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dialog.close();}}));

const filters=document.querySelectorAll('[data-filter]');
filters.forEach(button=>button.addEventListener('click',()=>{const value=button.dataset.filter;filters.forEach(b=>b.setAttribute('aria-pressed',String(b===button)));document.querySelectorAll('[data-category]').forEach(card=>{card.hidden=value!=='all'&&card.dataset.category!==value;});const count=document.querySelectorAll('[data-category]:not([hidden])').length;const status=document.querySelector('#filter-status');if(status)status.textContent=`显示 ${count} 个课堂片段`; }));
if(filters.length){const q=new URLSearchParams(location.search).get('course');[...filters].find(b=>b.dataset.filter===q)?.click();}

document.querySelector('[data-copy-address]')?.addEventListener('click',async()=>{try{await navigator.clipboard.writeText('宜兴市宜城街道体育场2号门，具体集合点请预约确认');showToast('到店信息已复制。');}catch{showToast('请选中页面上的地址文字进行复制。');}});
function showToast(message){let toast=document.querySelector('.toast');if(!toast){toast=document.createElement('div');toast.className='toast';toast.setAttribute('role','status');document.body.append(toast);}toast.textContent=message;toast.hidden=false;clearTimeout(window.toastTimer);window.toastTimer=setTimeout(()=>toast.hidden=true,3500);}

const imageDialog=document.querySelector('#image-dialog');
document.querySelectorAll('[data-image]').forEach(button=>button.addEventListener('click',()=>{
  if(!imageDialog)return;
  const title=button.dataset.title||'公开资质资料';
  imageDialog.querySelector('#image-title').textContent=title;
  const img=imageDialog.querySelector('#credential-image');img.src=button.dataset.image;img.alt=title;
  imageDialog.showModal();
}));
