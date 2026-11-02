# -*- coding=utf-8 -*-
"""Updating the system with pkg(8) into a fresh boot environment.

This is the whole mechanism of an update, with nothing of the middleware in
it: the module speaks to pkg, to beadm and to the update server, reports
progress through a callback and raises UpdateError when it cannot go on. The
middleware plugins wrap it; a command line tool can drive the very same code
when there is no middleware to ask, which is what makes a broken system
recoverable by hand.

Why a boot environment and not the running system. An update writes a whole
new base and a whole new set of our own packages. Doing that in place means a
window in which the system is half one version and half another, and a failure
inside that window leaves nothing to go back to. A boot environment is a ZFS
clone: it costs the blocks that change and nothing else, the running system is
not touched at all, and going back is choosing the previous environment at the
next boot.

The three things that are easy to get wrong, all found the hard way:

* /etc, /var and /mnt in an installed system are tmpfs, poured at every boot
  from the template in /conf/base by rc.initdiskless. Everything pkg writes
  under them lives until the first reboot and not a second longer — including
  pkg's own database in /var/db/pkg. An update that does not copy them into
  the template comes up looking healthy and having forgotten which packages it
  has.

* The repository description belongs outside the environment being built. Put
  it inside and it becomes part of the installed system, where it has no
  business, and the next phase overwrites it anyway.

* An empty or unreachable repository must stop the update. pkg is content to
  do nothing and report success, and an environment that received nothing
  boots into the old system while claiming to be the new one.

* A catalogue pkg refuses to trust does not fail `pkg update`. The
  repositories are signed and checked (signature_type: fingerprints, see
  write_repo_conf()), and when the check fails pkg says so, exits 0 and keeps
  the catalogue it had before -- so a refused repository looks like one with
  nothing new in it. update_catalogue() throws the old catalogue away first
  and then insists that every repository came back with packages.
"""
import contextlib
import datetime
import json
import os
import re
import shutil
import subprocess
import tempfile
import time

from urllib.error import HTTPError
from urllib.request import urlopen

# Where the public half of our signing key ships. The manifest is checked
# against this key and not against whatever keyring happens to be around: the
# point of the signature is to trust the key, not the server.
SIGNING_KEY = '/usr/local/share/licenses/BSDnas/BSDnas-signing-key.asc'

# Fingerprints of the keys the package repositories are signed with, in pkg's
# own layout: trusted/ holds the keys a catalogue may be signed by, revoked/
# the ones it must not be. Like the key above it ships in the image, so the
# repository cannot vouch for itself. Replacing the key is shipping its
# fingerprint in trusted/ first, signing with it next, and moving the old one
# to revoked/ last. The path is read by pkg inside the environment being
# built, which is a clone of this system and carries the same directory.
PKG_FINGERPRINTS = '/usr/local/share/keys/bsdnas-pkg'

# What a repository name and url from the manifest may look like. Both are
# written into pkg's configuration, which is UCL: a quote, a backslash, a
# brace or a line break in either would let the manifest add settings of its
# own -- a signature_type of its choosing, another repository. The manifest
# is signed, but the configuration is not the place to rely on that.
REPO_NAME_RE = re.compile(r'[a-z0-9][a-z0-9_-]*')
REPO_URL_RE = re.compile(r'https://[^"\\{}\s\x00-\x1f\x7f]+')

# The template rc.initdiskless pours /etc and /var from on every boot.
CONF_BASE = 'conf/base'

# Directories under the template that have to match what pkg just installed.
# /etc holds configuration the packages bring, /var/db/pkg holds the record of
# which packages those are.
TEMPLATE_PATHS = ('etc', 'var/db/pkg')

BEADM = '/usr/local/sbin/beadm'

# Names pkg prints a fetch or an install step with: "[12/310] Fetching ...".
STEP_RE = re.compile(r'^\[(\d+)/(\d+)\]\s+(.*)$')


# Fetching the manifest: how many times, and the pause that grows between
# attempts. pkg gets its own retry count for packages.
FETCH_ATTEMPTS = 4
FETCH_BACKOFF = 3
PKG_FETCH_RETRY = 6
CATALOGUE_ATTEMPTS = 3


class UpdateError(Exception):
    """Something went wrong and the update must not continue."""


