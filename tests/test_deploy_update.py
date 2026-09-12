"""Release safety checks, plus an optional real Nginx routing regression test."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tarfile
import tempfile
import time
import unittest
import urllib.error
import urllib.request

MODULE_PATH = Path(__file__).resolve().parents[1] / 'scripts' / 'deploy_update.py'
if MODULE_PATH.exists():
    SPEC = importlib.util.spec_from_file_location('deploy_update', MODULE_PATH)
    deploy = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(deploy)
else:
    deploy = None

PAGES = ['index.html', '404.html', 'courses/index.html', 'courses/pe-exam.html',
         'courses/cheer.html', 'courses/fitness.html', 'courses/athletics.html',
         'classroom/index.html', 'guides/index.html', 'guides/choose-course.html',
         'guides/start-cheer.html', 'guides/first-visit.html', 'guides/teaching.html',
         'about/index.html', 'visit/index.html', 'booking/index.html', 'privacy/index.html']
VIDEOS = ['V09', 'V11', 'V14', 'V23', 'V28', 'V35', 'V36', 'V41', 'V44', 'V50']


def release_files():
    files = {name: b'<!doctype html><html><head></head><body>Public page</body></html>'
             for name in PAGES}
    files.update({f'assets/videos/{video}.mp4': b'video sample' for video in VIDEOS})
    files.update({f'assets/{name}': b'/* public static file */' for name in
                  ['design.css', 'design.js', 'production.css', 'site.css', 'site.js', 'analytics.js']})
    files['assets/booking.js'] = b"fetch('/api/inquiries'); privacyConsent;"
    files['robots.txt'] = b'User-agent: *\nAllow: /\nDisallow: /admin\nDisallow: /api/\n'
    files['sitemap.xml'] = b'<urlset><loc>https://jiuyue.club/</loc></urlset>'
    return files


def archive_bytes(files=None, manifest_changes=None, extra=None):
    files = release_files() if files is None else dict(files)
    manifest = {'commit': 'a' * 40, 'repository': 'xlp294697-crypto/jiuyue-website-redesign-20260912',
                'files': {name: hashlib.sha256(value).hexdigest() for name, value in files.items()}}
    manifest.update(manifest_changes or {})
    files['release-manifest.json'] = json.dumps(manifest).encode()
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w:gz') as archive:
        for name, value in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(value)
            archive.addfile(member, io.BytesIO(value))
        if extra is not None:
            member, data = extra
            archive.addfile(member, io.BytesIO(data) if data is not None else None)
    return output.getvalue()


def config_fixture():
    common = '''
        root /srv/jiuyue-frontend;
        index index.html;
        autoindex off;
        expires off;
        try_files $uri $uri/ =404;
        add_header Cache-Control "no-cache" always;
        add_header X-Content-Type-Options "nosniff" always;
'''
    before = 'server {\n listen 8080;\n server_name jiuyue.club;\n'
    block = '\n    # BEGIN JIUYUE FRONTEND 20260911\n'
    for path in ['/', '/index.html', '/404.html', '/assets/site.css', '/assets/site.js']:
        block += '    location = ' + path + ' {' + common + '    }\n'
    block += '    location ^~ /courses/ {' + common + '    }\n'
    block += '    # END JIUYUE FRONTEND 20260911\n'
    after = '''
    location /api/ { proxy_pass http://127.0.0.1:3002; }
    location /admin { proxy_pass http://127.0.0.1:3002; }
    location /assets/ { proxy_pass http://127.0.0.1:3002; }
}\n'''
    return before + block + after, before, after


class DeploySafetyTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(deploy, 'The release update implementation is missing')

    def test_accepts_complete_repository_scoped_release(self):
        files, manifest = deploy.read_archive(archive_bytes())
        self.assertEqual(files, release_files())
        self.assertEqual(manifest['commit'], 'a' * 40)

    def test_rejects_traversal_aliases_links_and_duplicate_members(self):
        for name, kind in [('../escape', None), ('/etc/nginx/x', None),
                           ('assets/../escape', None), ('assets\\escape', None),
                           ('./index.html', None), ('assets//bad', None),
                           ('assets/link', tarfile.SYMTYPE), ('assets/hard', tarfile.LNKTYPE),
                           ('index.html', None)]:
            with self.subTest(name=name):
                member = tarfile.TarInfo(name)
                member.size = 1 if kind is None else 0
                if kind is not None:
                    member.type = kind
                    member.linkname = '/etc/passwd'
                with self.assertRaises(ValueError):
                    deploy.read_archive(archive_bytes(extra=(member, b'x' if kind is None else None)))

    def test_rejects_wrong_repository_digest_and_missing_manifest_entries(self):
        changes = [{'repository': 'xlp294697-crypto/previous-project'},
                   {'commit': 'not-a-commit'}, {'files': {'index.html': '0' * 64}}]
        for change in changes:
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    deploy.read_archive(archive_bytes(manifest_changes=change))
        files = release_files()
        hashes = {name: hashlib.sha256(value).hexdigest() for name, value in files.items()}
        hashes['index.html'] = '0' * 64
        with self.assertRaises(ValueError):
            deploy.read_archive(archive_bytes(files, {'files': hashes}))

    def test_rejects_backend_files_and_preview_booking_barriers(self):
        for name, payload in [('api/database.json', b'private'), ('assets/admin.js', b'admin'),
                              ('index.html', b'<meta name="ROBOTS" content="NOINDEX,nofollow">'),
                              ('booking/index.html', b'<meta http-equiv="Content-Security-Policy" content="form-action \'none\'">'),
                              ('booking/index.html', b'<meta http-equiv="Content-Security-Policy" content="form-action \'none\'"><meta http-equiv="Content-Security-Policy" content="default-src \'self\'">'),
                              ('index.html', '网站设计预览'.encode()),
                              ('assets/booking.js', b'local demonstration only'),
                              ('robots.txt', b'User-agent: *\nDisallow: /\n')]:
            with self.subTest(name=name, payload=payload):
                files = release_files()
                files[name] = payload
                with self.assertRaises(ValueError):
                    deploy.read_archive(archive_bytes(files))

    def test_404_may_be_noindex_but_all_public_pages_and_old_assets_are_required(self):
        files = release_files()
        files['404.html'] = b'<meta name="robots" content="noindex,follow">'
        deploy.read_archive(archive_bytes(files))
        for missing in ['404.html', 'privacy/index.html', 'assets/site.js', 'assets/videos/V50.mp4']:
            broken = dict(files)
            del broken[missing]
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                deploy.read_archive(archive_bytes(broken))

    def test_config_edit_preserves_unrelated_backend_bytes(self):
        original, before, after = config_fixture()
        candidate = deploy.update_config(original.encode()).decode()
        self.assertTrue(candidate.startswith(before))
        self.assertTrue(candidate.endswith(after))
        for path in ['/assets/design.css', '/assets/design.js', '/assets/production.css']:
            body = deploy.location_body(candidate, '=', path)
            self.assertIn('root /srv/jiuyue-frontend;', body)
            self.assertIn('add_header Cache-Control "no-cache" always;', body)
        self.assertEqual(deploy.location_body(original, '=', '/assets/site.js'),
                         deploy.location_body(candidate, '=', '/assets/site.js'))
        self.assertEqual(deploy.location_body(original, '^~', '/courses/'),
                         deploy.location_body(candidate, '^~', '/courses/'))

    def test_config_drift_is_rejected_before_mutation(self):
        original, _, _ = config_fixture()
        for broken in [original.replace('BEGIN JIUYUE FRONTEND', 'BEGIN UNKNOWN'),
                       original + original, original.replace('root /srv/jiuyue-frontend;', 'root /somewhere-else;'),
                       original.replace('    # END JIUYUE FRONTEND 20260911',
                                        '    location = /assets/design.css { return 200; }\n    # END JIUYUE FRONTEND 20260911')]:
            with self.subTest(broken=broken[:60]), self.assertRaises(ValueError):
                deploy.update_config(broken.encode())

    def test_atomic_switch_retains_old_directory_and_rejects_plain_directory_link(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            old, new, link = parent / 'old', parent / 'new', parent / 'current'
            old.mkdir()
            new.mkdir()
            try:
                link.symlink_to(old, target_is_directory=True)
            except OSError as error:
                self.skipTest('OS does not allow temporary directory symlinks: ' + str(error))
            deploy.replace_link(link, new)
            self.assertEqual(link.resolve(), new.resolve())
            self.assertTrue(old.is_dir())
            deploy.replace_link(link, old)
            self.assertEqual(link.resolve(), old.resolve())
            with self.assertRaises(ValueError):
                deploy.replace_link(new, old)


class NginxRoutingTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('NGINX_BINARY') or shutil.which('nginx'), 'Real Nginx is not installed locally')
    def test_root_serves_content_and_external_index_redirects_without_loop(self):
        self.assertIsNotNone(deploy)
        nginx = os.environ.get('NGINX_BINARY') or shutil.which('nginx')
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'logs').mkdir()
            (folder / 'temp').mkdir()
            (folder / 'site').mkdir()
            (folder / 'site/index.html').write_text('expected homepage', encoding='utf8')
            (folder / 'site/assets').mkdir()
            (folder / 'site/assets/design.css').write_text('new design css', encoding='utf8')
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0))
                port = probe.getsockname()[1]
            body = deploy.update_config(config_fixture()[0].encode()).decode()
            body = body.replace('listen 8080;', f'listen 127.0.0.1:{port};')
            body = body.replace('/srv/jiuyue-frontend', (folder / 'site').as_posix())
            config = 'pid nginx.pid;\nerror_log error.log;\nevents {}\nhttp { access_log off;\n' + body + '\n}\n'
            (folder / 'test.conf').write_text(config, encoding='utf8')
            checked = subprocess.run([nginx, '-p', folder.as_posix() + '/', '-c', 'test.conf', '-t'],
                                     capture_output=True, timeout=10,
                                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.assertEqual(checked.returncode, 0, checked.stderr.decode(errors='replace'))
            process = subprocess.Popen([nginx, '-p', folder.as_posix() + '/', '-c', 'test.conf', '-g', 'daemon off;'],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, *args):
                    return None
            client = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect)
            base = f'http://127.0.0.1:{port}'
            try:
                for attempt in range(100):
                    try:
                        with client.open(base + '/', timeout=1) as response:
                            self.assertEqual(response.read(), b'expected homepage')
                        break
                    except urllib.error.URLError:
                        if process.poll() is not None:
                            error_log = folder / 'error.log'
                            self.fail('Nginx startup failed: ' + (error_log.read_text() if error_log.exists() else str(process.returncode)))
                        time.sleep(.05)
                else:
                    self.fail('Nginx did not become ready')
                with client.open(base + '/?course=cheer', timeout=2) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.read(), b'expected homepage')
                with self.assertRaises(urllib.error.HTTPError) as redirect:
                    client.open(base + '/index.html?course=cheer', timeout=2)
                self.assertEqual(redirect.exception.code, 301)
                self.assertEqual(redirect.exception.headers['Location'], base + '/?course=cheer')
                with client.open(base + '/assets/design.css', timeout=2) as response:
                    self.assertEqual(response.read(), b'new design css')
            finally:
                subprocess.run([nginx, '-p', folder.as_posix() + '/', '-c', 'test.conf', '-s', 'stop'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == '__main__':
    unittest.main()
