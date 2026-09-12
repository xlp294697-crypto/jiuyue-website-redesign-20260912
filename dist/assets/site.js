'use strict';
const toggle=document.querySelector('.menu-toggle');
const nav=document.querySelector('#main-nav');
toggle?.addEventListener('click',()=>{const open=toggle.getAttribute('aria-expanded')!=='true';toggle.setAttribute('aria-expanded',String(open));nav.classList.toggle('open',open)});
document.addEventListener('keydown',event=>{if(event.key==='Escape'){toggle?.setAttribute('aria-expanded','false');nav?.classList.remove('open')}});
const media=document.querySelector('#media-dialog');
const container=document.querySelector('#media-container');
const scriptURL=new URL(document.currentScript?.src||[...document.scripts].find(s=>s.src.endsWith('/site.js')).src);
const assets=new URL('./',scriptURL);
document.querySelectorAll('[data-video]').forEach(button=>button.addEventListener('click',()=>{
  const video=document.createElement('video');video.controls=true;video.playsInline=true;video.muted=true;video.preload='metadata';
  video.src=new URL(`videos/${button.dataset.video}.mp4`,assets);video.poster=new URL(`photos/${button.dataset.video}.jpg`,assets);
  container.replaceChildren(video);document.querySelector('#media-title').textContent=button.dataset.title||'课堂片段';
  media.querySelector('.dialog-foot').textContent='真实课堂片段 · 静音浏览';media.showModal();video.play().catch(()=>{});
}));
media?.querySelector('.dialog-close').addEventListener('click',()=>media.close());
media?.addEventListener('click',event=>{if(event.target===media){const rect=media.getBoundingClientRect();if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)media.close()}});
media?.addEventListener('close',()=>{container.querySelector('video')?.pause();container.replaceChildren()});

document.querySelectorAll('[data-image]').forEach(button=>button.addEventListener('click',()=>{
  const image=document.createElement('img');image.src=button.dataset.image;image.alt=button.dataset.title;image.className='cert-full';
  container.replaceChildren(image);document.querySelector('#media-title').textContent=button.dataset.title;
  media.querySelector('.dialog-foot').textContent='现有官网公开资料 · 点击关闭或按 Esc 返回';media.showModal();
}));

const filters=[...document.querySelectorAll('[data-filter]')];
function filterClassroom(selected){
  if(!filters.some(button=>button.dataset.filter===selected))selected='all';
  filters.forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.filter===selected)));
  let count=0;
  document.querySelectorAll('[data-category]').forEach(card=>{card.hidden=selected!=='all'&&card.dataset.category!==selected;if(!card.hidden)count++});
  const countLabel=document.querySelector('#filter-count');if(countLabel)countLabel.textContent=`共 ${count} 段课堂与活动片段`;
  const empty=document.querySelector('.no-results');if(empty)empty.hidden=count!==0;
}
filters.forEach(button=>button.addEventListener('click',()=>filterClassroom(button.dataset.filter)));
if(filters.length)filterClassroom(new URLSearchParams(location.search).get('course')||'all');

const legacyAnchors={assessment:'booking/index.html',courses:'courses/index.html',team:'about/index.html#team',qualifications:'about/index.html#qualifications',achievements:'about/index.html#achievements'};
if((location.pathname==='/'||location.pathname==='/index.html')&&legacyAnchors[location.hash.slice(1)])location.replace('/'+legacyAnchors[location.hash.slice(1)]);
