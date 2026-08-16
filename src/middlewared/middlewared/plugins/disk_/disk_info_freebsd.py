import os
import re
import subprocess

import bsd
import bsd.geom
import bsd.disk
from middlewared.service import private, Service
from .disk_info_base import DiskInfoBase


RE_DISKPART = re.compile(r'^([a-z]+\d+)(p\d+)?')
GiB = 1024 ** 3


class DiskService(Service, DiskInfoBase):

    async def get_dev_size(self, dev):
        try:
            return await self.middleware.run_in_thread(bsd.disk.get_size_with_name, dev)
        except Exception:
            self.logger.error('Failed to get size of %r', dev, exc_info=True)

    def list_partitions(self, disk, part_xml=None):
        parts = []
        if part_xml is None:
            part_xml = self.middleware.call_sync('geom.cache.get_class_xml', 'PART')
            if not part_xml:
                return parts

        for g in part_xml.findall(f'./geom[name="{disk}"]'):
            for p in g.findall('./provider'):
                size = p.find('./mediasize')
                if size is not None:
                    try:
                        size = int(size.text)
                    except ValueError:
                        size = None
                name = p.find('./name')
                part_type = p.find('./config/type')
                if part_type is not None:
                    part_type = self.middleware.call_sync('disk.get_partition_uuid_from_name', part_type.text)
                if not part_type:
                    part_type = 'UNKNOWN'
                part_uuid = p.find('./config/rawuuid')
                part = {
                    'name': name.text,
                    'size': size,
                    'partition_type': part_type,
                    'disk': disk,
                    'id': p.get('id'),
                    'path': os.path.join('/dev', name.text),
                    'encrypted_provider': None,
                    'partition_number': None,
                    'partition_uuid': part_uuid.text if part_uuid is not None else None,
                }
                part_no = RE_DISKPART.match(part['name'])
                if part_no and part_no.group(2):
                    part['partition_number'] = int(part_no.group(2)[1:])
                if os.path.exists(f'{part["path"]}.eli'):
                    part['encrypted_provider'] = f'{part["path"]}.eli'
                parts.append(part)

        return parts

    def gptid_from_part_type(self, disk, part_type, part_xml=None):
        if part_xml is None:
            part_xml = self.middleware.call_sync('geom.cache.get_class_xml', 'PART')

        # Разделы приходят в произвольном порядке, поэтому отбираем по номеру,
        # а не по месту в списке.
        matches = []
        for g in part_xml.findall(f'.//geom[name="{disk}"]'):
            for prov in g.findall('./provider'):
                raw = prov.find('./config/rawtype')
                uuid = prov.find('./config/rawuuid')
                name = prov.find('./name')
                if raw is None or uuid is None or raw.text != part_type:
                    continue
                number = 0
                if name is not None:
                    part_no = RE_DISKPART.match(name.text)
                    if part_no and part_no.group(2):
                        number = int(part_no.group(2)[1:])
                matches.append((number, uuid.text))

        if not matches:
            raise ValueError(f'Partition type {part_type} not found on {disk}')

        matches.sort()
        if len(matches) > 1:
            # На диске с системой разделов ZFS два: загрузочный пул в начале
            # диска и данные на остатке. Данные — это всегда раздел с большим
            # номером; отдать первый значило бы отдать загрузочный пул.
            return f'gptid/{matches[-1][1]}'
        if self.system_partitions(disk, part_xml):
            # Единственный раздел ZFS на диске с загрузочными разделами — это
            # и есть загрузочный пул. Под данные его отдавать нельзя.
            raise ValueError(
                f'На диске {disk} стоит система, а раздела под данные нет. '
                f'Сначала разметьте диск (disk.format), затем добавляйте в пул.'
            )
        return f'gptid/{matches[0][1]}'

    @private
    def system_partitions(self, disk, part_xml=None):
        """
        Разделы загрузчика на диске: efi либо freebsd-boot. Их наличие означает,
        что система стоит на этом же диске, и затирать его нельзя.
        """
        if part_xml is None:
            part_xml = self.middleware.call_sync('geom.cache.get_class_xml', 'PART')
            if not part_xml:
                return []

        boot_types = (
            'c12a7328-f81f-11d2-ba4b-00a0c93ec93b',  # efi
            '83bd6b9d-7f41-11dc-be0b-001560b84f0f',  # freebsd-boot
        )
        found = []
        for g in part_xml.findall(f'.//geom[name="{disk}"]'):
            for p in g.findall('./provider'):
                raw = p.find('./config/rawtype')
                if raw is not None and raw.text in boot_types:
                    name = p.find('./name')
                    found.append(name.text if name is not None else None)
        return found

    @private
    def has_free_space(self, disk, minimum=GiB):
        """
        Есть ли на диске неразмеченный кусок, куда можно положить раздел данных.
        Нужно для установки системы на диски основного массива: диск с системой
        не считается занятым, если после её раздела остался свободный хвост.
        """
        cp = subprocess.run(
            ('gpart', 'show', disk), capture_output=True, text=True,
        )
        if cp.returncode != 0:
            return False
        sector = bsd.disk.get_sectorsize_with_name(disk) or 512
        for line in cp.stdout.splitlines():
            if '- free -' not in line:
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            try:
                if int(parts[1]) * sector >= minimum:
                    return True
            except ValueError:
                continue
        return False

    @private
    def data_room_on_system_disk(self, disk):
        """
        Можно ли на диске с системой разместить данные: либо есть свободное
        место, либо раздел под данные уже нарезан прошлой разметкой. Диски,
        которые реально заняты пулом, отсеиваются отдельно — по pool.get_disks.
        """
        if self.has_free_space(disk):
            return True
        return any(
            (part['partition_number'] or 0) >= 3
            for part in self.list_partitions(disk)
        )

    async def get_zfs_part_type(self):
        return '516e7cba-6ecf-11d6-8ff8-00022d09712b'

    async def get_swap_part_type(self):
        return '516e7cb5-6ecf-11d6-8ff8-00022d09712b'

    def get_swap_devices(self):
        return [os.path.join('/dev', i.devname) for i in bsd.getswapinfo()]

    def label_to_dev_disk_cache(self):
        label_to_dev = {}
        xml = self.middleware.call_sync('geom.cache.get_xml')
        for label in xml.iterfind('.//class[name="LABEL"]/geom'):
            if (name := label.find('name')) is not None:
                for provider in label.iterfind('provider'):
                    if (prov := provider.find('name')) is not None:
                        label_to_dev[prov.text] = name.text

        dev_to_disk = {}
        for label in xml.iterfind('.//class[name="PART"]/geom'):
            if (name := label.find('name')) is not None:
                for provider in label.iterfind('provider'):
                    if (prov := provider.find('name')) is not None:
                        dev_to_disk[prov.text] = name.text

        return {
            'label_to_dev': label_to_dev,
            'dev_to_disk': dev_to_disk,
        }

    def label_to_dev(self, label, geom_scan=True, cache=None):
        if label.endswith('.nop'):
            label = label[:-4]
        elif label.endswith('.eli'):
            label = label[:-4]

        if cache is not None:
            return cache['label_to_dev'].get(label)

        if geom_scan:
            bsd.geom.scan()
        klass = bsd.geom.class_by_name('LABEL')
        prov = klass.xml.find(f'.//provider[name="{label}"]/../name')
        if prov is not None:
            return prov.text

    def label_to_disk(self, label, geom_scan=True, cache=None):
        if cache is None:
            if geom_scan:
                bsd.geom.scan()
        dev = self.label_to_dev(label, geom_scan, cache) or label
        if cache is not None:
            return cache['dev_to_disk'].get(dev)
        part = bsd.geom.class_by_name('PART').xml.find(f'.//provider[name="{dev}"]/../name')
        if part is not None:
            return part.text

    def get_disk_from_partition(self, part_name):
        return self.label_to_disk(part_name, True)
