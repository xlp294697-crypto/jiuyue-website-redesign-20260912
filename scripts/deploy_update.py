"""Update the existing jiuyue.club static frontend without changing its backend.

Run on the existing Linux host as root. Inspect first, then pass the four
explicit archive/config/release arguments. This migration accepts the original
20260911 frontend block and refuses an already migrated or unfamiliar config.
Only an empty, rejected inquiry is sent; no successful test inquiry is created.
"""
import argparse
import datetime
import hashlib
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid

CONFIG = Path('/etc/nginx/sites-available/jiuyue-sports')
ENABLED = Path('/etc/nginx/sites-enabled/jiuyue-sports')
LINK = Path('/srv/jiuyue-frontend')
REPOSITORY = 'xlp294697-crypto/jiuyue-website-redesign-20260912'
BEGIN = '    # BEGIN JIUYUE FRONTEND 20260911'
END = '    # END JIUYUE FRONTEND 20260911'
PAGES = frozenset(['index.html', '404.html', 'courses/index.html', 'courses/pe-exam.html',
    'courses/cheer.html', 'courses/fitness.html', 'courses/athletics.html',
    'classroom/index.html', 'guides/index.html', 'guides/choose-course.html',
    'guides/start-cheer.html', 'guides/first-visit.html', 'guides/teaching.html',
    'about/index.html', 'visit/index.html', 'booking/index.html', 'privacy/index.html'])
STATIC = frozenset(['assets/design.css', 'assets/design.js', 'assets/production.css',
                   'assets/site.css', 'assets/site.js', 'assets/booking.js', 'assets/analytics.js'])
VIDEOS = frozenset('assets/videos/' + name + '.mp4' for name in
                  ['V09', 'V11', 'V14', 'V23', 'V28', 'V35', 'V36', 'V41', 'V44', 'V50'])
PROTECTED = ('/admin', '/admin/mobile/', '/assets/admin.js', '/assets/app.js', '/assets/styles.css')
PRIVATE = ('/api/session', '/api/inquiries', '/api/dashboard')
CSP = "default-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; img-src 'self' data:; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; object-src 'none'"
MAX_ARCHIVE = 100_000_000
MAX_EXPANDED = 150_000_000


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'Duplicate JSON object key')
        result[key] = value
    return result


class PagePolicy(HTMLParser):
    def __init__(self):
        super().__init__()
        self.noindex = False
        self.blocked_form = False

    def handle_starttag(self, tag, attrs):
        if tag.lower() != 'meta':
            return
        values = {key.lower(): (value or '').lower() for key, value in attrs}
        if values.get('name') == 'robots' and 'noindex' in values.get('content', ''):
            self.noindex = True
        if values.get('http-equiv') == 'content-security-policy':
            self.blocked_form = self.blocked_form or bool(re.search(r"(?:form-action|connect-src)\s+'none'", values.get('content', '')))


def validate_production(files):
    require(PAGES | STATIC | VIDEOS | {'robots.txt', 'sitemap.xml'} <= set(files), 'Missing required production page or compatibility asset')
    require({name for name in files if name.endswith('.html')} == PAGES, 'Unexpected production page set')
    require({name for name in files if name.endswith('.mp4')} == VIDEOS, 'Unexpected production video set')
    for name, payload in files.items():
        root_file = name in PAGES | STATIC | {'robots.txt', 'sitemap.xml'}
        media = re.fullmatch(r'assets/(?:photos|videos|credentials)/[A-Za-z0-9_-]+\.(?:jpg|jpeg|png|webp|avif|svg|mp4)', name)
        require(root_file or media is not None, 'Unexpected public release file: ' + name)
        if name.endswith('.html'):
            html = payload.decode('utf-8')
            policy = PagePolicy()
            policy.feed(html)
            require(name == '404.html' or not policy.noindex, 'Public page prohibits indexing: ' + name)
            require(not policy.blocked_form, 'Preview form/network policy remains: ' + name)
            require(not any(word in html for word in ['网站设计预览', '设计预览', '本机演示', '预览咨询信息', '尚未提交']),
                    'Preview copy remains: ' + name)
            require('127.0.0.1' not in html and 'localhost' not in html, 'Local URL remains: ' + name)
    booking = files['assets/booking.js'].decode('utf-8')
    require('/api/inquiries' in booking and 'privacyConsent' in booking, 'Production booking contract missing')
    robots = files['robots.txt'].decode('utf-8')
    require(not re.search(r'(?im)^\s*Disallow\s*:\s*/\s*$', robots), 'Public crawler blocked')
    require('/admin' in robots and '/api/' in robots, 'Private crawl exclusions missing')
    sitemap = files['sitemap.xml'].decode('utf-8')
    require('https://jiuyue.club/' in sitemap and '127.0.0.1' not in sitemap and 'localhost' not in sitemap,
            'Production sitemap origin invalid')