class ManifestNotPublished(UpdateError):
    """The train publishes no manifest at all.

    Kept apart from every other failure on purpose. A train without a
    manifest has simply not moved to package updates, and the caller may go
    the old way. A manifest that is there but cannot be fetched whole, or does
    not verify, is something else entirely, and must stop the update: if a
    broken manifest meant "use the older path", breaking the manifest would
    be how to choose the weaker check.
    """


def _run(args, **kwargs):
    kwargs.setdefault('stdout', subprocess.PIPE)
    kwargs.setdefault('stderr', subprocess.STDOUT)
    kwargs.setdefault('encoding', 'utf-8')
    kwargs.setdefault('errors', 'ignore')
    return subprocess.run(args, **kwargs)


def _check(args, what, **kwargs):
    p = _run(args, **kwargs)
    if p.returncode != 0:
        raise UpdateError('{0} failed: {1}'.format(what, (p.stdout or '').strip()))
    return p.stdout or ''


# --------------------------------------------------------------------------
# The train manifest
# --------------------------------------------------------------------------

def fetch_manifest(base_url, key=SIGNING_KEY, timeout=30):
    """Fetch a train manifest and refuse to return it unsigned.

    TLS says we talked to the right host. It says nothing about what the host
    was handed to serve, and the update server is the one machine in the chain
    we would least like to have to trust. So the manifest carries a detached
    signature made by a key that lives nowhere near it, and this is the first
    thing an update does.
    """
    base_url = base_url.rstrip('/')
    if not os.path.exists(key):
        raise UpdateError('No signing key at {0}: cannot verify an update'.format(key))

    def get(name):
        # A dropped connection is retried; an answer is not. The first update
        # run on the physical test machine (2026-10-06) died on a single TLS
        # handshake timeout while one connection in five to the update server
        # was failing, minutes after the same files had been fetched fine.
        # Retrying changes nothing about what is accepted: whatever arrives
        # is still checked against the signature below.
        url = '{0}/{1}'.format(base_url, name)
        for attempt in range(FETCH_ATTEMPTS):
            try:
                with contextlib.closing(urlopen(url, timeout=timeout)) as r:
                    return r.read()
            except HTTPError as e:
                # Only the manifest itself being absent means "not published".
                # A manifest whose signature is missing is a broken publication.
                if e.code == 404 and name == 'manifest.json':
                    raise ManifestNotPublished('No manifest at {0}'.format(base_url))
                if e.code < 500 or attempt == FETCH_ATTEMPTS - 1:
                    raise UpdateError('Cannot fetch {0}: {1}'.format(url, e))
            except Exception as e:
                if attempt == FETCH_ATTEMPTS - 1:
                    raise UpdateError('Cannot fetch {0} after {1} attempts: {2}'.format(
                        url, FETCH_ATTEMPTS, e))
            time.sleep(FETCH_BACKOFF * (attempt + 1))

    body = get('manifest.json')
    signature = get('manifest.json.asc')

    tmp = tempfile.mkdtemp(prefix='bsdnas-update-')
    try:
        manifest_path = os.path.join(tmp, 'manifest.json')
        signature_path = manifest_path + '.asc'
        with open(manifest_path, 'wb') as fh:
            fh.write(body)
        with open(signature_path, 'wb') as fh:
            fh.write(signature)

        # A keyring of our own, thrown away with the directory: the check has
        # to be against the key we shipped and no other.
        home = os.path.join(tmp, 'gnupg')
        os.mkdir(home, 0o700)
        env = dict(os.environ, GNUPGHOME=home)
        _check(['gpg', '--batch', '--quiet', '--import', key], 'importing the signing key', env=env)
        p = _run(['gpg', '--batch', '--quiet', '--verify', signature_path, manifest_path], env=env)
        if p.returncode != 0:
            raise UpdateError(
                'The signature of {0}/manifest.json does not check out, refusing to '
                'trust it: {1}'.format(base_url, (p.stdout or '').strip())
            )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    try:
        manifest = json.loads(body.decode('utf-8'))
    except ValueError as e:
        raise UpdateError('The manifest is signed but unreadable: {0}'.format(e))

    for field in ('version', 'train'):
        if not manifest.get(field):
            raise UpdateError('The manifest has no {0}'.format(field))
    if not manifest.get('repos'):
        raise UpdateError(
            'The manifest of train {0} names no package repositories, so there is '
            'nothing to update from'.format(manifest['train'])
        )
    return manifest


