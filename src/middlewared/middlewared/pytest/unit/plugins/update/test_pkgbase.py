import os
import pathlib
import re
import subprocess
import types

import pytest

from middlewared.plugins.update_ import pkgbase


# src/freenas is what the freenas-files package installs at the root of the image.
SHIPPED_ROOT = pathlib.Path(__file__).resolve().parents[6] / 'freenas'


def read_conf(directory):
    with open(os.path.join(directory, 'bsdnas-update.conf')) as fh:
        return fh.read()


def test__write_repo_conf__checks_signatures_against_shipped_fingerprints(tmp_path):
    pkgbase.write_repo_conf(str(tmp_path), {
        'base': 'https://updates.example.com/pkgbase/FreeBSD:15:amd64/latest',
        'ports': {'url': 'https://updates.example.com/ports/FreeBSD:15:amd64/latest'},
    })
    conf = read_conf(str(tmp_path))

    for name in ('base', 'ports'):
        block = re.search(r'bsdnas-%s: \{(.*?)\}' % name, conf, re.S).group(1)
        assert 'enabled: yes' in block
        assert 'signature_type: "fingerprints"' in block
        assert 'fingerprints: "%s"' % pkgbase.PKG_FINGERPRINTS in block
    assert 'signature_type: none' not in conf

    # Nothing configured on the machine takes part in an update.
    for name in ('FreeBSD', 'local', 'pcbsd-major', 'pcbsd-minor'):
        assert '%s: { enabled: no }' % name in conf


@pytest.mark.parametrize('url', [
    'http://updates.example.com/pkgbase',
    'ftp://updates.example.com/pkgbase',
    'file:///var/tmp/pkgbase',
    None,
])
def test__write_repo_conf__still_requires_https(tmp_path, url):
    with pytest.raises(pkgbase.UpdateError, match='https'):
        pkgbase.write_repo_conf(str(tmp_path), {'base': url})
    assert not os.path.exists(os.path.join(str(tmp_path), 'bsdnas-update.conf'))


@pytest.mark.parametrize('url', [
    # The finding: a quote and a line break turned the check off and added a repository.
    'https://u.example.com/b",\n  signature_type: "none"\n}\nevil: {\n  url: "https://evil.example.com',
    'https://u.example.com/b"',
    'https://u.example.com/b\\',
    'https://u.example.com/{b}',
    'https://u.example.com/b c',
    'https://u.example.com/b\n',
    'https://u.example.com/b\t',
    'https://u.example.com/b\x00',
    'https://u.example.com/b\x7f',
    'https://',
])
def test__write_repo_conf__refuses_a_url_that_would_escape_the_configuration(tmp_path, url):
    with pytest.raises(pkgbase.UpdateError, match='characters'):
        pkgbase.write_repo_conf(str(tmp_path), {'base': url})
    assert not os.path.exists(os.path.join(str(tmp_path), 'bsdnas-update.conf'))


@pytest.mark.parametrize('name', [
    'base: { url: "https://evil" }\nx',
    'Base',
    '-base',
    '_base',
    'ba se',
    'base\n',
    'ba"se',
    '',
    1,
])
def test__write_repo_conf__refuses_a_strange_repository_name(tmp_path, name):
    with pytest.raises(pkgbase.UpdateError, match='repository name'):
        pkgbase.write_repo_conf(str(tmp_path), {name: 'https://u.example.com/b'})
    assert not os.path.exists(os.path.join(str(tmp_path), 'bsdnas-update.conf'))


@pytest.mark.parametrize('name,url', [
    ('base', 'https://updates.example.com/pkgbase/FreeBSD:15:amd64/latest'),
    ('ports_2', 'https://updates.example.com:8443/ports/FreeBSD:15:amd64/2026-08-17_10h12m47s'),
    ('0-x', 'https://[2001:db8::1]/pkgbase/latest?x=1&y=%20'),
])
def test__write_repo_conf__takes_ordinary_names_and_urls(tmp_path, name, url):
    pkgbase.write_repo_conf(str(tmp_path), {name: url})
    assert 'url: "%s",' % url in read_conf(str(tmp_path))


