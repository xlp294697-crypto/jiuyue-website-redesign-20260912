const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '../dist/assets/design.js'), 'utf8');
const showcaseId = '6029204f-d3d6-4b84-8546-f50cbba3272f';
const media = '/school/api/v1/public/showcase-media/11111111-2222-4333-8444-555555555555';
function runtime() {
  const context = {
    location: { pathname: '/about/index.html', hash: '', search: '', origin: 'https://jiuyue.club' },
    document: { querySelector: () => null, querySelectorAll: () => [], addEventListener() {} },
    URL, URLSearchParams,
  };
  vm.runInNewContext(source, context);
  return context;
}
function published(overrides = {}) {
  return { data: { id: showcaseId, type: 'competition', status: 'published',
    competitionName: '2026年全国啦啦操联赛（无锡站）', eventDate: '2026-11-01',
    images: [{ url: media }], ...overrides } };
}

test('the gallery uses only the exact published competition and public image paths', () => {
  const context = runtime();
  assert.equal(typeof context.competitionPhotos, 'function', 'competition photo validation must exist');
  const photos = context.competitionPhotos(published());
  assert.equal(photos.length, 1);
  assert.equal(photos[0], media);
  for (const changes of [{id:'other'}, {status:'draft'}, {type:'course'},
    {competitionName:'另一场比赛'}, {eventDate:'2025-11-01'}]) {
    assert.equal(context.competitionPhotos(published(changes)).length, 0);
  }
  assert.equal(context.competitionPhotos({ data: [] }).length, 0);
  assert.equal(context.competitionPhotos(null).length, 0);
});

test('the gallery rejects private, external, executable and ambiguous media URLs', () => {
  const context = runtime();
  assert.equal(typeof context.competitionPhotos, 'function', 'competition photo validation must exist');
  const invalid = ['https://example.com'+media, 'javascript:alert(1)', 'data:image/png;base64,AAAA',
    '/school/api/v1/admin/showcase-media/11111111-2222-4333-8444-555555555555',
    media+'?token=private', media+'#fragment', 'https://user:password@jiuyue.club'+media,
    '/school/api/v1/public/showcase-media/%2e%2e', 42, null];
  const photos = context.competitionPhotos(published({images:invalid.map(url=>({url})).concat([{url:media},{url:media}])}));
  assert.equal(photos.length, 1);
  assert.equal(photos[0], media);
  assert.equal(context.competitionPhotos(published({images:[{url:'https://jiuyue.club'+media}]}))[0], media);
});

function domRuntime(response) {
  function element(tag) {
    return { tag, children: [], attributes: {}, events: {}, textContent: '',
      append(...items) { this.children.push(...items); },
      replaceChildren(...items) { this.children = items; },
      setAttribute(name,value) { this.attributes[name] = value; },
      addEventListener(name,handler) { this.events[name] = handler; },
    };
  }
  const gallery = element('div'), status = element('p'), dialogTitle = element('h2'), dialogImage = element('img');
  const dialog = { opened: false, querySelector: name => name === '#image-title' ? dialogTitle : dialogImage,
    showModal() { this.opened = true; } };
  const requests = [], timers = [];
  const context = {
    location: { pathname: '/about/index.html', hash: '', search: '', origin: 'https://jiuyue.club' },
    document: { querySelector: name => ({'#competition-gallery':gallery, '#competition-gallery-status':status, '#image-dialog':dialog}[name] || null),
      querySelectorAll: () => [], addEventListener() {}, createElement: element },
    URL, URLSearchParams, AbortController,
    setTimeout(fn) { timers.push(fn); return timers.length; }, clearTimeout() {},
    async fetch(url,options) { requests.push({url,options}); if(response instanceof Error)throw response; return {ok:true,json:async()=>response}; },
  };
  vm.runInNewContext(source, context);
  return { context, gallery, status, dialog, dialogImage, requests, timers };
}

test('published photos render with safe DOM nodes and reuse the working image dialog', async () => {
  const state = domRuntime(published({ title:'<img src=x onerror=alert(1)>', images:[{url:media}] }));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(state.requests[0].url, '/school/api/v1/public/showcases/'+showcaseId);
  assert.equal(state.requests[0].options.credentials, 'omit');
  assert.equal(state.requests[0].options.redirect, 'error');
  assert.equal(state.gallery.children.length, 1);
  const button = state.gallery.children[0].children[0];
  assert.equal(button.type, 'button');
  assert.equal(button.children[0].src, media);
  assert.ok(button.attributes['aria-label'].includes('放大查看'));
  assert.ok(!state.status.textContent.includes('<img'));
  button.events.click();
  assert.equal(state.dialog.opened, true);
  assert.equal(state.dialogImage.src, media);
});

test('failed or unpublished results leave the static achievement visible and show a photo fallback', async () => {
  for(const response of [new Error('offline'), published({status:'unpublished'}), {data:null}]) {
    const state = domRuntime(response);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(state.gallery.children.length, 0);
    assert.match(state.status.textContent, /暂时无法加载/);
  }
  const about = fs.readFileSync(path.join(__dirname, '../dist/about/index.html'), 'utf8');
  assert.match(about, /两个冠军、一个亚军/);
  assert.match(about, /往期赛事与活动/);
  assert.match(about, /outcome-cheer-primary-first-2025.jpg/);
});
