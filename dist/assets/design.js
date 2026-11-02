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

document.querySelector('[data-copy-address]')?.addEventListener('click',async()=>{try{await navigator.clipboard.writeText('到店参考：宜兴市宜城街道体育场2号门。预约时请确认本次上课地址、集合点和时间。');showToast('到店信息已复制。');}catch{showToast('请选中页面上的地址文字进行复制。');}});
function showToast(message){let toast=document.querySelector('.toast');if(!toast){toast=document.createElement('div');toast.className='toast';toast.setAttribute('role','status');document.body.append(toast);}toast.textContent=message;toast.hidden=false;clearTimeout(window.toastTimer);window.toastTimer=setTimeout(()=>toast.hidden=true,3500);}

const imageDialog=document.querySelector('#image-dialog');
function openPublicImage(source,title){
  if(!imageDialog)return;
  imageDialog.querySelector('#image-title').textContent=title;
  const img=imageDialog.querySelector('#credential-image');img.src=source;img.alt=title;
  imageDialog.showModal();
}
document.querySelectorAll('[data-image]').forEach(button=>button.addEventListener('click',()=>openPublicImage(button.dataset.image,button.dataset.title||'公开资质资料')));

/* This public competition is maintained in the existing school showcase backend.
   The static result remains readable when the API or photos are unavailable. */
const competitionShowcaseId='6029204f-d3d6-4b84-8546-f50cbba3272f';
const competitionPhotoLabels={
  '4ee7d0de-1e55-4f09-bdbc-87de4d71749f':'双冠军队合照',
  '033100e9-7e8f-4423-a89c-8cd1fa6d85ec':'赛后纪念合照',
  '1cf527f4-1f68-47c2-b29b-ea488c799d5e':'花球庆祝合影',
  '89a8d209-e7e6-4cbc-ad3e-abe704434b70':'冠军奖杯与证书'
};
function competitionPhotos(payload){
  const item=payload?.data;
  if(!item||item.id!==competitionShowcaseId||item.type!=='competition'||item.status!=='published'
    ||item.competitionName!=='2026年全国啦啦操联赛（无锡站）'||item.eventDate!=='2026-11-01'||!Array.isArray(item.images))return [];
  const photos=[];
  for(const image of item.images){
    if(typeof image?.url!=='string')continue;
    try{
      const url=new URL(image.url,location.origin);
      if(url.origin!==location.origin||url.username||url.password||url.search||url.hash
        ||!/^\/school\/api\/v1\/public\/showcase-media\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(url.pathname))continue;
      if(!photos.includes(url.pathname))photos.push(url.pathname);
      if(photos.length===9)break;
    }catch{ /* Invalid URLs never become DOM attributes. */ }
  }
  return photos;
}
async function loadCompetitionGallery(){
  const gallery=document.querySelector('#competition-gallery');
  if(!gallery)return;
  const status=document.querySelector('#competition-gallery-status');
  const controller=new AbortController();
  const timeout=setTimeout(()=>controller.abort(),8000);
  try{
    const response=await fetch(`/school/api/v1/public/showcases/${competitionShowcaseId}`,{
      credentials:'omit',redirect:'error',headers:{Accept:'application/json'},signal:controller.signal
    });
    if(!response.ok)throw new Error('showcase_unavailable');
    const photos=competitionPhotos(await response.json());
    if(!photos.length)throw new Error('showcase_photos_unavailable');
    const cards=photos.map((source,index)=>{
      const label=competitionPhotoLabels[source.split('/').pop()]||`赛事照片 ${index+1}`;
      const title=`2026年全国啦啦操联赛（无锡站）· ${label}`;
      const card=document.createElement('article');card.className='cert-card';
      const button=document.createElement('button');button.type='button';button.setAttribute('aria-label',`放大查看：${title}`);
      const image=document.createElement('img');image.src=source;image.alt=title;
      image.width=960;image.height=720;image.loading='lazy';image.decoding='async';
      button.append(image);button.addEventListener('click',()=>openPublicImage(source,title));
      const caption=document.createElement('p');caption.textContent=`${label} · 点击查看大图`;
      card.append(button,caption);return card;
    });
    gallery.replaceChildren(...cards);
    if(status)status.textContent=`${photos.length} 张赛场照片，点击可放大查看。`;
  }catch{
    if(status)status.textContent='赛场照片暂时无法加载，请稍后刷新。';
  }finally{clearTimeout(timeout);}
}
loadCompetitionGallery();

/* Progressive enhancement: the existing classroom buttons own filtering and
   accessibility; this decorative highlight follows them, including wrapped rows. */
document.querySelectorAll('.liquid-glass-ui .chips').forEach(group=>{
  const buttons=[...group.querySelectorAll('[data-filter]')];
  if(buttons.length<2)return;
  const indicator=document.createElement('span');
  indicator.className='glass-filter-indicator';
  indicator.setAttribute('aria-hidden','true');
  group.append(indicator);
  group.classList.add('glass-filter-ready');
  let frame=0;
  function positionIndicator(){
    const selected=buttons.find(button=>button.getAttribute('aria-pressed')==='true');
    if(!selected)return;
    indicator.style.width=`${selected.offsetWidth}px`;
    indicator.style.height=`${selected.offsetHeight}px`;
    indicator.style.transform=`translate3d(${selected.offsetLeft}px,${selected.offsetTop}px,0)`;
  }
  function schedulePosition(){
    if(frame)return;
    frame=requestAnimationFrame(()=>{frame=0;positionIndicator();});
  }
  positionIndicator();
  requestAnimationFrame(()=>indicator.setAttribute('data-positioned','true'));
  group.addEventListener('click',event=>{if(event.target.closest('[data-filter]'))schedulePosition();});
  if(typeof ResizeObserver!=='undefined')new ResizeObserver(schedulePosition).observe(group);
  else window.addEventListener('resize',schedulePosition,{passive:true});
  document.fonts?.ready.then(schedulePosition);
});
