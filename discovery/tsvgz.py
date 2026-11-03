"""Deterministic gzip TSV files: sorted rows, gzip mtime 0 and no file name, so a re-run writes byte-identical bytes.

purpose: write and read the committed discovery tables (discovery/assets/index.tsv.gz, discovery/loc/keys.tsv.gz) so a re-run diffs cleanly
usage: from tsvgz import write, read, problems; write(path, header, rows); header, rows = read(path); problems(path) -> [str]   (library)
when: every J7 pass that commits a large table; `wsc discovery check` runs problems() on each committed file
not-a-verb: a library module imported by the discovery passes and the discovery verb
"""
import gzip
import io


def cell(v):
    """One cell: None is empty; tabs and line breaks (never in paths, keys or hashes) become spaces."""
    return '' if v is None else str(v).replace('\t', ' ').replace('\r', ' ').replace('\n', ' ')


def text(header, rows):
    return ('\t'.join(header) + '\n' + ''.join('\t'.join(cell(v) for v in r) + '\n' for r in sorted(rows))).encode('utf-8')


def dumps(header, rows):
    buf = io.BytesIO()
    with gzip.GzipFile(filename='', mode='wb', fileobj=buf, mtime=0, compresslevel=9) as g:
        g.write(text(header, rows))
    return buf.getvalue()


def write(path, header, rows):
    rows = [tuple(cell(v) for v in r) for r in rows]
    data = dumps(header, rows)
    with open(path, 'wb') as f:
        f.write(data)
    return len(rows)


def read(path):
    with open(path, 'rb') as f:
        lines = gzip.decompress(f.read()).decode('utf-8').split('\n')
    return lines[0].split('\t'), [tuple(x.split('\t')) for x in lines[1:] if x]


def problems(path, header=None):
    """Header as expected, rows sorted and unique, a gzip header with mtime 0 and no name, and the inflated bytes exactly text().

    The deflate stream itself is not compared: zlib and zlib-ng (CPython 3.14+ on Windows) compress the same text to different
    bytes, so a byte compare passes on the machine that wrote the file and fails on the other.
    """
    try:
        raw = open(path, 'rb').read()
        inflated = gzip.decompress(raw)
        h, rows = read(path)
    except (OSError, ValueError, EOFError) as e:
        return [f'{path}: {e}']
    out = []
    if header is not None and h != list(header):
        out.append(f'{path}: header {h}, want {list(header)}')
    if rows != sorted(set(rows)):
        out.append(f'{path}: rows are not sorted or repeat')
    elif raw[3] != 0 or raw[4:8] != b'\0\0\0\0':
        out.append(f'{path}: gzip header has a name, extra field or mtime (want flags 0, mtime 0)')
    elif inflated != text(h, rows):
        out.append(f'{path}: inflated text is not the canonical TSV of its rows (sorted, one trailing newline)')
    return out