# --------------------------------------------------------------------------
# pkg
# --------------------------------------------------------------------------

def write_repo_conf(directory, repos):
    """Describe the repositories of an update, outside the system being built.

    Everything else is switched off by name: an update takes what the signed
    manifest named and nothing that happens to be configured on the machine.

    The signed manifest says WHICH repository to take packages from; the
    signature on the repository's catalogue says WHAT it holds. The build signs
    the catalogue (core-build, tools/pkg-repo-sign.sh) and pkg checks it with
    signature_type: fingerprints against PKG_FINGERPRINTS from the image: the
    certificate travels in the catalogue, and pkg takes it only if its SHA256
    is in trusted/ and not in revoked/. The catalogue in turn carries the
    checksum of every package, which pkg checks before installing one.

    https stays required as a second layer. It costs nothing, and it keeps a
    repository off plain http even if the signature check were ever switched
    off by mistake.

    Systems released before the repositories were signed have signature_type:
    none written into this function; they ignore the signature, and a signed
    catalogue updates them as before.
    """
    os.makedirs(directory, exist_ok=True)
    conf = []
    for name, repo in sorted(repos.items()):
        url = repo['url'] if isinstance(repo, dict) else repo
        if not isinstance(name, str) or not REPO_NAME_RE.fullmatch(name):
            raise UpdateError(
                'The manifest names a repository {0!r}: refusing it, a repository name '
                'is lower case letters, digits, "-" and "_".'.format(name)
            )
        if not isinstance(url, str) or not url.startswith('https://'):
            raise UpdateError(
                'Repository {0} is published over {1!r}. Refusing to install from '
                'it: an update must arrive over https.'.format(name, url)
            )
        if not REPO_URL_RE.fullmatch(url):
            raise UpdateError(
                'Repository {0} has the url {1!r}, with characters that do not belong '
                'in one (quotes, backslashes, braces, spaces or control characters). '
                'Refusing to install from it.'.format(name, url)
            )
        conf.append((name, url))

    with open(os.path.join(directory, 'bsdnas-update.conf'), 'w') as fh:
        for name in ('FreeBSD', 'local', 'pcbsd-major', 'pcbsd-minor'):
            fh.write('%s: { enabled: no }\n' % name)
        for name, url in conf:
            fh.write(
                'bsdnas-%s: {\n'
                '  url: "%s",\n'
                '  enabled: yes,\n'
                '  signature_type: "fingerprints",\n'
                '  fingerprints: "%s"\n'
                '}\n' % (name, url, PKG_FINGERPRINTS)
            )
    return directory


def _pkg(root, repos_dir, args):
    """pkg, chrooted into the environment being built.

    -c and not -r. With -r pkg puts the files under the root but runs the
    packages' scripts in the running system, and our own packages' scripts
    use absolute paths: on 2026-10-06 the post-install of freenas-files,
    run that way during an update, moved the RUNNING system's configuration
    database aside, generated a blank one in its place with the old
    migrations, rewrote its factory-v1.db and put the database back -- and
    the running middleware, caught between, answered 500 to everything until
    restarted. With -c everything happens inside the new environment,
    scripts included, against its own /data and its own, newer, migrate.

    `repos_dir` is therefore a path INSIDE the chroot; see prepared_root().
    FETCH_RETRY is pkg's own retry of a failed download (default 3), raised
    for the same unreliable networks the manifest fetch retries for.
    """
    return ['env', 'ASSUME_ALWAYS_YES=yes', 'REPOS_DIR=' + repos_dir,
            'FETCH_RETRY={0}'.format(PKG_FETCH_RETRY),
            'pkg', '-c', root] + list(args)


def _inside(root, path):
    """Refuse a path that, followed through symlinks, leaves the root."""
    real_root = os.path.realpath(root)
    real = os.path.realpath(path)
    if real != real_root and not real.startswith(real_root + os.sep):
        raise UpdateError('{0} leads outside the new environment, to {1}: '
                          'refusing to write there'.format(path, real))


