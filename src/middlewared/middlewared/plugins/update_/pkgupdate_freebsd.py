# -*- coding=utf-8 -*-
"""The pkg backend of the update plugin, and how a train chooses it.

A train moves to package updates by publishing a signed manifest.json next to
its LATEST on the update server. That is the whole switch: no setting on the
machine, nothing to flip by hand, and a train that has not moved keeps working
exactly as before through freenasOS.

Three outcomes when the manifest is looked for, and they are not equal:

* not published (404) -- the train has not moved; the old path runs;
* published and verified -- the update goes through pkgbase.apply_update();
* published but not verifiable, or not whole -- the update stops. Falling back
  to the old path here would mean that whoever can break the manifest chooses
  the weaker check for us.

Nothing is downloaded ahead of time on this path: pkg fetches what it needs
while installing into the new boot environment. "Download" therefore verifies
the manifest and records which version the user agreed to; "install" verifies
it once more and refuses if the train has moved on in between. The manifest
handed to apply_update() is always the one verified a moment ago, never one
read back from disk.
"""
import contextlib
import json
import os

from freenasOS import Configuration

from middlewared.service import CallError, private, Service

from . import pkgbase
from .utils import can_update

# The record a pkg download leaves in the update location. The other
# platform modules look for it to tell a pkg update from an old-style one.
MARKER = 'pkgbase-update.json'

PRODUCT = 'BSDnas'


def marker_path(location):
    return os.path.join(location, MARKER)


class UpdateService(Service):

    @private
    def pkgbase_train_url(self, train):
        return '{0}/{1}'.format(Configuration.Configuration().UpdateServerURL().rstrip('/'), train)

    @private
    def pkgbase_manifest(self, train):
        """The verified manifest of `train`, or None when the train has none."""
        url = self.pkgbase_train_url(train)
        try:
            manifest = pkgbase.fetch_manifest(url)
        except pkgbase.ManifestNotPublished:
            return None
        except pkgbase.UpdateError as e:
            raise CallError(str(e))

        # The signature proves the manifest is ours, not that it is the one
        # for this train: a valid manifest of another train, served under this
        # one, would verify just as well.
        if manifest.get('train') != train:
            raise CallError(
                'The manifest published for train {0} describes train {1}. '
                'Refusing to update from it.'.format(train, manifest.get('train'))
            )
        return manifest

    @private
    def pkgbase_newer(self, manifest):
        """(current version, offered version) when the offer is newer, else None."""
        current = self.middleware.call_sync('system.version')
        offered = manifest['version']
        if offered == current or not can_update(current, offered):
            return None
        return current, offered

    @private
    def pkgbase_check(self, manifest):
        newer = self.pkgbase_newer(manifest)
        if newer is None:
            return {'status': 'UNAVAILABLE'}
        current, offered = newer
        return {
            'status': 'AVAILABLE',
            # The catalogue is not read at this point: doing so means running
            # pkg against a root, and a check has no business writing one.
            # The real list of packages appears in the job while installing.
            'changes': [{
                'operation': 'upgrade',
                'old': {'name': PRODUCT, 'version': current, 'size': None},
                'new': {'name': PRODUCT, 'version': offered, 'size': None},
            }],
            'notice': None,
            'notes': None,
            'changelog': None,
            'version': offered,
        }

    @private
    def pkgbase_download(self, job, train, location, manifest):
        newer = self.pkgbase_newer(manifest)
        if newer is None:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(marker_path(location))
            return False
        current, offered = newer
        os.makedirs(location, exist_ok=True)
        with open(marker_path(location), 'w') as f:
            json.dump({'train': train, 'old_version': current, 'version': offered}, f)
        job.set_progress(100, 'Update {0} verified; packages are fetched while installing'.format(offered))
        return True

    @private
    def pkgbase_pending(self, location):
        with open(marker_path(location)) as f:
            pending = json.load(f)
        return [{
            'operation': 'upgrade',
            'old': {'name': PRODUCT, 'version': pending['old_version']},
            'new': {'name': PRODUCT, 'version': pending['version']},
        }]

    @private
    def pkgbase_install(self, job, location):
        with open(marker_path(location)) as f:
            pending = json.load(f)

        job.set_progress(0, 'Verifying the update manifest')
        manifest = self.pkgbase_manifest(pending['train'])
        if manifest is None:
            raise CallError('Train {0} no longer publishes a package update'.format(pending['train']))
        if manifest['version'] != pending['version']:
            raise CallError(
                'Train {0} has moved on from {1} to {2} since the update was downloaded. '
                'Check for updates again.'.format(pending['train'], pending['version'], manifest['version'])
            )
        if self.pkgbase_newer(manifest) is None:
            raise CallError('You already are using {0}'.format(manifest['version']))

        try:
            result = pkgbase.apply_update(
                manifest,
                progress=lambda percent, text: job.set_progress(percent, text),
            )
        except pkgbase.UpdateError as e:
            raise CallError(str(e))

        with contextlib.suppress(FileNotFoundError):
            os.unlink(marker_path(location))
        return result
