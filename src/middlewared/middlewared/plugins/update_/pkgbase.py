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

* The manifest is signed, the packages are not. Signing the repositories with
  `pkg repo -k` is still to be done; until it is, the signed manifest proves
  only which repository to use, so the repository has to be served over https
  and write_repo_conf() refuses anything else.
"""
import contextlib
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

    What this does NOT yet check: the packages themselves. The repositories
    are written with signature_type: none, because nothing signs them at
    publish time -- `pkg repo -k` is not part of the publishers. The signed
    manifest therefore authenticates WHICH repository to take packages from,
    not WHAT comes back from it, and the integrity of the code that ends up
    running as root rests on the transport. That is why the transport has to
    be https: over plain http anyone on the path can answer instead of the
    server, and pkg, told to verify nothing, would install what they sent.
    Signing the repositories closes this properly and is the next step; until
    then the scheme is enforced here rather than left to whoever writes a
    manifest.
    """
    os.makedirs(directory, exist_ok=True)
    conf = []
    for name, repo in sorted(repos.items()):
        url = repo['url'] if isinstance(repo, dict) else repo
        if not isinstance(url, str) or not url.startswith('https://'):
            raise UpdateError(
                'Repository {0} is published over {1!r}, and the packages it serves '
                'are not signed. Refusing to install from it: an update must arrive '
                'over https.'.format(name, url)
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
                '  signature_type: none\n'
                '}\n' % (name, url)
            )
    return directory


def _pkg(root, repos_dir, args):
    # FETCH_RETRY is pkg's own retry of a failed download (default 3), raised
    # for the same unreliable networks the manifest fetch retries for.
    return ['env', 'ASSUME_ALWAYS_YES=yes', 'REPOS_DIR=' + repos_dir,
            'FETCH_RETRY={0}'.format(PKG_FETCH_RETRY),
            'pkg', '-r', root] + list(args)


def _versions(output):
    out = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            out[parts[0]] = parts[1]
    return out


def update_catalogue(root, repos_dir):
    """Refresh the catalogues and insist that they hold something.

    pkg treats an unreachable repository as a repository with no packages and
    exits happily. Taken at face value that turns into an update that installs
    nothing and reports success, so the emptiness is an error here.
    """
    _check(_pkg(root, repos_dir, ['update', '-f']), 'updating the package catalogue')
    available = _versions(_check(_pkg(root, repos_dir, ['rquery', '%n %v']),
                                 'reading the package catalogue'))
    if not available:
        raise UpdateError(
            'The repositories named by the manifest hold no packages. Refusing to '
            'continue: an update that installs nothing would still look like one.'
        )
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
    template = os.path.join(root, CONF_BASE)
    if not os.path.isdir(template):
        raise UpdateError(
            'No {0} in the new environment: this system does not pour /etc and /var '
            'from a template, and the update has nothing to synchronise'.format(template)
        )
    for rel in TEMPLATE_PATHS:
        src = os.path.join(root, rel)
        dst = os.path.join(template, rel)
        if not os.path.isdir(src):
            raise UpdateError('Nothing at {0} to copy into the template'.format(src))
        parent = os.path.dirname(dst.rstrip('/'))
        os.makedirs(parent, exist_ok=True)
        tmp = dst.rstrip('/') + '.new'
        shutil.rmtree(tmp, ignore_errors=True)
        # The -shm file is sqlite's shared-memory index and nothing else: it is
        # rebuilt on demand, and a stale one copied next to a database it does
        # not belong to is the one way this copy could mislead sqlite. The -wal
        # file, by contrast, may hold committed data and travels with it.
        shutil.copytree(src, tmp, symlinks=True,
                        ignore=shutil.ignore_patterns('*-shm'))
        old = dst.rstrip('/') + '.old'
        shutil.rmtree(old, ignore_errors=True)
        if os.path.exists(dst):
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
    repos_dir = tempfile.mkdtemp(prefix='bsdnas-repos-')
    write_repo_conf(repos_dir, manifest['repos'])

    say(0.01, 'Creating boot environment {0}'.format(be_name))
    create_environment(be_name)
    mounted = None
    try:
        mounted = mount_environment(be_name)

        say(0.05, 'Reading the package catalogue')
        update_catalogue(mounted, repos_dir)

        changes = pending_changes(mounted, repos_dir)
        if not changes and not packages:
            raise UpdateError('Already up to date: the repositories hold no newer packages')

        # Fetching and installing is the long part; it gets the span from 10%
        # to 90% and reports its own progress inside it.
        say(0.10, '{0} packages to change'.format(len(changes)))
        install(mounted, repos_dir,
                progress=lambda f, text: say(0.10 + 0.80 * f, text),
                packages=packages)

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
    finally:
        shutil.rmtree(repos_dir, ignore_errors=True)

    return {'boot_environment': be_name, 'version': manifest['version'], 'changes': changes}