@contextlib.contextmanager
def prepared_root(root, repos):
    """What pkg needs inside the chroot, and nothing left behind after it.

    /dev for the packages' scripts and for pkg itself, a resolv.conf so the
    repositories resolve (the environment's own /etc is the bare one from the
    image: at boot /etc is poured from the template, and this is not booted),
    and the repository description written inside the root. Yields the path
    of that description as the chroot sees it.
    """
    dev = os.path.join(root, 'dev')
    resolv = os.path.join(root, 'etc', 'resolv.conf')
    saved_resolv = resolv + '.bsdnas-update'
    # Everything written here has to land inside the new environment, and a
    # path joined onto the root does not guarantee that: in the environment
    # /tmp is an ABSOLUTE symlink to /var/tmp, so <root>/tmp resolves to the
    # running system's /var/tmp from out here, and to the environment's own
    # from inside the chroot -- the repository description written through it
    # was where pkg never looked. So the description goes into a directory at
    # the top of the root, and every path is checked to really be inside it.
    for path in (dev, os.path.dirname(resolv)):
        _inside(root, path)
    repos_host = tempfile.mkdtemp(prefix='.bsdnas-update-repos-', dir=root)
    devfs = False
    had_resolv = os.path.lexists(resolv)
    try:
        _inside(root, repos_host)
        write_repo_conf(repos_host, repos)
        _check(['mount', '-t', 'devfs', 'devfs', dev], 'mounting devfs in the new environment')
        devfs = True
        if had_resolv:
            os.rename(resolv, saved_resolv)
        shutil.copyfile('/etc/resolv.conf', resolv)
        yield '/' + os.path.relpath(repos_host, root)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(resolv)
        if had_resolv:
            with contextlib.suppress(FileNotFoundError):
                os.rename(saved_resolv, resolv)
        if devfs:
            _run(['umount', '-f', dev])
        shutil.rmtree(repos_host, ignore_errors=True)


def _versions(output):
    out = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            out[parts[0]] = parts[1]
    return out


def update_catalogue(root, repos_dir, repos):
    """Refresh the catalogues and insist that each of them holds something.

    pkg treats an unreachable repository as a repository with no packages and
    exits happily. Taken at face value that turns into an update that installs
    nothing and reports success, so the emptiness is an error here.

    The same goes for a catalogue pkg refuses to trust -- unsigned, signed by
    a key that is not in trusted/ or is in revoked/, altered after signing.
    pkg 2.7.5 prints why, exits 0 and carries on with the catalogue it already
    had, which in the new environment is the one the template brought over
    from the previous update. Measured, not assumed: a refused catalogue left
    `pkg update -f` at exit 0 and `pkg rquery` answering from the old one. So
    the stored catalogues of the update's repositories are removed before the
    refresh, and afterwards every repository has to have come back with
    packages of its own -- one refused repository among good ones is not
    hidden by the others either.
    """
    names = ['bsdnas-%s' % name for name in sorted(repos)]

    def drop_stored():
        for name in names:
            stored = os.path.join(root, 'var', 'db', 'pkg', 'repos', name)
            _inside(root, stored)
            # Only "not there" is fine. A catalogue that cannot be removed -- an
            # immutable flag, a read-only dataset -- would survive the refresh and
            # bring back exactly the silent fallback this is here to prevent.
            try:
                if os.path.islink(stored):
                    os.unlink(stored)
                else:
                    shutil.rmtree(stored)
            except FileNotFoundError:
                pass
            except OSError as e:
                raise UpdateError('Cannot remove the previous catalogue of {0} ({1}): {2}. '
                                  'Refusing to continue, pkg would fall back on it.'.format(name, stored, e))
            if os.path.lexists(stored):
                raise UpdateError('The previous catalogue of {0} is still there after removing it '
                                  '({1}). Refusing to continue, pkg would fall back on it.'.format(name, stored))

    # The whole refresh is retried, not just single files: pkg's FETCH_RETRY
    # does not cover every failure, and on 2026-10-06 a run on the test
    # machine stopped on "meta.conf: Timeout was reached" followed by "Error
    # updating repositories!" while the server was answering eleven requests
    # in twelve. Refreshing a catalogue is safe to repeat.
    #
    # The stored catalogues go before every attempt, not only the first: an
    # attempt that fails on one repository may already have stored another,
    # and if the next attempt refuses that one, pkg would fall back on what
    # the failed attempt left behind.
    for attempt in range(CATALOGUE_ATTEMPTS):
        drop_stored()
        try:
            refreshed = _check(_pkg(root, repos_dir, ['update', '-f']), 'updating the package catalogue')
            break
        except UpdateError:
            if attempt == CATALOGUE_ATTEMPTS - 1:
                raise
            time.sleep(FETCH_BACKOFF * 5 * (attempt + 1))

    available = {}
    for name in names:
        # Without a catalogue rquery fails rather than printing nothing; both
        # mean the same here. Its complaints are kept apart from its answer:
        # a stray "pkg: ..." line read as a package would make an empty
        # repository look like one with something in it.
        p = _run(_pkg(root, repos_dir, ['rquery', '-r', name, '%n %v']), stderr=subprocess.PIPE)
        versions = _versions(p.stdout or '') if p.returncode == 0 else {}
        if not versions:
            raise UpdateError(
                'Repository {0} came back with no packages: it is unreachable or empty, '
                'or its catalogue was refused because the signature does not check out. '
                'Refusing to continue: an update that installs nothing would still look '
                'like one. pkg said: {1}'.format(name, refreshed.strip())
            )
        available.update(versions)
    return available