def read_archive(payload):
    """Validate every archive member before creating any release filesystem path."""
    require(len(payload) <= MAX_ARCHIVE, 'Archive too large')
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode='r|gz') as archive:
            data = {}
            total = 0
            for member in archive:
                require(len(data) < 249, 'Unexpected archive member count')
                name = member.name
                path = PurePosixPath(name)
                require(member.isfile(), 'Archive contains non-regular member')
                require(not member.issparse(), 'Sparse archive members are forbidden')
                require(0 <= member.size <= 40_000_000, 'Archive member too large')
                total += member.size
                require(total <= MAX_EXPANDED, 'Expanded archive too large')
                require(re.fullmatch(r'[A-Za-z0-9_./-]+', name) is not None and
                        not path.is_absolute() and str(path) == name and
                        all(part not in ('', '.', '..') and not part.startswith('.') for part in path.parts),
                        'Unsafe archive member path')
                require(name not in data, 'Duplicate archive member')
                stream = archive.extractfile(member)
                require(stream is not None, 'Unreadable archive member')
                data[name] = stream.read()
                require(len(data[name]) == member.size, 'Truncated archive member')
            require(len(data) > 20, 'Unexpected archive member count')
    except (tarfile.TarError, EOFError) as error:
        raise ValueError('Invalid archive') from error
    require('release-manifest.json' in data, 'Release manifest missing')
    manifest = json.loads(data.pop('release-manifest.json'), object_pairs_hook=unique_object)
    require(isinstance(manifest, dict) and manifest.get('repository') == REPOSITORY, 'Wrong repository')
    require(isinstance(manifest.get('commit'), str) and re.fullmatch(r'[0-9a-f]{40}', manifest['commit']) is not None,
            'Invalid source commit')
    expected = manifest.get('files')
    require(isinstance(expected, dict) and set(expected) == set(data), 'Manifest file set differs')
    for name, value in data.items():
        require(isinstance(expected[name], str) and re.fullmatch(r'[0-9a-f]{64}', expected[name]) is not None and
                digest(value) == expected[name], 'Manifest digest differs: ' + name)
    validate_production(data)
    return data, manifest


def closing_brace(text, start):
    depth, quote, escaped, comment = 0, None, False, False
    for index in range(start, len(text)):
        char = text[index]
        if comment:
            if char == '\n':
                comment = False
            continue
        if escaped:
            escaped = False
            continue
        if char == '\\':
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = None
            continue
        if char in ('"', "'"):
            quote = char
        elif char == '#':
            comment = True
        elif char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                return index
    raise ValueError('Unbalanced Nginx block')


def location_span(text, modifier, path):
    matches = list(re.finditer(r'(?m)^[ \t]*location\s+' + re.escape(modifier) + r'\s+' +
                              re.escape(path) + r'\s*\{', text))
    require(len(matches) == 1, 'Expected one location for ' + path)
    opening = matches[0].end() - 1
    return opening, closing_brace(text, opening)


def location_body(text, modifier, path):
    opening, closing = location_span(text, modifier, path)
    return text[opening + 1:closing]


