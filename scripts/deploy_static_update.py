"""Apply the three-file booking QR update to an existing immutable frontend.

Linux/root only. Nginx configuration is read and checked, never changed or
reloaded. The archive contains the three public files and incremental-manifest.json.
No POST request, backend write, repository credential or customer record is used.
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

REPOSITORY = 'xlp294697-crypto/jiuyue-website-redesign-20260912'
CONFIG = Path('/etc/nginx/sites-available/jiuyue-sports')
ENABLED = Path('/etc/nginx/sites-enabled/jiuyue-sports')
LINK = Path('/srv/jiuyue-frontend')
IMAGE = 'assets/photos/wechat-contact.png'
CHANGES = frozenset(['booking/index.html', 'assets/production.css', IMAGE])
MANIFEST_NAME = 'incremental-manifest.json'
PROTECTED = ('/', '/admin', '/admin/mobile/', '/assets/admin.js', '/assets/app.js', '/assets/styles.css')
PRIVATE = ('/api/session', '/api/inquiries', '/api/dashboard')
CSP = "default-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; img-src 'self' data:; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; object-src 'none'"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(payload):
    return hashlib.sha256(payload).hexdigest()


def valid_sha(value, length=64):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{' + str(length) + '}', value) is not None


def safe_path(name):
    path = PurePosixPath(name)
    return (re.fullmatch(r'[A-Za-z0-9_./-]+', name) is not None and not path.is_absolute() and
            str(path) == name and all(part not in ('', '.', '..') and not part.startswith('.') for part in path.parts)
            and path.parts[0] not in ('admin', 'api'))


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'Duplicate manifest key')
        result[key] = value
    return result


class BookingPolicy(HTMLParser):
    def __init__(self):
        super().__init__()
        self.blocked = False

    def handle_starttag(self, tag, attrs):
        if tag != 'meta':
            return
        attrs = {key: (value or '').lower() for key, value in attrs}
        if attrs.get('name') == 'robots' and 'noindex' in attrs.get('content', ''):
            self.blocked = True
        if attrs.get('http-equiv') == 'content-security-policy' and re.search(
                r"(?:form-action|connect-src)\s+'none'", attrs.get('content', '')):
            self.blocked = True


def validate_changes(files, manifest):
    require(isinstance(manifest, dict) and manifest.get('repository') == REPOSITORY, 'Wrong repository')
    require(valid_sha(manifest.get('base_commit'), 40) and valid_sha(manifest.get('target_commit'), 40)
            and manifest['base_commit'] != manifest['target_commit'], 'Invalid source commits')
    expected = manifest.get('files')
    require(isinstance(expected, dict) and set(expected) == CHANGES and set(files) == CHANGES,
            'Expected exactly the three approved files')
    for name, payload in files.items():
        entry = expected[name]
        require(isinstance(entry, dict) and set(entry) == {'old_sha256', 'new_sha256'}, 'Invalid change entry')
        require(valid_sha(entry['new_sha256']) and sha(payload) == entry['new_sha256'], 'New content digest differs: ' + name)
        require((entry['old_sha256'] is None if name == IMAGE else valid_sha(entry['old_sha256'])),
                'Invalid previous digest: ' + name)
        require(entry['old_sha256'] != entry['new_sha256'], 'Unchanged file in incremental release: ' + name)
    require(files[IMAGE].startswith(b'\x89PNG\r\n\x1a\n'), 'Expected original PNG image')
    html = files['booking/index.html'].decode('utf8')
    policy = BookingPolicy()
    policy.feed(html)
    require(not policy.blocked and '127.0.0.1' not in html and 'localhost' not in html,
            'Booking page retains a preview restriction')
    require('/' + IMAGE in html and '/assets/booking.js' in html, 'Booking image or submission script reference missing')
    require(bool(files['assets/production.css'].strip()), 'Empty production stylesheet')


def read_archive(payload):
    require(len(payload) <= 20_000_000, 'Incremental archive too large')
    files = {}
    total = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode='r|gz') as archive:
            for member in archive:
                require(len(files) < 4 and member.isfile() and not member.issparse(), 'Unexpected archive member')
                require(safe_path(member.name) and member.name in CHANGES | {MANIFEST_NAME}, 'Unapproved archive path')
                require(member.name not in files and 0 < member.size <= 10_000_000, 'Duplicate or invalid archive member')
                total += member.size
                require(total <= 20_000_000, 'Expanded archive too large')
                stream = archive.extractfile(member)
                require(stream is not None, 'Unreadable archive member')
                files[member.name] = stream.read()
                require(len(files[member.name]) == member.size, 'Truncated archive member')
    except (tarfile.TarError, EOFError) as error:
        raise ValueError('Invalid archive') from error
    require(set(files) == CHANGES | {MANIFEST_NAME}, 'Incremental package members differ')
    manifest = json.loads(files.pop(MANIFEST_NAME), object_pairs_hook=unique_object)
    validate_changes(files, manifest)
    return files, manifest


def verify_release(folder, commit, enforce_owner=False):
    require(folder.is_dir() and not folder.is_symlink(), 'Release must be a real directory')
    actual = set()
    for path in [folder, *folder.rglob('*')]:
        metadata = path.lstat()
        require(stat.S_ISREG(metadata.st_mode) or stat.S_ISDIR(metadata.st_mode), 'Release contains a link or special file')
        if enforce_owner:
            require(metadata.st_uid == 0 and not metadata.st_mode & 0o022, 'Release is writable by another user')
        if stat.S_ISREG(metadata.st_mode):
            require(metadata.st_nlink == 1, 'Release contains hard-linked files')
            actual.add(path.relative_to(folder).as_posix())
    manifest_path = folder / 'release-manifest.json'
    require('release-manifest.json' in actual and manifest_path.stat().st_size < 1_000_000, 'Release manifest missing or oversized')
    manifest = json.loads(manifest_path.read_bytes(), object_pairs_hook=unique_object)
    require(isinstance(manifest, dict) and manifest.get('repository') == REPOSITORY and manifest.get('commit') == commit,
            'Base release repository or commit differs')
    hashes = manifest.get('files')
    require(isinstance(hashes, dict) and 0 < len(hashes) < 250 and set(hashes) == actual - {'release-manifest.json'},
            'Release manifest file set differs')
    for name, checksum in hashes.items():
        require(safe_path(name) and valid_sha(checksum) and sha((folder / name).read_bytes()) == checksum,
                'Release file integrity differs: ' + name)
    return manifest


def prepare_release(base, new, files, change_manifest, enforce_owner=False):
    """Verify before creating the destination, then copy and validate all public files."""
    validate_changes(files, change_manifest)
    previous = verify_release(base, change_manifest['base_commit'], enforce_owner)
    require(not os.path.lexists(new), 'Refusing to overwrite an existing destination')
    for name, entry in change_manifest['files'].items():
        expected = entry['old_sha256']
        if expected is None:
            require(name not in previous['files'] and not os.path.lexists(base / name), 'New image already exists')
        else:
            require(previous['files'].get(name) == expected, 'Old content digest differs: ' + name)
    new.mkdir(mode=0o700)
    for name in previous['files']:
        destination = new / name
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copyfile(base / name, destination)
        os.chmod(destination, 0o644)
    # A second digest pass detects source drift during the copy itself.
    for name, checksum in previous['files'].items():
        require(sha((new / name).read_bytes()) == checksum, 'Source changed while copying: ' + name)
    for name, payload in files.items():
        destination = new / name
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        destination.write_bytes(payload)
        os.chmod(destination, 0o644)
    manifest = {'repository': REPOSITORY, 'commit': change_manifest['target_commit'],
                'files': {**previous['files'], **{name: entry['new_sha256'] for name, entry in change_manifest['files'].items()}}}
    (new / 'release-manifest.json').write_text(json.dumps(manifest, sort_keys=True, indent=2), encoding='utf8')
    os.chmod(new / 'release-manifest.json', 0o644)
    verify_release(new, change_manifest['target_commit'], enforce_owner)
    for directory, _, _ in os.walk(new):
        os.chmod(directory, 0o755)
    return manifest


def replace_link(link, target):
    require(link.is_symlink() and target.is_dir() and not target.is_symlink(), 'Unexpected frontend link or release target')
    temporary = link.parent / ('.jiuyue-switch-' + uuid.uuid4().hex)
    try:
        temporary.symlink_to(target, target_is_directory=True)
        os.replace(temporary, link)
    finally:
        if temporary.is_symlink():
            temporary.unlink()


def request(path):
    completed = subprocess.run(['curl', '--silent', '--show-error', '--noproxy', '*', '--max-time', '20',
        '--resolve', 'jiuyue.club:443:127.0.0.1', '-D', '-', 'https://jiuyue.club' + path],
        capture_output=True, timeout=25)
    require(completed.returncode == 0, 'Local HTTPS request failed')
    header, body = completed.stdout.split(b'\r\n\r\n', 1)
    headers = {}
    for line in header.splitlines()[1:]:
        if b':' in line:
            key, value = line.split(b':', 1)
            headers[key.decode().lower()] = value.decode().strip()
    return int(header.splitlines()[0].split()[1]), headers, body


def public_baseline():
    result = {}
    for path in PROTECTED + ('/api/health',) + PRIVATE:
        status, _, body = request(path)
        require(status == (401 if path in PRIVATE else 200), 'Existing route unhealthy: ' + path)
        result[path] = {'status': status}
        if path in PROTECTED:
            result[path]['sha256'] = sha(body)
    return result


def current_state():
    require(sys.platform.startswith('linux') and os.geteuid() == 0, 'Run on the existing Linux host as root')
    require(CONFIG.is_file() and not CONFIG.is_symlink() and ENABLED.is_symlink() and ENABLED.resolve() == CONFIG,
            'Unexpected Nginx configuration location')
    require(LINK.is_symlink(), 'Frontend is not a symbolic link')
    release = LINK.resolve(strict=True)
    require(release.parent == Path('/srv') and release.name.startswith('jiuyue-frontend-') and release.is_dir(),
            'Unexpected release location')
    return {'release': str(release), 'symlink_target': os.readlink(LINK),
            'config_sha256': sha(CONFIG.read_bytes()), 'manifest_sha256': sha((release / 'release-manifest.json').read_bytes())}


def deploy(args):
    require(sys.platform.startswith('linux') and os.geteuid() == 0, 'Run on the existing Linux host as root')
    import fcntl
    require(valid_sha(args.sha256) and valid_sha(args.expected_config), 'Invalid expected SHA-256 argument')
    descriptor = os.open('/run/jiuyue-frontend-deploy.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'a') as lock:
        metadata = os.fstat(lock.fileno())
        require(stat.S_ISREG(metadata.st_mode) and metadata.st_uid == 0 and not metadata.st_mode & 0o022, 'Unexpected deploy lock')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = current_state()
        require(state['config_sha256'] == args.expected_config and state['release'] == args.expected_release,
                'Current configuration or release differs from inspection')
        archive = Path(args.archive)
        require(archive.is_file() and not archive.is_symlink() and archive.stat().st_size <= 20_000_000, 'Unexpected archive path')
        payload = archive.read_bytes()
        require(sha(payload) == args.sha256, 'Archive digest differs')
        files, changes = read_archive(payload)
        old = Path(state['release'])
        verify_release(old, changes['base_commit'], enforce_owner=True)
        before = public_baseline()
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        backup = Path(tempfile.mkdtemp(prefix='jiuyue-static-backup-' + stamp + '-', dir='/root'))
        os.chmod(backup, 0o700)
        (backup / 'before.json').write_text(json.dumps({'state': state, 'public_routes': before}, indent=2), encoding='utf8')
        (backup / 'incremental-manifest.json').write_text(json.dumps(changes, sort_keys=True, indent=2), encoding='utf8')
        shutil.copyfile(old / 'release-manifest.json', backup / 'previous-release-manifest.json')
        shutil.copyfile(CONFIG, backup / 'jiuyue-sports.conf')
        new = Path('/srv') / ('jiuyue-frontend-' + stamp + '-' + uuid.uuid4().hex[:12])
        switched = False
        try:
            manifest = prepare_release(old, new, files, changes, enforce_owner=True)
            require(current_state() == state, 'Site changed during release preparation')
            verify_release(old, changes['base_commit'], enforce_owner=True)
            replace_link(LINK, new)
            switched = True
            for _ in range(30):
                status, _, content = request('/booking/index.html')
                if status == 200 and sha(content) == changes['files']['booking/index.html']['new_sha256']:
                    break
                time.sleep(.1)
            else:
                raise RuntimeError('Updated booking page did not become ready')
            types = {'booking/index.html': 'text/html', 'assets/production.css': 'text/css', IMAGE: 'image/png'}
            for name, content in files.items():
                status, headers, public = request('/' + name)
                require(status == 200 and sha(public) == sha(content), 'Published change differs: ' + name)
                require(headers.get('content-type', '').split(';')[0] == types[name], 'Published MIME differs: ' + name)
                require(headers.get('content-security-policy') == CSP, 'Published security policy differs: ' + name)
            require(public_baseline() == before, 'Homepage, backend resources or access control changed')
            require(sha(CONFIG.read_bytes()) == state['config_sha256'] and LINK.resolve(strict=True) == new,
                    'Configuration or frontend changed during validation')
            result = {'status': 'deployed', 'repository': REPOSITORY, 'commit': changes['target_commit'],
                'previous_commit': changes['base_commit'], 'archive_sha256': args.sha256,
                'release': str(new), 'previous_release': str(old), 'backup': str(backup),
                'config_sha256': state['config_sha256'], 'nginx_configuration_changed': False,
                'verified_changed_files': len(files), 'verified_release_files': len(manifest['files']),
                'homepage_and_backend_unchanged': True, 'private_api_anonymous': 401,
                'post_requests_sent': 0, 'deployment_script_sha256': sha(Path(__file__).read_bytes())}
            (backup / 'deployment-result.json').write_text(json.dumps(result, indent=2), encoding='utf8')
            print(json.dumps(result), flush=True)
            return 0
        except Exception as error:
            restored = False
            rollback_error = None
            try:
                if switched:
                    require(LINK.is_symlink() and LINK.resolve(strict=True) == new, 'Frontend changed independently; refusing rollback overwrite')
                    replace_link(LINK, old)
                require(LINK.resolve(strict=True) == old and sha(CONFIG.read_bytes()) == state['config_sha256'],
                        'Original release or configuration differs')
                require(public_baseline() == before, 'Original public routes not restored')
                restored = True
            except Exception as failure:
                rollback_error = type(failure).__name__
            result = {'status': 'failed', 'reason': str(error), 'original_site_restored': restored,
                'rollback_error_type': rollback_error, 'backup': str(backup), 'release': str(new), 'previous_release': str(old)}
            (backup / 'deployment-result.json').write_text(json.dumps(result, indent=2), encoding='utf8')
            print(json.dumps(result), flush=True)
            return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inspect', action='store_true')
    parser.add_argument('--archive')
    parser.add_argument('--sha256')
    parser.add_argument('--expected-config')
    parser.add_argument('--expected-release')
    args = parser.parse_args()
    try:
        if args.inspect:
            state = current_state()
            manifest = json.loads((Path(state['release']) / 'release-manifest.json').read_bytes(), object_pairs_hook=unique_object)
            verify_release(Path(state['release']), manifest['commit'], enforce_owner=True)
            print(json.dumps({'status': 'inspected', **state, 'commit': manifest['commit'],
                'old_file_sha256': {name: manifest['files'].get(name) for name in sorted(CHANGES)},
                'public_routes': public_baseline()}), flush=True)
            return 0
        if not all([args.archive, args.sha256, args.expected_config, args.expected_release]):
            parser.error('--archive, --sha256, --expected-config and --expected-release are required')
        return deploy(args)
    except Exception as error:
        print(json.dumps({'status': 'failed_before_switch', 'error_type': type(error).__name__, 'reason': str(error)}), flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