def pending_changes(root, repos_dir):
    """What an update would do, as the API describes it.

    Worked out by comparing the two lists of versions rather than by reading
    pkg's own report of its plans: the lists are what they are, while the
    report is prose and changes shape between releases of pkg.
    """
    installed = _versions(_check(_pkg(root, repos_dir, ['query', '%n %v']),
                                 'reading the installed packages'))
    available = _versions(_check(_pkg(root, repos_dir, ['rquery', '%n %v']),
                                 'reading the package catalogue'))

    # Only what is installed. The repositories hold more than the image is made
    # of — every -dbg companion, the sources, the compiler — and an update must
    # not drag any of it in: listing them as pending would both lie about the
    # size of the update and, if acted on, grow the system with every one.
    # Packages that genuinely arrive as new dependencies pkg pulls in by
    # itself, and reports while it works.
    changes = []
    for name in sorted(installed):
        new = available.get(name)
        if new is not None and new != installed[name]:
            changes.append({
                'operation': 'upgrade',
                'old': {'name': name, 'version': installed[name]},
                'new': {'name': name, 'version': new},
            })
    return changes


def install(root, repos_dir, progress=None, packages=None):
    """Bring the packages in `root` up to what the repositories hold.

    `packages` is for a system whose base pkg knows nothing about — one that
    came from an unpacked image rather than from packages. There the base has
    to be installed rather than upgraded, by an explicit list, because the
    set-* metapackages drag in the sources and the compiler.
    """
    if packages:
        args = ['install', '-y'] + list(packages)
        what = 'installing the base'
    else:
        args = ['upgrade', '-y']
        what = 'upgrading the packages'

    p = subprocess.Popen(_pkg(root, repos_dir, args), stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, encoding='utf-8', errors='ignore')
    tail = []
    for line in p.stdout:
        line = line.rstrip('\n')
        tail.append(line)
        del tail[:-40]
        if progress is None:
            continue
        m = STEP_RE.match(line.strip())
        if m:
            index, total = int(m.group(1)), int(m.group(2))
            progress(index / float(total), m.group(3))
    p.wait()
    if p.returncode != 0:
        raise UpdateError('{0} failed: {1}'.format(what, '\n'.join(tail).strip()))


def sync_template(root):
    """Make the template match what was just installed.

    /etc and /var in a running system are tmpfs poured from /conf/base at
    boot. Without this the update comes up with the old /etc and with pkg's
    database from the day the image was made: the system works, and has no
    idea which packages it is made of, which is exactly what the next update
    needs to know.
    """
    template = _template(root)
    for rel in TEMPLATE_PATHS:
        _mirror(root, os.path.join(root, rel), os.path.join(template, rel))


def pour_template(root):
    """Give the environment the /etc and pkg database it really boots with.

    The reverse of sync_template(), and what the boot itself does: /etc and
    /var are tmpfs poured from /conf/base. The /etc on the disk of an
    environment underneath them is the bare one from the image and is never
    seen by the running system -- measured on the test machine (2026-10-06):
    533 files there against 949 in the template, and no /etc/local at all.
    pkg working on that /etc fails where /usr/local/etc links to /etc/local
    ("Fail to rename ... /usr/local/etc: Not a directory"), and
    sync_template() copying it back afterwards would have dropped some four
    hundred files from the template, /etc/local whole, and the system would
    have booted without the configuration of its services.
    """
    template = _template(root)
    for rel in TEMPLATE_PATHS:
        _mirror(root, os.path.join(template, rel), os.path.join(root, rel))