def test__fingerprints_ship_in_the_image():
    if not SHIPPED_ROOT.is_dir():
        pytest.skip('not run from a source tree')
    trusted = SHIPPED_ROOT / pkgbase.PKG_FINGERPRINTS.lstrip('/') / 'trusted'
    files = sorted(trusted.iterdir())
    assert files, 'no trusted fingerprint ships in the image'
    for path in files:
        # pkg's own format; anything else in trusted/ makes pkg complain.
        assert re.fullmatch(r'function: sha256\nfingerprint: "[0-9a-f]{64}"\n', path.read_text()), path


class FakePkg:
    """Stands in for pkgbase._run: answers `pkg update` and `pkg rquery -r`."""

    def __init__(self, catalogues, update_output='All repositories are up to date.\n'):
        self.catalogues = catalogues
        self.update_output = update_output
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        pkg_args = args[args.index('pkg') + 3:]
        if pkg_args[0] == 'update':
            return types.SimpleNamespace(returncode=0, stdout=self.update_output)
        assert pkg_args[:2] == ['rquery', '-r']
        # A merged stderr would let a "pkg: ..." complaint pass for a package.
        assert kwargs.get('stderr') == subprocess.PIPE
        rows = self.catalogues.get(pkg_args[2])
        if rows is None:
            return types.SimpleNamespace(returncode=1, stdout='')
        return types.SimpleNamespace(returncode=0, stdout=rows)


REPOS = {'base': 'https://u.example.com/b', 'ports': 'https://u.example.com/p'}


def stored(root, name):
    path = root / 'var' / 'db' / 'pkg' / 'repos' / name
    path.mkdir(parents=True)
    (path / 'db').write_text('the catalogue of the previous update')
    return path


def test__update_catalogue__returns_what_every_repository_holds(tmp_path, monkeypatch):
    fake = FakePkg({
        'bsdnas-base': 'FreeBSD-runtime 15.snap2\n',
        'bsdnas-ports': 'py311-middlewared 0.2\n',
    })
    monkeypatch.setattr(pkgbase, '_run', fake)

    available = pkgbase.update_catalogue(str(tmp_path), '/repos', REPOS)

    assert available == {'FreeBSD-runtime': '15.snap2', 'py311-middlewared': '0.2'}


def test__update_catalogue__drops_the_previous_catalogues_first(tmp_path, monkeypatch):
    # pkg keeps the catalogue it had when it refuses a new one, and exits 0.
    old = [stored(tmp_path, 'bsdnas-base'), stored(tmp_path, 'bsdnas-ports')]
    other = stored(tmp_path, 'FreeBSD')
    seen = []

    def run(args, **kwargs):
        if 'update' in args:
            seen.extend(path.exists() for path in old)
        return FakePkg({'bsdnas-base': 'a 1\n', 'bsdnas-ports': 'b 1\n'})(args, **kwargs)

    monkeypatch.setattr(pkgbase, '_run', run)
    pkgbase.update_catalogue(str(tmp_path), '/repos', REPOS)

    assert seen == [False, False]
    assert other.exists(), 'only the repositories of the update are touched'


@pytest.mark.parametrize('ports', [None, ''])
def test__update_catalogue__one_refused_repository_stops_the_update(tmp_path, monkeypatch, ports):
    # None: no catalogue at all, rquery fails. '': a catalogue with nothing in it.
    catalogues = {'bsdnas-base': 'FreeBSD-runtime 15.snap2\n'}
    if ports is not None:
        catalogues['bsdnas-ports'] = ports
    monkeypatch.setattr(pkgbase, '_run', FakePkg(
        catalogues, update_output='pkg: rsa signature verification failure\n'
    ))

    with pytest.raises(pkgbase.UpdateError) as e:
        pkgbase.update_catalogue(str(tmp_path), '/repos', REPOS)

    assert 'bsdnas-ports' in str(e.value)
    assert 'rsa signature verification failure' in str(e.value)


