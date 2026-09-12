const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

function navigate(pathname, hash, search = '') {
  const redirects = [];
  const context = {
    location: { pathname, hash, search, replace: target => redirects.push(target) },
    document: { querySelector: () => null, querySelectorAll: () => [], addEventListener() {} },
    URLSearchParams,
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../dist/assets/design.js'), 'utf8'), context);
  return redirects;
}

test('legacy home links route to the corresponding page while inner-page anchors stay intact', () => {
  const expected = {
    assessment: '/booking/index.html#booking-form',
    courses: '/courses/index.html',
    team: '/about/index.html#team',
    qualifications: '/about/index.html#qualifications',
    achievements: '/about/index.html#achievements',
  };
  for (const [hash, target] of Object.entries(expected)) {
    assert.deepEqual(navigate('/', '#' + hash), [target]);
    assert.deepEqual(navigate('/index.html', '#' + hash), [target]);
    assert.deepEqual(navigate('/about/index.html', '#' + hash), []);
  }
  assert.deepEqual(navigate('/', '#unknown'), []);
  assert.deepEqual(navigate('/booking/index.html', '#booking-form'), []);
  assert.match(fs.readFileSync(path.join(__dirname, '../dist/about/index.html'), 'utf8'), /id="achievements"/);
});
