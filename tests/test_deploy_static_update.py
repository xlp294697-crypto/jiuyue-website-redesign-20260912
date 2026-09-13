"""Safety boundaries for the narrowly scoped booking QR-code release."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

PATH = Path(__file__).resolve().parents[1] / 'scripts' / 'deploy_static_update.py'
if PATH.exists():
    SPEC = importlib.util.spec_from_file_location('deploy_static_update', PATH)
    update = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(update)
else:
    update = None

REPO = 'xlp294697-crypto/jiuyue-website-redesign-20260912'
BASE = '1fb585fc25835a7b9db65f0765bcef13fcf09d03'
TARGET = 'b' * 40
OLD = {'index.html': b'unchanged homepage', 'booking/index.html': b'old booking',
       'assets/production.css': b'old css', 'assets/booking.js': b'unchanged booking integration'}
NEW = {'booking/index.html': b'<html><img src="/assets/photos/wechat-contact.png"><script src="/assets/booking.js"></script></html>',
       'assets/production.css': b'.qr { max-width: 100%; }',
       'assets/photos/wechat-contact.png': b'\x89PNG\r\n\x1a\noriginal user image bytes'}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def make_manifest():
    return {'repository': REPO, 'base_commit': BASE, 'target_commit': TARGET,
            'files': {name: {'old_sha256': sha(OLD[name]) if name in OLD else None,
                             'new_sha256': sha(payload)} for name, payload in NEW.items()}}


def make_archive(files=None, manifest=None, extra=None):
    data = dict(NEW if files is None else files)
    data['incremental-manifest.json'] = json.dumps(make_manifest() if manifest is None else manifest).encode()
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w:gz') as archive:
        for name, payload in data.items():
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
        if extra:
            member, payload = extra
            archive.addfile(member, io.BytesIO(payload) if payload is not None else None)
    return output.getvalue()


def write_base(folder):
    folder.mkdir()
    for name, payload in OLD.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    manifest = {'repository': REPO, 'commit': BASE, 'files': {name: sha(payload) for name, payload in OLD.items()}}
    (folder / 'release-manifest.json').write_text(json.dumps(manifest), encoding='utf8')


class IncrementalReleaseTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(update, 'The incremental deploy implementation is missing')

    def test_accepts_only_the_three_authorized_changes_with_exact_image_bytes(self):
        files, manifest = update.read_archive(make_archive())
        self.assertEqual(files, NEW)
        self.assertEqual(manifest['base_commit'], BASE)
        self.assertIsNone(manifest['files']['assets/photos/wechat-contact.png']['old_sha256'])

    def test_rejects_extra_files_duplicates_traversal_and_links(self):
        for name, kind in [('api/private.json', None), ('../outside', None),
                           ('/root/outside', None), ('./booking/index.html', None),
                           ('assets\\photos\\wechat-contact.png', None),
                           ('booking/index.html', None), ('assets/link', tarfile.SYMTYPE),
                           ('assets/hard', tarfile.LNKTYPE)]:
            with self.subTest(name=name):
                member = tarfile.TarInfo(name)
                if kind is None:
                    member.size = 1
                else:
                    member.type = kind
                    member.linkname = '/etc/passwd'
                with self.assertRaises(ValueError):
                    update.read_archive(make_archive(extra=(member, b'x' if kind is None else None)))

    def test_rejects_wrong_repo_same_commit_corrupt_payload_and_missing_image(self):
        for key, value in [('repository', 'somewhere/old-project'), ('target_commit', BASE),
                           ('base_commit', 'invalid')]:
            manifest = make_manifest()
            manifest[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                update.read_archive(make_archive(manifest=manifest))
        files = dict(NEW)
        files['assets/production.css'] = b'corrupt bytes'
        with self.assertRaises(ValueError):
            update.read_archive(make_archive(files=files))
        del files['assets/photos/wechat-contact.png']
        with self.assertRaises(ValueError):
            update.read_archive(make_archive(files=files))

    def test_missing_old_digest_cannot_turn_an_existing_file_into_an_addition(self):
        manifest = make_manifest()
        manifest['files']['booking/index.html']['old_sha256'] = None
        with self.assertRaises(ValueError):
            update.read_archive(make_archive(manifest=manifest))

    def test_preparation_copies_unchanged_files_and_preserves_original_release(self):
        with tempfile.TemporaryDirectory() as temporary:
            base, new = Path(temporary) / 'old', Path(temporary) / 'new'
            write_base(base)
            before = {name: (base / name).read_bytes() for name in OLD}
            manifest = update.prepare_release(base, new, NEW, make_manifest())
            self.assertEqual({name: (base / name).read_bytes() for name in OLD}, before)
            self.assertFalse((base / 'assets/photos/wechat-contact.png').exists())
            self.assertEqual((new / 'index.html').read_bytes(), b'unchanged homepage')
            self.assertEqual((new / 'assets/booking.js').read_bytes(), b'unchanged booking integration')
            for name, payload in NEW.items():
                self.assertEqual((new / name).read_bytes(), payload)
            self.assertEqual(manifest['commit'], TARGET)
            self.assertEqual(manifest['files']['index.html'], sha(b'unchanged homepage'))
            self.assertEqual(manifest['files']['assets/photos/wechat-contact.png'], sha(NEW['assets/photos/wechat-contact.png']))
            update.verify_release(new, TARGET)

    def test_base_file_or_manifest_drift_is_rejected_before_copying(self):
        for mutation in ['existing-file', 'unlisted-file', 'wrong-base', 'old-hash', 'image-already-exists']:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                base, new = Path(temporary) / 'old', Path(temporary) / 'new'
                write_base(base)
                manifest = make_manifest()
                if mutation == 'existing-file':
                    (base / 'index.html').write_bytes(b'unexpected change')
                elif mutation == 'unlisted-file':
                    (base / 'private.json').write_bytes(b'not a public release file')
                elif mutation == 'wrong-base':
                    manifest['base_commit'] = 'c' * 40
                elif mutation == 'old-hash':
                    manifest['files']['booking/index.html']['old_sha256'] = '0' * 64
                else:
                    (base / 'assets/photos').mkdir()
                    (base / 'assets/photos/wechat-contact.png').write_bytes(b'old unexpected image')
                with self.assertRaises(ValueError):
                    update.prepare_release(base, new, NEW, manifest)
                self.assertFalse(new.exists())

    def test_existing_destination_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            base, new = Path(temporary) / 'old', Path(temporary) / 'new'
            write_base(base)
            new.mkdir()
            (new / 'keep.txt').write_bytes(b'preserve this directory')
            with self.assertRaises(ValueError):
                update.prepare_release(base, new, NEW, make_manifest())
            self.assertEqual((new / 'keep.txt').read_bytes(), b'preserve this directory')

    def test_base_symlink_is_never_followed(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary) / 'old'
            write_base(base)
            extra = base / 'unlisted-link'
            try:
                extra.symlink_to(base / 'index.html')
            except OSError:
                self.skipTest('Local OS does not permit symbolic links')
            with self.assertRaises(ValueError):
                update.verify_release(base, BASE)


if __name__ == '__main__':
    unittest.main()