def test__update_catalogue__drops_the_catalogues_before_every_attempt(tmp_path, monkeypatch):
    # Attempt 1 stores a good base catalogue and fails on ports; attempt 2
    # would refuse base and keep attempt 1's copy. It must not find one.
    base = tmp_path / 'var' / 'db' / 'pkg' / 'repos' / 'bsdnas-base'
    seen = []
    answers = FakePkg({'bsdnas-base': 'a 1\n', 'bsdnas-ports': 'b 1\n'})

    def run(args, **kwargs):
        if 'update' in args:
            seen.append(base.exists())
            if len(seen) == 1:
                base.mkdir(parents=True)
                (base / 'db').write_text('stored by the failed attempt')
                return types.SimpleNamespace(returncode=1, stdout='bsdnas-ports: fetch failed')
        return answers(args, **kwargs)

    monkeypatch.setattr(pkgbase, '_run', run)
    monkeypatch.setattr(pkgbase.time, 'sleep', lambda seconds: None)
    pkgbase.update_catalogue(str(tmp_path), '/repos', REPOS)

    assert seen == [False, False]


def test__update_catalogue__a_catalogue_that_cannot_be_removed_stops_the_update(tmp_path, monkeypatch):
    stored(tmp_path, 'bsdnas-base')
    fake = FakePkg({'bsdnas-base': 'a 1\n', 'bsdnas-ports': 'b 1\n'})
    monkeypatch.setattr(pkgbase, '_run', fake)

    def rmtree(path, *args, **kwargs):
        raise PermissionError(1, 'Operation not permitted', path)

    monkeypatch.setattr(pkgbase.shutil, 'rmtree', rmtree)

    with pytest.raises(pkgbase.UpdateError, match='bsdnas-base.*Operation not permitted'):
        pkgbase.update_catalogue(str(tmp_path), '/repos', REPOS)
    assert fake.calls == [], 'pkg must not run on top of the old catalogue'


def test__update_catalogue__a_catalogue_still_there_after_removal_stops_the_update(tmp_path, monkeypatch):
    stored(tmp_path, 'bsdnas-ports')
    fake = FakePkg({'bsdnas-base': 'a 1\n', 'bsdnas-ports': 'b 1\n'})
    monkeypatch.setattr(pkgbase, '_run', fake)
    monkeypatch.setattr(pkgbase.shutil, 'rmtree', lambda path, *args, **kwargs: None)

    with pytest.raises(pkgbase.UpdateError, match='bsdnas-ports.*still there'):
        pkgbase.update_catalogue(str(tmp_path), '/repos', REPOS)
    assert fake.calls == []


def test__update_catalogue__a_link_in_place_of_the_catalogue_is_removed_not_followed(tmp_path, monkeypatch):
    target = tmp_path / 'elsewhere'
    target.mkdir()
    (target / 'db').write_text('keep')
    repos = tmp_path / 'var' / 'db' / 'pkg' / 'repos'
    repos.mkdir(parents=True)
    (repos / 'bsdnas-base').symlink_to(target)
    monkeypatch.setattr(pkgbase, '_run', FakePkg({'bsdnas-base': 'a 1\n', 'bsdnas-ports': 'b 1\n'}))

    pkgbase.update_catalogue(str(tmp_path), '/repos', REPOS)

    assert not os.path.lexists(str(repos / 'bsdnas-base'))
    assert (target / 'db').read_text() == 'keep'


def test__update_catalogue__stays_inside_the_root(tmp_path, monkeypatch):
    outside = tmp_path / 'outside'
    victim = outside / 'repos' / 'bsdnas-base'
    victim.mkdir(parents=True)
    root = tmp_path / 'root'
    (root / 'var' / 'db').mkdir(parents=True)
    (root / 'var' / 'db' / 'pkg').symlink_to(outside)
    monkeypatch.setattr(pkgbase, '_run', FakePkg({}))

    with pytest.raises(pkgbase.UpdateError, match='leads outside the new environment'):
        pkgbase.update_catalogue(str(root), '/repos', REPOS)
    assert victim.exists()
