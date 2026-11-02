"""
Read and write the Samba group mapping database through samba.samba3.passdb.

The JSON interface to `net groupmap` (`net --json groupmap list|listmem|addmem|batch`)
exists only in the iXsystems Samba tree; stock Samba rejects it. The same operations
are available in the passdb python bindings that ship with stock Samba.

This module is not meant to be used from within middlewared. It is run as a script
in a short-lived subprocess per operation (see `groupmap_passdb` in groupmap.py):

    python3 -I groupmap_passdb.py <smb.conf> <op> [<json args>]

It imports nothing from middlewared. -I keeps the script directory off sys.path, so
the sibling modules of this plugin package cannot shadow anything samba imports.

passdb keeps secrets.tdb, registry.tdb and group_mapping.tdb open for the lifetime of
the process once used, and its loadparm and database handles are process-global. A
fresh process per operation sees the current configuration and leaves no open handles
on the samba state directory behind.

The result is printed to stdout as JSON. On failure a message is printed to stderr
and the exit code is non-zero.
"""
import json
import re
import sys

# passdb errors carry the NTSTATUS only inside the message: "..., (<status>,<text>)"
RE_NTSTATUS = re.compile(r'\((-?\d+),')


class GroupmapError(Exception):
    pass


def ntstatus_of(exc):
    m = RE_NTSTATUS.search(str(exc))
    return int(m.group(1)) & 0xFFFFFFFF if m else None


class GroupmapDB:
    def __init__(self, smb_conf):
        from samba.samba3 import param, passdb
        from samba.dcerpc import lsa, security
        from samba import ntstatus

        self.passdb = passdb
        self.security = security
        self.ntstatus = ntstatus
        self.group_types = {
            'domain': lsa.SID_NAME_DOM_GRP,
            'local': lsa.SID_NAME_ALIAS,
            'builtin': lsa.SID_NAME_WKN_GRP,
        }

        lp = param.get_context()
        lp.load(smb_conf)
        passdb.set_secrets_dir(lp.get('private dir'))
        self.pdb = passdb.PDB(lp.get('passdb backend'))

    def sid(self, sid):
        return self.security.dom_sid(sid)

    def group_type(self, entry):
        group_type = entry['group_type_str']
        if group_type not in self.group_types:
            raise GroupmapError(f'{group_type}: unknown group type')

        return self.group_types[group_type]

    def list(self):
        return [{
            'gid': g.gid,
            'sid': str(g.sid),
            'nt_name': g.nt_name,
            'comment': g.comment,
            'group_type_int': g.sid_name_use,
        } for g in self.pdb.enum_group_mapping()]

    def listmem(self, alias):
        try:
            members = self.pdb.enum_aliasmem(self.sid(alias))
        except self.passdb.error as e:
            # Alias without a group mapping yet has no members
            if ntstatus_of(e) == self.ntstatus.NT_STATUS_NO_SUCH_ALIAS:
                return []
            raise

        return [str(x) for x in members]

    def addmem(self, alias, member):
        self.pdb.add_aliasmem(self.sid(alias), self.sid(member))

    def add(self, entry):
        if entry.get('sid'):
            sid = entry['sid']
        else:
            sid = f'{self.passdb.get_global_sam_sid()}-{entry["rid"]}'

        # As `net groupmap add` does: one gid maps to one SID.
        if any(g.gid == entry['gid'] for g in self.pdb.enum_group_mapping()):
            raise GroupmapError(f'unix gid {entry["gid"]} already mapped')

        g = self.passdb.Groupmap()
        g.sid = self.sid(sid)
        g.gid = entry['gid']
        g.nt_name = entry['nt_name']
        g.sid_name_use = self.group_type(entry)
        g.comment = entry.get('comment', '')
        self.pdb.add_group_mapping_entry(g)

    def mod(self, entry):
        # update_group_mapping_entry() would create a missing entry, so look it up first.
        g = self.pdb.getgrsid(self.sid(entry['sid']))
        if 'gid' in entry:
            g.gid = entry['gid']
        if 'nt_name' in entry:
            g.nt_name = entry['nt_name']
        if 'group_type_str' in entry:
            g.sid_name_use = self.group_type(entry)
        if 'comment' in entry:
            g.comment = entry['comment']
        self.pdb.update_group_mapping_entry(g)

    def delete(self, entry):
        self.pdb.delete_group_mapping_entry(self.sid(entry['sid']))

    def batch(self, data):
        """
        `data` has the layout of the former `net --json groupmap batch` payload:
        {"ADD": [{"groupmap": [...]}], "MOD": [...], "DEL": [...],
         "ADDMEM": [{"alias": sid, "members": [{"sid": sid}]}], "DELMEM": [...]}

        Deletions go first: sync_builtins() queues a DEL and an ADD of the same SID
        to change the type of an entry, and add_group_mapping_entry() overwrites an
        existing entry, so a DEL after the ADD would remove the new entry.
        Alias members are removed before new ones are added, so that a failure part
        way through leaves fewer memberships rather than more.
        """
        for op, fn in (('DEL', self.delete), ('ADD', self.add), ('MOD', self.mod)):
            for block in data.get(op, []):
                for entry in block['groupmap']:
                    self.run_one(op, entry, fn, entry)

        for op, fn in (('DELMEM', self.pdb.del_aliasmem), ('ADDMEM', self.pdb.add_aliasmem)):
            for block in data.get(op, []):
                for member in block['members']:
                    entry = {'alias': block['alias'], 'member': member['sid']}
                    self.run_one(op, entry, fn, self.sid(block['alias']), self.sid(member['sid']))

    def run_one(self, op, entry, fn, *args):
        try:
            fn(*args)
        except (self.passdb.error, GroupmapError, KeyError) as e:
            raise GroupmapError(f'{op} {json.dumps(entry)}: {e}') from None


def main(argv):
    smb_conf, op, *args = argv
    gm = GroupmapDB(smb_conf)
    ops = {
        'list': gm.list,
        'listmem': gm.listmem,
        'addmem': gm.addmem,
        'batch': lambda payload: gm.batch(json.loads(payload)),
    }
    if op not in ops:
        raise GroupmapError(f'{op}: unknown operation')

    try:
        return ops[op](*args)
    except gm.passdb.error as e:
        raise GroupmapError(f'{op}: {e}') from None


if __name__ == '__main__':
    try:
        result = main(sys.argv[1:])
    except GroupmapError as e:
        print(e, file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f'{type(e).__name__}: {e}', file=sys.stderr)
        sys.exit(1)

    print(json.dumps(result))
