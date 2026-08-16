Compatibility symlinks for the ZFS utilities.

In our build ZFS comes from ports and lives in /usr/local/sbin, while the base
/sbin/zfs and /sbin/zpool are absent. Service startup scripts run with a PATH
without /usr/local/sbin, so anything looking for zfs on the usual path breaks. That is
podman tripped over this on every boot:

    Error: configure storage: the 'zfs' command is not available

The symlinks restore the familiar location and remove a whole class of such breakages.
