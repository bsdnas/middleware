import socket
import asyncio
from urllib.parse import quote


class CTLDControl:
    socket = "/var/run/ctld.sock"

    def __init__(self):
        self.sock = None
        self.loop = asyncio.get_event_loop()

    async def open(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        self.sock.setblocking(False)
        await self.loop.sock_connect(self.sock, self.socket)

    def close(self):
        self.sock.close()
        self.sock = None

    async def cmd(self, command, id, args=[]):
        line = ' '.join([command, quote(id), *args])
        line = line.encode()

        await self.loop.sock_sendall(self.sock, line)
        ret = await self.loop.sock_recv(self.sock, 4096)
        ret = ret.decode()

        if not ret.startswith("OK"):
            raise RuntimeError("ctld-control: {}".format(ret))

    async def __aenter__(self):
        await self.open()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        self.close()

    async def auth_group_set(self, id, type_, auths):
        """
        Parameters
        ----------

        auths : list of 4-tuples (user, secret, peeruser, peersecret)

        """
        type_ = type_.lower()
        args = ["type={}".format(type_)]
        a = []
        if type_ == "chap":
            a = [':'.join([quote(x) for x in i[:2]]) for i in auths if len(i[1]) >= 12]
        elif type_ == "chap-mutual":
            a = [':'.join([quote(x) for x in i[:4]]) for i in auths if len(i[1]) >= 12 and len(i[3]) >= 12]

        args += ["auth={}".format(quote(i)) for i in a]

        await self.cmd("auth-group-set", id, args)

    async def auth_group_del(self, id):
        await self.cmd("auth-group-del", id, [])

    async def lun_set(self, id, ctl_lun, path, blocksize, serial, device_id, size, pblocksize=None, **options):
        args=[
            "ctl-lun={}".format(ctl_lun),
            "path={}".format(quote(path)),
            "blocksize={}".format(blocksize),
            "serial={}".format(quote(serial)),
            "device-id={}".format(quote(device_id)),
        ]

        if size != 0:
            args.append("size={}".format(size))

        if pblocksize is not None:
            args.append("option=pblocksize={}".format(pblocksize))

        for key, value in options.items():
            args.append("option={}={}".format(key, quote(str(value))))

        await self.cmd("lun-set", id, args)

    async def lun_del(self, id):
        await self.cmd("lun-del", id)

    async def target_add(self, id, alias=None, pgs=[], ag=None):
        args = []

        if alias is not None:
            args.append('alias={}'.format(quote(alias)))

        args += [
            'portal-group={}'.format(pg)
            for pg in pgs
        ]

        if ag is not None:
            args.append('auth-group={}'.format(ag))

        await self.cmd("target-add", id, args)

    async def target_del(self, id):
        await self.cmd("target-del", id)

    async def target_set_luns(self, id, luns=[]):
        await self.cmd("target-set-lun", id, luns)
