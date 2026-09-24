"""Pull one public repository and atomically update an existing static webroot.

Linux/root at runtime. No token, shell, POST request, Nginx change, backend write,
archive extraction, source execution, deletion or old-release cleanup is used.
The deployment script is installed independently; fetched repository code cannot
replace it. Only the initial release manifest's exact static file set is allowed.
"""
import argparse
import hashlib
from html.parser import HTMLParser
import io
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tarfile
import time
from urllib.parse import unquote, urljoin, urlsplit
import uuid
import xml.etree.ElementTree as ET

REPOSITORY = 'xlp294697-crypto/jiuyue-website-redesign-20260912'
REMOTE = 'https://github.com/' + REPOSITORY + '.git'
ORIGIN = 'https://jiuyue.club'
MAX_ARCHIVE = 128 * 1024 * 1024
MAX_FILE = 16 * 1024 * 1024
MAX_TOTAL = 96 * 1024 * 1024
EXTENSIONS = {'.html', '.css', '.js', '.png', '.jpg', '.jpeg', '.webp', '.gif', '.ico', '.mp4', '.webm', '.txt', '.xml', '.svg'}
PROTECTED = {'/admin': 200, '/admin/mobile/': 200, '/assets/admin.js': 200,
             '/assets/app.js': 200, '/assets/styles.css': 200,
             '/api/health': 200, '/api/session': 401, '/api/inquiries': 401, '/api/dashboard': 401}


class DeployError(RuntimeError):
    pass


def require(condition, code):
    if not condition:
        raise DeployError(code)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def safe_name(name):
    path = PurePosixPath(name)
    return (isinstance(name, str) and bool(re.fullmatch(r'[A-Za-z0-9_./-]+', name))
            and not path.is_absolute() and path.as_posix() == name
            and all(part and not part.startswith('.') for part in path.parts)
            and path.parts[0] not in {'admin', 'api', 'uploads'}
            and path.suffix.lower() in EXTENSIONS)


def unique_json(pairs):
    obj = {}
    for key, value in pairs:
        require(key not in obj, 'duplicate_json_key')
        obj[key] = value
    return obj


def load_json(path, limit=1000000):
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= limit, 'invalid_json_file')
    return json.loads(path.read_bytes(), object_pairs_hook=unique_json)


def atomic_json(path, value):
    require(not path.is_symlink(), 'unsafe_status_path')
    temp = path.with_name('.' + path.name + '-' + uuid.uuid4().hex)
    descriptor = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)
    if os.name != 'nt':
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def root_owned(path):
    for part in [path, *path.parents]:
        metadata = part.lstat()
        require(not stat.S_ISLNK(metadata.st_mode) and metadata.st_uid == 0
                and not metadata.st_mode & 0o022, 'path_not_root_controlled')


def read_archive(payload, allowed):
    require(isinstance(payload, bytes) and 0 < len(payload) <= MAX_ARCHIVE, 'archive_size')
    require(0 < len(allowed) <= 250 and all(safe_name(name) for name in allowed), 'invalid_allowlist')
    files, seen, total = {}, set(), 0
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode='r:') as archive:
            for member in archive:
                name = member.name.rstrip('/') if member.isdir() else member.name
                require(name not in seen and len(seen) < 500, 'duplicate_archive_member')
                seen.add(name)
                require(name == 'dist' or name.startswith('dist/'), 'archive_scope')
                relative = name.removeprefix('dist/')
                if member.isdir():
                    require(name == 'dist' or any(item.startswith(relative + '/') for item in allowed), 'unknown_archive_directory')
                    continue
                require(member.isfile() and not member.issparse() and not member.linkname,
                        'archive_special_file')
                require(not member.mode & 0o111 and not member.mode & 0o7000, 'archive_executable')
                require(safe_name(relative) and relative in allowed, 'archive_file_scope')
                require(0 < member.size <= MAX_FILE, 'archive_member_size')
                total += member.size
                require(total <= MAX_TOTAL, 'archive_total_size')
                stream = archive.extractfile(member)
                require(stream is not None, 'archive_missing_stream')
                files[relative] = stream.read(member.size + 1)
                require(len(files[relative]) == member.size, 'archive_truncated')
    except (tarfile.TarError, EOFError):
        raise DeployError('archive_invalid') from None
    require(set(files) == set(allowed), 'archive_missing_files')
    return files