def update_config(original):
    """Edit only the already identified frontend marker block."""
    text = original.decode('utf-8')
    require(text.count(BEGIN) == 1 and text.count(END) == 1, 'Unknown frontend marker layout')
    start, end = text.index(BEGIN), text.index(END)
    require(start < end, 'Invalid frontend marker order')
    block = text[start:end]
    common = location_body(block, '=', '/')
    require(len(re.findall(r'(?m)^\s*root\s+/srv/jiuyue-frontend\s*;', common)) == 1,
            'Unexpected frontend root')
    require('try_files $uri $uri/ =404;' in common and 'index index.html;' in common,
            'Unexpected frontend static behavior')
    require(location_body(block, '=', '/index.html').strip() == common.strip(), 'Unexpected index location behavior')
    assets = ['/assets/design.css', '/assets/design.js', '/assets/production.css']
    for path in assets:
        require(re.search(r'location\s+(?:=\s+)?' + re.escape(path) + r'(?:\s|\{)', text) is None,
                'New frontend location already exists: ' + path)
    opening, closing = location_span(block, '=', '/index.html')
    # $request_uri remains the original client URI after the index module's
    # internal redirect. Thus GET / keeps serving index.html without a loop.
    redirect = '\n        if ($request_uri ~ "^/index[.]html([?]|$)") { return 301 /$is_args$args; }'
    block = block[:opening + 1] + redirect + block[opening + 1:]
    for path in assets:
        block += '    location = ' + path + ' {' + common + '}\n'
    candidate = text[:start] + block + text[end:]
    return candidate.encode('utf-8')


def replace_link(link, target):
    require(link.is_symlink(), 'Frontend link is no longer a symbolic link')
    require(target.is_dir() and not target.is_symlink(), 'Release target is not a real directory')
    temporary = link.parent / ('.jiuyue-switch-' + uuid.uuid4().hex)
    try:
        temporary.symlink_to(target, target_is_directory=True)
        os.replace(temporary, link)
    finally:
        if temporary.is_symlink():
            temporary.unlink()


def command(args, timeout=30):
    result = subprocess.run(args, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError('Command failed: ' + Path(args[0]).name)
    return result.stdout


def request(path, extra=()):
    raw = command(['curl', '--silent', '--show-error', '--noproxy', '*', '--max-time', '20',
                   '--resolve', 'jiuyue.club:443:127.0.0.1', '-D', '-', *extra,
                   'https://jiuyue.club' + path])
    header, body = raw.split(b'\r\n\r\n', 1)
    headers = {}
    for line in header.splitlines()[1:]:
        if b':' in line:
            key, value = line.split(b':', 1)
            headers[key.decode().lower()] = value.decode().strip()
    return int(header.splitlines()[0].split()[1]), headers, body


def baseline():
    result = {}
    for path in PROTECTED + ('/api/health',) + PRIVATE:
        status, _, body = request(path)
        result[path] = {'status': status}
        if path in PROTECTED:
            result[path]['sha256'] = digest(body)
    return result


def validate_baseline(current, expected=None):
    require(all(current[path]['status'] == 200 for path in PROTECTED + ('/api/health',)),
            'Existing public service route unhealthy')
    require(all(current[path]['status'] == 401 for path in PRIVATE), 'Private API access control changed')
    if expected is not None:
        require(all(current[path]['sha256'] == expected[path]['sha256'] for path in PROTECTED),
                'Protected backend resource changed')


def reject_empty_booking():
    status, _, body = request('/api/inquiries', ['-H', 'Content-Type: application/json',
        '-H', 'Origin: https://jiuyue.club', '--data', '{}'])
    require(status == 422 and json.loads(body).get('error', {}).get('code') == 'INVALID_INQUIRY',
            'Empty inquiry rejection contract changed')


def filesystem_state():
    require(sys.platform.startswith('linux') and os.geteuid() == 0, 'Run on the existing Linux host as root')
    require(CONFIG.is_file() and not CONFIG.is_symlink(), 'Unexpected Nginx config path')
    require(ENABLED.is_symlink() and ENABLED.resolve() == CONFIG, 'Unexpected enabled Nginx site')
    require(LINK.is_symlink(), 'Expected an existing frontend symbolic link')
    release = LINK.resolve(strict=True)
    require(release.parent == Path('/srv') and release.name.startswith('jiuyue-frontend-') and
            release.is_dir() and not release.is_symlink(), 'Unexpected existing release location')
    metadata = release.stat()
    require(metadata.st_uid == 0 and not metadata.st_mode & 0o022, 'Existing release is writable by another user')
    return {'config_sha256': digest(CONFIG.read_bytes()), 'release': str(release),
            'symlink_target': os.readlink(LINK)}


def replace_config(payload, metadata):
    descriptor, temporary = tempfile.mkstemp(prefix='.jiuyue-config-', dir=CONFIG.parent)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, stat.S_IMODE(metadata.st_mode))
        os.chown(temporary, metadata.st_uid, metadata.st_gid)
        os.replace(temporary, CONFIG)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def verify_static(files):
    for name, payload in files.items():
        path = '/' if name == 'index.html' else '/' + name
        status, headers, body = request(path)
        require(status == 200 and digest(body) == digest(payload), 'Published content differs: ' + name)
        require(headers.get('content-security-policy') == CSP, 'Static security policy differs: ' + name)
        suffix = name.rsplit('.', 1)[-1]
        allowed = {'html': {'text/html'}, 'css': {'text/css'}, 'js': {'application/javascript', 'text/javascript'},
                   'jpg': {'image/jpeg'}, 'jpeg': {'image/jpeg'}, 'png': {'image/png'}, 'webp': {'image/webp'},
                   'svg': {'image/svg+xml'}, 'mp4': {'video/mp4'}, 'txt': {'text/plain'},
                   'xml': {'text/xml', 'application/xml'}}
        require(suffix not in allowed or headers.get('content-type', '').split(';')[0] in allowed[suffix],
                'Static MIME type differs: ' + name)
    for name in sorted(VIDEOS):
        status, headers, body = request('/' + name, ['-H', 'Range: bytes=0-1023'])
        size = len(files[name])
        expected = files[name][:1024]
        require(status == 206 and body == expected and
                headers.get('content-range') == f'bytes 0-{len(expected)-1}/{size}', 'Video range failed: ' + name)
    status, headers, _ = request('/index.html?course=cheer')
    require(status == 301 and headers.get('location') in ('/?course=cheer', 'https://jiuyue.club/?course=cheer'),
            'Canonical homepage redirect failed')