def _template(root):
    template = os.path.join(root, CONF_BASE)
    if not os.path.isdir(template):
        raise UpdateError(
            'No {0} in the new environment: this system does not pour /etc and /var '
            'from a template, and the update has nothing to synchronise'.format(template)
        )
    return template


def _mirror(root, src, dst):
    """Make `dst` an exact copy of `src`, swapping it in whole."""
    _inside(root, src)
    _inside(root, dst)
    if not os.path.isdir(src):
        raise UpdateError('Nothing at {0} to copy'.format(src))
    os.makedirs(os.path.dirname(dst.rstrip('/')), exist_ok=True)
    tmp = dst.rstrip('/') + '.new'
    shutil.rmtree(tmp, ignore_errors=True)
    # The -shm file is sqlite's shared-memory index and nothing else: it is
    # rebuilt on demand, and a stale one copied next to a database it does not
    # belong to is the one way this copy could mislead sqlite. The -wal file,
    # by contrast, may hold committed data and travels with it.
    shutil.copytree(src, tmp, symlinks=True, ignore=shutil.ignore_patterns('*-shm'))
    old = dst.rstrip('/') + '.old'
    shutil.rmtree(old, ignore_errors=True)
    if os.path.lexists(dst):
        os.rename(dst, old)
    os.rename(tmp, dst)
    shutil.rmtree(old, ignore_errors=True)


# The sentinel ix-update looks for on the first boot of a new system. With it
# the configuration database is backed up, migrated to the schema of the
# middleware that boot runs, and the machine reboots once; on failure the
# backup is restored. /data lives inside each boot environment, so the
# sentinel goes into the NEW environment -- set in the running one, it would
# migrate the database of the system being left behind.
NEED_UPDATE_SENTINEL = 'data/need-update'


# What the system calls itself. freenasOS reads the version and the train
# from this manifest (Configuration.SystemManifest), and system.version is
# that version: nothing pkg installs updates it.
SYSTEM_MANIFEST = 'data/manifest'


def stamp_version(root, manifest):
    """Record in the new environment which version has just gone into it.

    Without this an environment updated with pkg booted under the version it
    was cloned from -- measured on the test machine (2026-10-06): packages of
    202610060940, /etc/version and system.version still 202610060859 -- and
    every check for updates would then offer it what it already runs. The
    signed manifest is the one authority on what this update is.
    """
    version = manifest['version']
    path = os.path.join(root, SYSTEM_MANIFEST)
    _inside(root, path)
    try:
        with open(path) as f:
            system = json.load(f)
    except (OSError, ValueError) as e:
        raise UpdateError('Cannot read the system manifest {0}: {1}'.format(path, e))
    system['Version'] = version
    # The sequence is what the freenasOS path compares with the train's
    # LATEST; the version is unique per build and serves as well.
    system['Sequence'] = version
    released = manifest.get('released')
    if released:
        with contextlib.suppress(ValueError):
            system['BuildTime'] = str(int(datetime.datetime.strptime(
                released, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc).timestamp()))
    tmp = path + '.new'
    with open(tmp, 'w') as f:
        json.dump(system, f, sort_keys=True, indent=4)
    os.rename(tmp, path)

    etc_version = os.path.join(root, 'etc', 'version')
    _inside(root, etc_version)
    with open(etc_version, 'w') as f:
        f.write(version + '\n')


def request_migration(root):
    """Have the new environment migrate its database on first boot.

    The installer sets this sentinel after every upgrade; the old freenasOS
    path ran the migrations from package scripts instead. pkg runs neither,
    so without it an update that brings a newer middleware boots it against
    the old schema.
    """
    data = os.path.join(root, 'data')
    if not os.path.isdir(data):
        raise UpdateError('No /data in the new environment {0}: cannot request '
                          'the database migration'.format(root))
    with open(os.path.join(root, NEED_UPDATE_SENTINEL), 'w'):
        pass