class Page(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.ids, self.references = set(), []
        self.h1 = self.title = 0
        self.feed(text)
        self.close()

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if values.get('id'):
            require(values['id'] not in self.ids, 'html_duplicate_id')
            self.ids.add(values['id'])
        self.h1 += tag == 'h1'
        self.title += tag == 'title'
        require(tag != 'base', 'html_base_forbidden')
        for key in ('href', 'src', 'poster', 'data-image', 'data-video', 'data-poster'):
            if values.get(key):
                if tag == 'link' and key == 'href' and values.get('rel') == 'icon' and values[key].startswith('data:image/svg+xml,'):
                    # Existing pages use an embedded geometric brand favicon.
                    # Accept only inert SVG shapes with no references or events.
                    try:
                        svg = ET.fromstring(unquote(values[key].split(',', 1)[1]))
                        for element in svg.iter():
                            require(element.tag.removeprefix('{http://www.w3.org/2000/svg}') in {'svg', 'rect', 'path', 'circle'}, 'unsafe_embedded_icon')
                            require(set(element.attrib) <= {'viewBox', 'width', 'height', 'x', 'y', 'rx', 'ry', 'cx', 'cy', 'r', 'd', 'fill', 'stroke', 'stroke-width'}, 'unsafe_embedded_icon')
                            require(not any('url(' in value.lower() for value in element.attrib.values()), 'unsafe_embedded_icon')
                    except ET.ParseError:
                        raise DeployError('unsafe_embedded_icon') from None
                    continue
                self.references.append(values[key])
        if values.get('srcset'):
            self.references.extend(value.strip().split()[0] for value in values['srcset'].split(',') if value.strip())

    handle_startendtag = handle_starttag


def validate_links(files):
    pages = {}
    for name, data in files.items():
        if name.endswith('.html'):
            try:
                pages[name] = Page(data.decode('utf-8'))
            except UnicodeError:
                raise DeployError('html_not_utf8') from None
            require(pages[name].h1 == 1 and pages[name].title == 1, 'html_structure')
    for name, page in pages.items():
        references = page.references
        for value in references:
            require(not value.lower().startswith(('javascript:', 'vbscript:', 'file:', 'data:')), 'html_unsafe_reference')
            raw = urlsplit(value)
            require(not (raw.path.startswith('/') and '..' in unquote(raw.path).split('/')), 'link_traversal')
            target = urlsplit(urljoin(ORIGIN + '/' + name, value))
            if target.scheme in {'tel', 'mailto'}:
                continue
            require(target.scheme in {'https', 'http'}, 'link_unsupported_scheme')
            if target.netloc not in {'jiuyue.club', 'www.jiuyue.club'}:
                continue
            if target.path in PROTECTED:
                continue
            relative = unquote(target.path).lstrip('/')
            if not relative or relative.endswith('/'):
                relative += 'index.html'
            require(relative in files, 'link_target_missing')
            if target.fragment and relative in pages:
                require(unquote(target.fragment) in pages[relative].ids, 'link_fragment_missing')


def verify_release(folder, enforce_owner=True):
    require(folder.is_dir() and not folder.is_symlink(), 'release_not_directory')
    if enforce_owner:
        root_owned(folder)
    actual = set()
    for item in folder.rglob('*'):
        metadata = item.lstat()
        require(stat.S_ISDIR(metadata.st_mode) or stat.S_ISREG(metadata.st_mode), 'release_special_file')
        if enforce_owner:
            require(metadata.st_uid == 0 and not metadata.st_mode & 0o022, 'release_not_root_controlled')
        if stat.S_ISREG(metadata.st_mode):
            require(metadata.st_nlink == 1, 'release_hardlink')
            actual.add(item.relative_to(folder).as_posix())
    manifest = load_json(folder / 'release-manifest.json')
    require(manifest.get('repository') == REPOSITORY and re.fullmatch('[0-9a-f]{40}', manifest.get('commit', '')), 'release_identity')
    hashes = manifest.get('files')
    require(isinstance(hashes, dict) and 0 < len(hashes) <= 250
            and all(safe_name(name) and isinstance(digest, str) and re.fullmatch('[0-9a-f]{64}', digest) for name, digest in hashes.items()), 'release_manifest')
    # Extra upload/user files cause refusal; they are never discarded by copying.
    require(actual == set(hashes) | {'release-manifest.json'}, 'release_extra_or_missing_files')
    for name, digest in hashes.items():
        path = folder / name
        require(0 < path.stat().st_size <= MAX_FILE and sha(path.read_bytes()) == digest, 'release_hash_mismatch')
    return manifest


def write_release(folder, files, commit):
    require(not os.path.lexists(folder), 'release_already_exists')
    require(re.fullmatch('[0-9a-f]{40}', commit) and all(safe_name(name) for name in files), 'release_input')
    folder.mkdir(mode=0o755)
    for name, data in files.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        with path.open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(path, 0o644)
    atomic_json(folder / 'release-manifest.json', {'repository': REPOSITORY, 'commit': commit,
                'files': {name: sha(data) for name, data in files.items()}})
    os.chmod(folder / 'release-manifest.json', 0o644)
    # systemd deliberately keeps UMask=0077 for private state. Public release
    # directories need explicit traversal rights after creation, including every
    # intermediate parent made by mkdir(parents=True). Never chmod state or the
    # existing release parent. Finish children first and publish root last.
    directories = [item for item in folder.rglob('*') if item.is_dir()]
    for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        os.chmod(directory, 0o755)
    os.chmod(folder, 0o755)


def require_current(link, expected):
    require(link.is_symlink() and link.resolve(strict=True) == expected, 'release_changed')


def replace_link(link, target):
    require(link.is_symlink() and target.is_dir() and not target.is_symlink(), 'invalid_switch')
    temporary = link.with_name('.jiuyue-switch-' + uuid.uuid4().hex)
    try:
        temporary.symlink_to(target, target_is_directory=True)
        os.replace(temporary, link)
        descriptor = os.open(link.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if temporary.is_symlink():
            temporary.unlink()


def switch_verified(link, old, new, state, commit, verify):
    require_current(link, old)
    atomic_json(state / 'transaction.json', {'status': 'switching', 'old': str(old), 'new': str(new), 'commit': commit})
    try:
        replace_link(link, new)
        verify(new)
        require_current(link, new)
    except Exception:
        try:
            require_current(link, new)
            replace_link(link, old)
            verify(old)
            result = {'status': 'rolled_back', 'failed_commit': commit, 'at': int(time.time())}
        except Exception:
            result = {'status': 'rollback_needs_attention', 'failed_commit': commit, 'at': int(time.time())}
        atomic_json(state / 'status.json', result)
        atomic_json(state / 'transaction.json', result)
        raise DeployError(result['status']) from None
    result = {'status': 'deployed', 'commit': commit, 'at': int(time.time())}
    atomic_json(state / 'status.json', result)
    atomic_json(state / 'transaction.json', result)
    return result


def run_command(args, *, cwd=None, timeout=90, max_output=MAX_ARCHIVE):
    # Output to a bounded-on-read temporary file avoids unbounded captured stdout.
    import tempfile
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='never',
               GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
    with tempfile.TemporaryFile() as output:
        result = subprocess.run(args, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                stdout=output, stderr=subprocess.DEVNULL, timeout=timeout)
        require(result.returncode == 0, 'command_failed')
        require(output.tell() <= max_output, 'command_output_limit')
        output.seek(0)
        return output.read(max_output + 1)


def git(mirror, *args, max_output=1000000):
    return run_command(['git', '-c', 'core.hooksPath=/dev/null', '-c', 'protocol.file.allow=never',
                        '-c', 'protocol.ext.allow=never', '-C', str(mirror), *args], max_output=max_output)


def fetch_release(state, allowed, base_commit):
    mirror = state / 'repository.git'
    if not mirror.exists():
        run_command(['git', '-c', 'core.hooksPath=/dev/null', 'init', '--bare', str(mirror)])
    root_owned(mirror)
    git(mirror, 'fetch', '--quiet', '--depth=100', '--no-tags', REMOTE, 'refs/heads/main')
    commit = git(mirror, 'rev-parse', '--verify', 'FETCH_HEAD^{commit}').decode().strip()
    require(re.fullmatch('[0-9a-f]{40}', commit), 'invalid_remote_commit')
    # A rewritten branch or an unproven ancestry must not silently roll back
    # production. More than 100 unseen commits requires an explicit operator check.
    git(mirror, 'merge-base', '--is-ancestor', base_commit, commit)
    if commit == base_commit:
        return commit, None
    entries = git(mirror, 'ls-tree', '-r', '-l', '-z', commit, '--', 'dist')
    names, objects, total = set(), {}, 0
    for record in entries.split(b'\0'):
        if not record:
            continue
        fields, raw_name = record.split(b'\t', 1)
        mode, kind, _oid, raw_size = fields.split()
        name = raw_name.decode('utf-8', errors='strict')
        require(mode == b'100644' and kind == b'blob' and name.startswith('dist/'), 'git_tree_file_type')
        relative, size = name[5:], int(raw_size)
        require(relative in allowed and safe_name(relative) and 0 < size <= MAX_FILE, 'git_tree_scope')
        names.add(relative)
        objects[relative] = _oid.decode('ascii')
        total += size
        require(total <= MAX_TOTAL, 'git_tree_total_limit')
    require(names == allowed, 'git_tree_missing_files')
    payload = git(mirror, 'archive', '--format=tar', commit, 'dist', max_output=MAX_ARCHIVE)
    files = read_archive(payload, allowed)
    for name, data in files.items():
        # Attributes such as export-subst must not alter the committed bytes.
        object_id = hashlib.sha1(b'blob ' + str(len(data)).encode('ascii') + b'\0' + data).hexdigest()
        require(object_id == objects[name], 'archive_differs_from_git_blob')
    return commit, files


def request(route, local_address=None, commit=None):
    suffix = ('?jiuyue_release=' + commit) if commit else ''
    command = ['curl', '--silent', '--show-error', '--noproxy', '*', '--max-time', '15',
               '--max-filesize', str(MAX_FILE), '--proto', '=https', '--header', 'Accept-Encoding: identity',
               '--header', 'Cache-Control: no-cache', '--write-out', '\n%{http_code}']
    if local_address:
        command += ['--resolve', 'jiuyue.club:443:' + local_address]
    body = run_command(command + [ORIGIN + route + suffix], timeout=20, max_output=MAX_FILE + 10)
    content, status = body.rsplit(b'\n', 1)
    return int(status), content


def protected_baseline(local_address):
    result = {}
    for route, expected in PROTECTED.items():
        status, content = request(route, local_address)
        require(status == expected, 'protected_route_unhealthy')
        result[route] = {'status': status}
        if route.startswith('/assets/') or route.startswith('/admin'):
            result[route]['sha256'] = sha(content)
    return result


def verify_http(folder, config, protected):
    manifest = verify_release(folder)
    for local in [config['local_address']] + ([None] if config['verify_public'] else []):
        for name, expected in manifest['files'].items():
            route = '/' if name == 'index.html' else '/' + name
            status, content = request(route, local, manifest['commit'])
            require(status == 200 and sha(content) == expected, 'http_hash_mismatch')
    require(protected_baseline(config['local_address']) == protected, 'protected_route_changed')


def inspect(webroot, nginx_config):
    root_owned(webroot.parent)
    require(webroot.is_symlink(), 'existing_webroot_must_be_symlink')
    metadata = webroot.lstat()
    require(metadata.st_uid == 0, 'webroot_not_root_owned')
    current = webroot.resolve(strict=True)
    require(current.parent == webroot.parent, 'release_must_share_parent')
    manifest = verify_release(current)
    root_owned(nginx_config)
    require(nginx_config.is_file(), 'nginx_config_not_file')
    run_command(['nginx', '-t'], max_output=10000)
    return current, manifest, sha(nginx_config.read_bytes())


def load_config(path):
    root_owned(path)
    config = load_json(path)
    require(config.get('repository') == REPOSITORY and config.get('branch') == 'main', 'config_repository')
    require(isinstance(config.get('verify_public'), bool), 'config_http_mode')
    require(ipaddress.ip_address(config['local_address']).is_loopback, 'local_address_must_be_loopback')
    for key in ('webroot', 'state_dir', 'nginx_config'):
        require(Path(config[key]).is_absolute(), 'config_absolute_path')
    require(set(config['allowed_files']) and all(safe_name(name) for name in config['allowed_files']), 'config_allowlist')
    return config


def poll(config):
    import fcntl
    state, webroot, nginx = (Path(config[key]) for key in ('state_dir', 'webroot', 'nginx_config'))
    root_owned(state)
    lock_path = state / 'deploy.lock'
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    legacy_descriptor = os.open('/run/jiuyue-frontend-deploy.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'a') as lock, os.fdopen(legacy_descriptor, 'a') as shared_lock:
        for handle in (lock, shared_lock):
            metadata = os.fstat(handle.fileno())
            require(stat.S_ISREG(metadata.st_mode) and metadata.st_uid == 0 and metadata.st_nlink == 1
                    and not metadata.st_mode & 0o022, 'unsafe_deployment_lock')
        fcntl.flock(shared_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        old, manifest, nginx_hash = inspect(webroot, nginx)
        require(nginx_hash == config['nginx_sha256'], 'nginx_config_changed')
        require(set(manifest['files']) == set(config['allowed_files']), 'current_file_scope_changed')
        transaction_path = state / 'transaction.json'
        if transaction_path.exists():
            transaction = load_json(transaction_path)
            require(transaction.get('status') not in {'switching', 'rollback_needs_attention'}, 'interrupted_switch_needs_attention')
        commit, files = fetch_release(state, set(config['allowed_files']), manifest['commit'])
        if commit == manifest['commit']:
            return {'status': 'unchanged', 'commit': commit}
        if (state / 'status.json').exists():
            previous = load_json(state / 'status.json')
            require(previous.get('failed_commit') != commit, 'failed_commit_not_retried')
        validate_links(files)
        protected = protected_baseline(config['local_address'])
        new = webroot.parent / ('jiuyue-frontend-' + commit[:12] + '-' + uuid.uuid4().hex[:12])
        write_release(new, files, commit)
        verify_release(new)
        # Revalidate original release and configuration immediately before switch.
        observed, observed_manifest, observed_config = inspect(webroot, nginx)
        require(observed == old and observed_manifest == manifest and observed_config == nginx_hash, 'pre_switch_state_changed')
        return switch_verified(webroot, old, new, state, commit,
                               lambda folder: verify_http(folder, config, protected))


def initialize(args):
    webroot, nginx, state = Path(args.webroot), Path(args.nginx_config), Path(args.state_dir)
    require(all(path.is_absolute() for path in (webroot, nginx, state)), 'absolute_paths_required')
    require(not state.exists() and not state.is_symlink(), 'state_directory_already_exists')
    require(ipaddress.ip_address(args.local_address).is_loopback, 'local_address_must_be_loopback')
    old, manifest, config_hash = inspect(webroot, nginx)
    require(re.fullmatch('[0-9a-f]{40}', args.expected_commit) and manifest['commit'] == args.expected_commit, 'initial_commit_mismatch')
    require(state.parent.exists(), 'state_parent_missing')
    root_owned(state.parent)
    require(not state.is_relative_to(webroot.parent) and not webroot.parent.is_relative_to(state), 'state_must_be_separate')
    # Validate actual existing public files and backend routes before saving state.
    config = {'repository': REPOSITORY, 'branch': 'main', 'webroot': str(webroot),
              'state_dir': str(state), 'nginx_config': str(nginx), 'nginx_sha256': config_hash,
              'initial_commit': manifest['commit'], 'allowed_files': sorted(manifest['files']),
              'local_address': args.local_address, 'verify_public': not args.local_only}
    verify_http(old, config, protected_baseline(args.local_address))
    if args.dry_run:
        return {'status': 'preflight_passed', 'commit': manifest['commit'], 'files': len(manifest['files']), 'changed': False}
    state.mkdir(mode=0o700)
    atomic_json(state / 'config.json', config)
    atomic_json(state / 'status.json', {'status': 'initialized', 'commit': manifest['commit']})
    return {'status': 'initialized', 'commit': manifest['commit'], 'site_changed': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    init = commands.add_parser('init')
    init.add_argument('--webroot', required=True)
    init.add_argument('--nginx-config', required=True)
    init.add_argument('--state-dir', default='/var/lib/jiuyue-static-pull')
    init.add_argument('--expected-commit', required=True)
    init.add_argument('--local-address', default='127.0.0.1')
    init.add_argument('--local-only', action='store_true', help='Skip public route verification; local HTTPS remains mandatory')
    init.add_argument('--dry-run', action='store_true')
    once = commands.add_parser('once')
    once.add_argument('--config', required=True)
    args = parser.parse_args()
    try:
        require(sys.platform.startswith('linux') and os.geteuid() == 0, 'linux_root_required')
        result = initialize(args) if args.command == 'init' else poll(load_config(Path(args.config)))
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as error:
        code = str(error) if isinstance(error, DeployError) else type(error).__name__
        print(json.dumps({'status': 'blocked', 'reason': code}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
