import os

from middlewared.schema import Bool, Dict, Int, Str, accepts
from middlewared.service import CallError, Service, job, private
from middlewared.utils import osc, run
from middlewared.validators import Range

try:
    from bsd import geom
except ImportError:
    geom = None


BOOT_POOL_NAME = None
BOOT_POOL_NAME_VALID = ['freenas-boot', 'boot-pool']


class BootService(Service):

    @private
    async def pool_name(self):
        return BOOT_POOL_NAME

    @accepts()
    async def get_state(self):
        """
        Returns the current state of the boot pool, including all vdevs, properties and datasets.
        """
        return await self.middleware.call('zfs.pool.query', [('name', '=', BOOT_POOL_NAME)], {'get': True})

    @accepts()
    async def get_disks(self):
        """
        Returns disks of the boot pool.
        """
        return await self.middleware.call('zfs.pool.get_disks', BOOT_POOL_NAME)

    @private
    async def get_boot_type(self):
        """
        Get the boot type of the boot pool.

        Returns:
            "BIOS", "EFI", None
        """
        if osc.IS_LINUX:
            # https://wiki.debian.org/UEFI
            return 'EFI' if os.path.exists('/sys/firmware/efi') else 'BIOS'
        else:
            return await self.__get_boot_type_freebsd()

    async def __get_boot_type_freebsd(self):
        await self.middleware.run_in_thread(geom.scan)
        labelclass = geom.class_by_name('PART')
        efi = bios = 0
        for disk in await self.get_disks():
            for e in labelclass.xml.findall(f".//geom[name='{disk}']/provider/config/type"):
                if e.text == 'efi':
                    efi += 1
                elif e.text == 'freebsd-boot':
                    bios += 1
        if efi == 0 and bios == 0:
            return None
        if bios > 0:
            return 'BIOS'
        return 'EFI'

    @accepts(
        Str('dev'),
        Dict(
            'options',
            Bool('expand', default=False),
        ),
    )
    @job(lock='boot_attach')
    async def attach(self, job, dev, options=None):
        """
        Attach a disk to the boot pool, turning a stripe into a mirror.

        `expand` option will determine whether the new disk partition will be
                 the maximum available or the same size as the current disk.
        """
        await self.check_update_ashift_property()
        disks = list(await self.get_disks())

        format_opts = {}
        if not options['expand']:
            # Lets try to find out the size of the current freebsd-zfs partition so
            # the new partition is not bigger, preventing size mismatch if one of
            # them fail later on. See #21336
            zfs_part = await self.member_partition(disks[0])
            if zfs_part:
                format_opts['size'] = zfs_part['size']

        swap_part = await self.middleware.call('disk.get_partition', disks[0], 'SWAP')
        if swap_part:
            format_opts['swap_size'] = swap_part['size']
        await self.middleware.call('boot.format', dev, format_opts)

        pool = await self.middleware.call('zfs.pool.query', [['name', '=', BOOT_POOL_NAME]], {'get': True})

        zfs_dev_part = await self.middleware.call('disk.get_partition', dev, 'ZFS')
        extend_pool_job = await self.middleware.call(
            'zfs.pool.extend', BOOT_POOL_NAME, None, [{
                'target': pool['groups']['data'][0]['guid'],
                'type': 'DISK',
                'path': f'/dev/{zfs_dev_part["name"]}'
            }]
        )

        await self.middleware.call('boot.install_loader', dev)

        await job.wrap(extend_pool_job)

        # If the user is upgrading his disks, let's set expand to True to make sure that we
        # register the new disks capacity which increase the size of the pool
        await self.middleware.call('zfs.pool.online', BOOT_POOL_NAME, zfs_dev_part['name'], True)

    @private
    async def needs_copy(self):
        """
        Нужно ли отдать новому диску копию загрузочного пула. Да, если система
        стоит на дисках массива и копий стало меньше положенных трёх — либо
        участник выпал, либо его уже отцепили. Три копии — компромисс: зеркало
        шире смысла не имеет, а две копии оставляют систему без запаса.
        """
        if not await self.array_layout():
            return False
        if await self.missing_member():
            return True
        return len(list(await self.get_disks())) < 3

    @private
    async def member_partition(self, disk):
        """
        Раздел этого диска, который состоит в загрузочном пуле. Спрашивать
        "первый раздел ZFS" нельзя: при установке на диски основного массива
        разделов ZFS на диске два, и вторым идёт раздел данных — по нему новый
        диск разметился бы наоборот.
        """
        state = await self.get_state()
        names = set()
        for vdev in (state.get('groups') or {}).get('data') or []:
            for child in vdev.get('children') or [vdev]:
                path = child.get('path') or ''
                if path:
                    names.add(os.path.basename(path))
        for part in await self.middleware.call('disk.list_partitions', disk):
            if part['name'] in names:
                return part
        return None

    @private
    async def array_layout(self):
        """
        Система стоит на дисках основного массива: у дисков загрузочного пула
        есть ещё и раздел под данные. От этого зависит, надо ли при замене
        диска восстанавливать на нём загрузочные разделы.
        """
        zfs_type = await self.middleware.call('disk.get_zfs_part_type')
        for disk in await self.get_disks():
            parts = await self.middleware.call('disk.list_partitions', disk)
            if len([p for p in parts if p['partition_type'] == zfs_type]) > 1:
                return True
        return False

    @private
    async def missing_member(self):
        """
        Метка выпавшего участника зеркала загрузочного пула, если такой есть.
        Именно её надо отдать в boot.replace, когда диск меняют.
        """
        try:
            pool = await self.middleware.call(
                'zfs.pool.query', [['name', '=', BOOT_POOL_NAME]], {'get': True}
            )
        except Exception:
            return None
        for vdev in (pool.get('groups') or {}).get('data') or []:
            for child in vdev.get('children') or [vdev]:
                if child.get('status') in (None, 'ONLINE'):
                    continue
                return child.get('guid') or child.get('path') or child.get('name')
        return None

    @accepts(Str('dev'))
    async def detach(self, dev):
        """
        Detach given `dev` from boot pool.
        """
        await self.check_update_ashift_property()
        await self.middleware.call('zfs.pool.detach', BOOT_POOL_NAME, dev)

    @accepts(Str('label'), Str('dev'))
    async def replace(self, label, dev):
        """
        Replace device `label` on boot pool with `dev`.
        """
        await self.check_update_ashift_property()
        format_opts = {}
        disks = list(await self.get_disks())
        # Размер нового раздела берём такой же, как у живого участника зеркала.
        # Без этого раздел растянулся бы на весь диск, а при установке системы
        # на диски основного массива остаток диска нужен под данные.
        zfs_part = await self.member_partition(disks[0])
        if zfs_part:
            format_opts['size'] = zfs_part['size']
        swap_part = await self.middleware.call('disk.get_partition', disks[0], 'SWAP')
        if swap_part:
            format_opts['swap_size'] = swap_part['size']

        await self.middleware.call('boot.format', dev, format_opts)
        zfs_dev_part = await self.middleware.call('disk.get_partition', dev, 'ZFS')
        await self.middleware.call('zfs.pool.replace', BOOT_POOL_NAME, label, zfs_dev_part['name'])
        await self.middleware.call('boot.install_loader', dev)

    @accepts()
    @job(lock='boot_scrub')
    async def scrub(self, job):
        """
        Scrub on boot pool.
        """
        subjob = await self.middleware.call('pool.scrub.scrub', BOOT_POOL_NAME)
        return await job.wrap(subjob)

    @accepts(
        Int('interval', validators=[Range(min=1)])
    )
    async def set_scrub_interval(self, interval):
        """
        Set Automatic Scrub Interval value in days.
        """
        await self.middleware.call(
            'datastore.update',
            'system.advanced',
            (await self.middleware.call('system.advanced.config'))['id'],
            {'adv_boot_scrub': interval},
        )
        return interval

    @accepts()
    async def get_scrub_interval(self):
        """
        Get Automatic Scrub Interval value in days.
        """
        return (await self.middleware.call('system.advanced.config'))['boot_scrub']

    @private
    async def check_update_ashift_property(self):
        properties = {}
        if (
            zfs_pool := await self.middleware.call('zfs.pool.query', [('name', '=', BOOT_POOL_NAME)])
        ) and zfs_pool[0]['properties']['ashift']['source'] == 'DEFAULT':
            properties['ashift'] = {'value': '12'}

        if properties:
            await self.middleware.call('zfs.pool.update', BOOT_POOL_NAME, {'properties': properties})


async def setup(middleware):
    global BOOT_POOL_NAME

    pools = (
        await run('zpool', 'list', '-H', '-o', 'name', encoding='utf8')
    ).stdout.strip().split()
    for i in BOOT_POOL_NAME_VALID:
        if i in pools:
            BOOT_POOL_NAME = i
            break
    else:
        middleware.logger.error('Failed to detect boot pool name.')
