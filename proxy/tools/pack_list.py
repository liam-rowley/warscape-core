#!/usr/bin/env python3
"""List or extract entries of Warscape PFH0 packs (the PFH0 titles), read only.

Purpose: find files inside the game's packs (movies, UI scripts, layouts, battle presets) without a pack editor.
Usage: pack_list.py PACK [PACK ...] [--grep TEXT ...] [--ext .luac|none ...] [--under ui ...] [--extract OUTDIR] [--json]
       (TEXT is a case-insensitive substring of the entry path; --extract writes the matching entries under OUTDIR/<pack stem>/<path>)
When: discovery for the dev control channel (J3: start-up movies, front-end scripts); a stand-in until the asset index (J7)
      owns pack reading. Never writes next to the packs.

Format (PFH0, 24-byte header, little endian): magic, pack type (4 = movie pack), 0, size of the pack-name list, entry count,
index size; then the pack-name list, then the index (u32 size + NUL-terminated path per entry), then the data in index order.
not-a-verb: reads the game's binary packs in the game folder on the PC; a standalone discovery reader until J7's asset index
"""
import argparse
import json
import os
import struct
import sys


def read_header(path):
    """The 24-byte PFH0 header and the raw pack-name list and index (J6: header facts and the index hash)."""
    with open(path, "rb") as f:
        hdr = f.read(24)
        if len(hdr) < 24 or hdr[:4] != b"PFH0":
            raise ValueError(f"{path}: not a PFH0 pack (magic {hdr[:4]!r})")
        magic, ptype, flags, names_size, count, index_size = struct.unpack("<4sIIIII", hdr)
        names = f.read(names_size)
        idx = f.read(index_size)
    if len(idx) != index_size:
        raise ValueError(f"{path}: index truncated ({len(idx)} of {index_size} bytes)")
    return {"magic": magic.decode("latin-1"), "pack_type": ptype, "flags": flags, "names_size": names_size, "count": count,
            "index_size": index_size, "pack_names": [n.decode("latin-1") for n in names.split(b"\0") if n], "index": idx}


def read_index(path):
    h = read_header(path)
    ptype, names_size, count, index_size, idx = h["pack_type"], h["names_size"], h["count"], h["index_size"], h["index"]
    off = 24 + names_size + index_size
    pos = 0
    entries = []
    for _ in range(count):
        size = struct.unpack_from("<I", idx, pos)[0]
        pos += 4
        end = idx.index(b"\0", pos)
        name = idx[pos:end].decode("latin-1").replace("/", "\\")
        pos = end + 1
        entries.append({"path": name, "size": size, "offset": off})
        off += size
    return ptype, entries


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("packs", nargs="+")
    ap.add_argument("--grep", action="append", default=[])
    ap.add_argument("--ext", action="append", default=[], help="keep entries with this extension (.luac); 'none' = no extension")
    ap.add_argument("--under", action="append", default=[], help="keep entries under this folder prefix (ui\\)")
    ap.add_argument("--extract")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    exts = {("" if x.lower() == "none" else x.lower()) for x in a.ext}
    unders = [u.lower().replace("/", "\\").rstrip("\\") + "\\" for u in a.under]
    out = []
    for p in a.packs:
        ptype, entries = read_index(p)
        for e in entries:
            low = e["path"].lower()
            if a.grep and not any(g.lower() in low for g in a.grep):
                continue
            if exts and os.path.splitext(low.rsplit("\\", 1)[-1])[1] not in exts:
                continue
            if unders and not any(low.startswith(u) for u in unders):
                continue
            e = dict(e, pack=os.path.basename(p), pack_type=ptype)
            out.append(e)
            if a.extract:
                dst = os.path.join(a.extract, os.path.splitext(os.path.basename(p))[0], *e["path"].split("\\"))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with open(p, "rb") as f, open(dst, "wb") as g:
                    f.seek(e["offset"])
                    g.write(f.read(e["size"]))
    if a.json:
        json.dump(out, sys.stdout, indent=1)
    else:
        for e in out:
            print(f'{e["pack"]}\t{e["size"]}\t{e["path"]}')
    return 0


if __name__ == "__main__":
    sys.exit(main())