def deploy_release(args):
    import fcntl
    require(sys.platform.startswith('linux') and os.geteuid() == 0, 'Run on the existing Linux host as root')
    for value in [args.sha256, args.expected_config]:
        require(re.fullmatch(r'[0-9a-f]{64}', value) is not None, 'Expected lowercase SHA-256 argument')
    with open('/run/jiuyue-frontend-deploy.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        initial = filesystem_state()
        require(initial['config_sha256'] == args.expected_config, 'Nginx config changed since inspection')
        require(initial['release'] == args.expected_release, 'Frontend release changed since inspection')
        archive = Path(args.archive)
        require(archive.is_file() and not archive.is_symlink() and archive.stat().st_size <= MAX_ARCHIVE,
                'Unexpected archive file')
        payload = archive.read_bytes()
        require(digest(payload) == args.sha256, 'Archive digest differs')
        files, manifest = read_archive(payload)
        original = CONFIG.read_bytes()
        metadata = CONFIG.stat()
        candidate = update_config(original)
        command(['nginx', '-t'])
        protected = baseline()
        validate_baseline(protected)
        reject_empty_booking()
        homepage_status, _, old_homepage = request('/')
        require(homepage_status == 200, 'Existing homepage unhealthy')
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        backup = Path(tempfile.mkdtemp(prefix='jiuyue-frontend-backup-' + stamp + '-', dir='/root'))
        os.chmod(backup, 0o700)
        shutil.copy2(CONFIG, backup / 'jiuyue-sports.conf')
        (backup / 'old-release.txt').write_text(initial['release'] + '\n', encoding='utf8')
        (backup / 'old-symlink-target.txt').write_text(initial['symlink_target'] + '\n', encoding='utf8')
        (backup / 'before.json').write_text(json.dumps({'filesystem': initial, 'protected_routes': protected,
            'homepage_sha256': digest(old_homepage)}, indent=2), encoding='utf8')
        release = Path(tempfile.mkdtemp(prefix='jiuyue-frontend-' + stamp + '-', dir='/srv'))
        for name, content in files.items():
            target = release / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            os.chmod(target, 0o644)
        (release / 'release-manifest.json').write_text(json.dumps(manifest, sort_keys=True, indent=2), encoding='utf8')
        os.chmod(release / 'release-manifest.json', 0o644)
        for folder, _, _ in os.walk(release):
            os.chmod(folder, 0o755)
        old_release = Path(initial['release'])
        attempted = False
        try:
            require(filesystem_state() == initial, 'Frontend changed during release preparation')
            attempted = True
            replace_config(candidate, metadata)
            command(['nginx', '-t'])
            command(['systemctl', 'reload', 'nginx'])
            # New asset routes become active while the original frontend still
            # serves requests. The following link replacement switches all pages.
            for _ in range(40):
                if request('/index.html?deploy=1')[0] == 301:
                    break
                time.sleep(.1)
            else:
                raise RuntimeError('New Nginx workers did not become ready')
            require(LINK.resolve(strict=True) == old_release and digest(CONFIG.read_bytes()) == digest(candidate),
                    'Frontend changed before activation')
            replace_link(LINK, release)
            for _ in range(40):
                status, _, body = request('/')
                if status == 200 and digest(body) == manifest['files']['index.html']:
                    break
                time.sleep(.1)
            else:
                raise RuntimeError('New homepage did not become ready')
            verify_static(files)
            validate_baseline(baseline(), protected)
            reject_empty_booking()
            result = {'status': 'deployed', 'repository': REPOSITORY, 'commit': manifest['commit'],
                      'archive_sha256': args.sha256, 'config_sha256': digest(candidate),
                      'previous_release': str(old_release), 'release': str(release), 'backup': str(backup),
                      'verified_static_files': len(files), 'verified_html_pages': len(PAGES),
                      'verified_video_ranges': len(VIDEOS), 'protected_routes_unchanged': True,
                      'private_api_anonymous': 401, 'empty_booking_rejected': 422,
                      'deployment_script_sha256': digest(Path(__file__).read_bytes())}
            (backup / 'deployment-result.json').write_text(json.dumps(result, indent=2), encoding='utf8')
            print(json.dumps(result), flush=True)
            return 0
        except Exception as error:
            restored = False
            rollback_error = None
            if attempted:
                try:
                    require(LINK.is_symlink() and LINK.resolve(strict=True) in (old_release, release),
                            'Frontend link changed independently; refusing to overwrite it')
                    require(digest(CONFIG.read_bytes()) in (digest(original), digest(candidate)),
                            'Nginx config changed independently; refusing to overwrite it')
                    if LINK.resolve(strict=True) != old_release:
                        replace_link(LINK, old_release)
                    replace_config(original, metadata)
                    command(['nginx', '-t'])
                    command(['systemctl', 'reload', 'nginx'])
                    status, _, restored_homepage = request('/')
                    require(status == 200 and digest(restored_homepage) == digest(old_homepage), 'Old homepage not restored')
                    validate_baseline(baseline(), protected)
                    restored = True
                except Exception as failure:
                    rollback_error = type(failure).__name__
            result = {'status': 'failed', 'reason': str(error), 'original_site_restored': restored,
                      'rollback_error_type': rollback_error, 'backup': str(backup), 'release': str(release),
                      'previous_release': str(old_release)}
            (backup / 'deployment-result.json').write_text(json.dumps(result, indent=2), encoding='utf8')
            print(json.dumps(result), flush=True)
            return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inspect', action='store_true', help='Read current release, config digest and public route status; make no changes')
    parser.add_argument('--archive')
    parser.add_argument('--sha256')
    parser.add_argument('--expected-config')
    parser.add_argument('--expected-release')
    args = parser.parse_args()
    try:
        if args.inspect:
            result = filesystem_state()
            result.update(status='inspected', protected_routes=baseline())
            print(json.dumps(result), flush=True)
            return 0
        if not all([args.archive, args.sha256, args.expected_config, args.expected_release]):
            parser.error('--archive, --sha256, --expected-config and --expected-release are required for deployment')
        return deploy_release(args)
    except Exception as error:
        print(json.dumps({'status': 'failed_before_switch', 'error_type': type(error).__name__, 'reason': str(error)}), flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