# --------------------------------------------------------------------------
# Boot environments
# --------------------------------------------------------------------------

def environments():
    """The boot environments, as beadm lists them.

    Returns a list of dicts with name, active ('N' for now, 'R' for the next
    boot, 'NR' for both) and the creation date as beadm prints it.
    """
    out = _check([BEADM, 'list', '-H'], 'listing boot environments')
    result = []
    for line in out.splitlines():
        parts = line.split('\t')
        if len(parts) < 2:
            parts = line.split()
        if not parts:
            continue
        result.append({
            'name': parts[0],
            'active': parts[1] if len(parts) > 1 else '',
            'created': parts[-1] if len(parts) > 2 else '',
        })
    return result


def create_environment(name):
    existing = {be['name'] for be in environments()}
    if name in existing:
        raise UpdateError(
            'A boot environment named {0} already exists. Remove it or activate it; '
            'an update will not write into an environment it did not make.'.format(name)
        )
    _check([BEADM, 'create', name], 'creating boot environment {0}'.format(name))
    return name


def mount_environment(name, where=None):
    where = where or tempfile.mkdtemp(prefix='bsdnas-be-')
    _check([BEADM, 'mount', name, where], 'mounting boot environment {0}'.format(name))
    return where


def umount_environment(name):
    _run([BEADM, 'umount', '-f', name])


def activate_environment(name):
    _check([BEADM, 'activate', name], 'activating boot environment {0}'.format(name))


def destroy_environment(name):
    _check([BEADM, 'destroy', '-F', name], 'destroying boot environment {0}'.format(name))


def previous_environment():
    """The environment to go back to: the newest one that is not the current.

    Rollback is choosing a different environment at the next boot, so the
    question is which one. The newest of the rest is the one the last update
    came from.
    """
    others = [be for be in environments() if 'N' not in be['active']]
    if not others:
        return None
    return sorted(others, key=lambda be: be['created'])[-1]


# --------------------------------------------------------------------------
# The update itself
# --------------------------------------------------------------------------

def apply_update(manifest, progress=None, be_name=None, packages=None, activate=True):
    """Install an update into a new boot environment and make it the next boot.

    The running system is not written to at any point. Should anything fail,
    the half-built environment is destroyed and the machine stays exactly as
    it was, still booting what it boots now.
    """
    def say(fraction, text):
        if progress is not None:
            progress(max(0.0, min(1.0, fraction)) * 100.0, text)

    be_name = be_name or manifest['version']

    say(0.01, 'Creating boot environment {0}'.format(be_name))
    create_environment(be_name)
    mounted = None
    try:
        mounted = mount_environment(be_name)

        say(0.03, 'Preparing the environment from its configuration template')
        pour_template(mounted)

        with prepared_root(mounted, manifest['repos']) as repos_dir:
            say(0.05, 'Reading the package catalogue')
            update_catalogue(mounted, repos_dir, manifest['repos'])

            changes = pending_changes(mounted, repos_dir)
            if not changes and not packages:
                raise UpdateError('Already up to date: the repositories hold no newer packages')

            # Fetching and installing is the long part; it gets the span from
            # 10% to 90% and reports its own progress inside it.
            say(0.10, '{0} packages to change'.format(len(changes)))
            install(mounted, repos_dir,
                    progress=lambda f, text: say(0.10 + 0.80 * f, text),
                    packages=packages)

        say(0.91, 'Recording version {0} in the environment'.format(manifest['version']))
        stamp_version(mounted, manifest)

        # After prepared_root() has taken its resolv.conf back: the template
        # must not capture it. After stamp_version(): /etc/version has to
        # reach the template the system boots from.
        say(0.92, 'Synchronising the configuration template')
        sync_template(mounted)

        say(0.95, 'Scheduling the database migration for the first boot')
        request_migration(mounted)

        umount_environment(be_name)
        mounted = None

        if activate:
            say(0.98, 'Making {0} the next boot'.format(be_name))
            activate_environment(be_name)
        say(1.0, 'Update installed into {0}; reboot to use it'.format(be_name))
    except Exception:
        if mounted is not None:
            umount_environment(be_name)
        with contextlib.suppress(Exception):
            destroy_environment(be_name)
        raise

    return {'boot_environment': be_name, 'version': manifest['version'], 'changes': changes}
