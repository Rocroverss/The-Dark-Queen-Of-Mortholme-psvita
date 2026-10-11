#!/usr/bin/env python3
"""
pck_patch_gui.py – GUI tool to create and apply patches for Godot .pck files.
Provides:
  - Create Patch: compare two .pck/.exe files and extract only new/changed files.
  - Apply Patch: merge a patch folder into an original .pck/.exe and repack (optionally build a .vpk).
"""

import os
import sys
import tempfile
import shutil
import struct
import hashlib
import zipfile
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from tkinter import filedialog, messagebox

GDPC_MAGIC = b'GDPC'
PCK_EXE_FILETYPES = [
    ("PCK / EXE files", "*.pck *.exe"),
    ("PCK files", "*.pck"),
    ("EXE files", "*.exe"),
]

def _read(f, size):
    data = f.read(size)
    if len(data) != size:
        raise ValueError("Truncated PCK header or file data")
    return data


def _unpack(f, fmt):
    return struct.unpack(fmt, _read(f, struct.calcsize(fmt)))


def find_embedded_pck_offset(exe_path):
    """Find a validated header, including the uint64 size footer used by Godot."""
    with open(exe_path, 'rb') as f:
        length = os.fstat(f.fileno()).st_size
        if length >= 12:
            f.seek(-12, 2)
            size, magic = _unpack(f, '<Q4s')
            pos = length - 12 - size
            if magic == GDPC_MAGIC and pos >= 0:
                f.seek(pos)
                if f.read(4) == GDPC_MAGIC:
                    return pos
        pos = 0
        while pos < length:
            f.seek(pos)
            data = f.read((1 << 20) + 20)
            at = data.find(GDPC_MAGIC)
            while at >= 0:
                if at + 20 <= len(data):
                    fmt, major, minor, patch = struct.unpack_from('<4I', data, at + 4)
                    if fmt in (1, 2, 3, 4) and major in (2, 3, 4) and minor < 100 and patch < 100:
                        return pos + at
                at = data.find(GDPC_MAGIC, at + 1)
            pos += 1 << 20
    return None


def resolve_source(path):
    path = os.path.abspath(path)
    if path.lower().endswith('.exe'):
        sibling = os.path.splitext(path)[0] + '.pck'
        if find_embedded_pck_offset(path) is None and os.path.isfile(sibling):
            return sibling
    return path


def safe_path(root, virtual):
    rel = virtual.removeprefix('res://').replace('\\', '/')
    if not rel or any(part in ('', '.', '..') for part in rel.split('/')) or ':' in rel:
        raise ValueError(f"Unsafe PCK path: {virtual!r}")
    root = os.path.realpath(root)
    dest = os.path.realpath(os.path.join(root, *rel.split('/')))
    if os.path.commonpath((root, dest)) != root:
        raise ValueError(f"Path escapes output folder: {virtual!r}")
    return dest


def read_header_index(src_path):
    """Read unencrypted Godot PCK formats 1-4; offsets returned are absolute."""
    src_path = resolve_source(src_path)
    index = {}
    with open(src_path, 'rb') as f:
        length = os.fstat(f.fileno()).st_size
        start = 0
        if f.read(4) != GDPC_MAGIC:
            start = find_embedded_pck_offset(src_path)
            if start is None:
                raise ValueError("No PCK found. Select the .pck beside the executable.")
        f.seek(start + 4)
        version = _unpack(f, '<4I')
        fmt = version[0]
        if fmt not in (1, 2, 3, 4):
            raise ValueError(f"Unsupported PCK format {fmt}")
        base = 0
        if fmt >= 2:
            flags, base = _unpack(f, '<IQ')
            if flags & ~2:
                raise ValueError("Encrypted or sparse-bundle PCKs are not supported.")
            if fmt >= 3 or flags & 2:
                base += start
            if fmt >= 3:
                directory, = _unpack(f, '<Q')
                if not 0 <= start + directory <= length - 4:
                    raise ValueError("Invalid PCK directory offset")
                f.seek(start + directory)
                reserved = bytes(64)
            else:
                reserved = _read(f, 64)
        else:
            reserved = _read(f, 64)
        count, = _unpack(f, '<I')
        if count > (length - f.tell()) // (36 if fmt == 1 else 40):
            raise ValueError("Invalid PCK file count")
        for _ in range(count):
            path_len, = _unpack(f, '<I')
            if not 0 < path_len <= min(1048576, length - f.tell()):
                raise ValueError("Invalid PCK path length")
            path = _read(f, path_len).decode('utf-8').rstrip('\x00')
            safe_path(tempfile.gettempdir(), path)
            offset, size = _unpack(f, '<QQ')
            _read(f, 16)
            flags = _unpack(f, '<I')[0] if fmt >= 2 else 0
            if flags:
                raise ValueError(f"Encrypted, removal or delta entry is unsupported: {path}")
            offset += base
            if offset > length or size > length - offset:
                raise ValueError(f"PCK data outside file: {path}")
            path = 'res://' + path.removeprefix('res://')
            if path in index:
                raise ValueError(f"Duplicate PCK path: {path}")
            index[path] = (offset, size)
    return version, reserved, index


def _copy_bytes(src, dst, size):
    while size:
        data = _read(src, min(size, 1024 * 1024))
        dst.write(data)
        size -= len(data)


def extract_pck(src_path, out_dir):
    src_path = resolve_source(src_path)
    _, _, index = read_header_index(src_path)
    os.makedirs(out_dir, exist_ok=True)
    with open(src_path, 'rb') as f:
        for path, (offset, size) in index.items():
            dest = safe_path(out_dir, path)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            f.seek(offset)
            with open(dest, 'wb') as out:
                _copy_bytes(f, out, size)


def repack_pck(extracted_dir, new_pck_path, src_pck=None):
    """Preserve source engine/format version and write a matching index layout."""
    version = read_header_index(src_pck)[0] if src_pck else (2, 4, 0, 0)
    fmt = version[0]
    items = []
    for rel, full in sorted(collect_files(extracted_dir).items()):
        vb = ('res://' + rel).encode('utf-8')
        vb += bytes((-len(vb)) % 4)
        with open(full, 'rb') as f:
            md5 = hashlib.file_digest(f, 'md5').digest()
        items.append((vb, full, os.path.getsize(full), md5))
    header_size = 88 if fmt == 1 else (100 if fmt == 2 else 108)
    base = header_size + sum(4 + len(vb) + 32 + (4 if fmt >= 2 else 0) for vb, _, _, _ in items)
    base = (base + 15) & ~15
    offsets = []
    cur = base
    for _, _, size, _ in items:
        offsets.append(cur)
        cur = (cur + size + 15) & ~15
    target = os.path.abspath(new_pck_path)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    fd, staged = tempfile.mkstemp(prefix='.pck_', dir=os.path.dirname(target))
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(GDPC_MAGIC + struct.pack('<4I', *version))
            if fmt >= 2:
                out.write(struct.pack('<IQ', 2, base))
                if fmt >= 3:
                    out.write(struct.pack('<Q', 104))
            out.write(bytes(64))
            out.write(struct.pack('<I', len(items)))
            for (vb, _, size, md5), offset in zip(items, offsets):
                out.write(struct.pack('<I', len(vb)) + vb)
                out.write(struct.pack('<QQ', offset if fmt == 1 else offset - base, size) + md5)
                if fmt >= 2:
                    out.write(struct.pack('<I', 0))
            for (_, full, size, _), offset in zip(items, offsets):
                out.write(bytes(offset - out.tell()))
                with open(full, 'rb') as f:
                    _copy_bytes(f, out, size)
        os.replace(staged, target)
    finally:
        if os.path.exists(staged):
            os.unlink(staged)

def build_vpk(patched_pck_path, template_dir, content_dir, output_vpk):
    """Assemble a full VPK: copy template → content_dir, inject patched .pck, zip to output_vpk."""
    if not os.path.isdir(template_dir):
        raise FileNotFoundError(f"VPK template '{template_dir}' not found")
    # clean content_dir
    if os.path.isdir(content_dir):
        shutil.rmtree(content_dir)
    shutil.copytree(template_dir, content_dir)
    # Godot 4 Vita loads game.pck beside eboot.bin; Godot 3 uses game_data.
    version, _, _ = read_header_index(patched_pck_path)
    if version[1] >= 4:
        pack_dir = content_dir
        stale_pack = os.path.join(content_dir, 'game_data', 'game.pck')
    else:
        pack_dir = os.path.join(content_dir, 'game_data')
        stale_pack = os.path.join(content_dir, 'game.pck')
    if os.path.isfile(stale_pack):
        os.remove(stale_pack)
    os.makedirs(pack_dir, exist_ok=True)
    shutil.copy2(patched_pck_path, os.path.join(pack_dir, 'game.pck'))
    # zip up with 0777 perms
    with zipfile.ZipFile(output_vpk, 'w', compression=zipfile.ZIP_STORED) as zf:
        for root, dirs, files in os.walk(content_dir):
            for d in dirs:
                full = os.path.join(root, d)
                rel  = os.path.relpath(full, content_dir).replace(os.sep, '/')
                if not rel.endswith('/'):
                    rel += '/'
                zi = zipfile.ZipInfo(rel)
                zi.external_attr = (0o777 << 16) | 0x10
                zf.writestr(zi, b'')
            for f in files:
                full = os.path.join(root, f)
                rel  = os.path.relpath(full, content_dir).replace(os.sep, '/')
                zi = zipfile.ZipInfo(rel)
                zi.external_attr = (0o777 << 16)
                data = open(full, 'rb').read()
                zf.writestr(zi, data)

def hash_file(path):
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b''):
            h.update(chunk)
    return h.hexdigest()

def collect_files(root_dir):
    """Walk root_dir and return dict of relative_path -> full_path."""
    files = {}
    for dirpath, _, filenames in os.walk(root_dir):
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root_dir).replace("\\", "/")
            files[rel] = full
    return files

def create_patch(src_orig, src_patched, output_folder):
    """Compare actual payload bytes and stage changed files before replacing output."""
    src_orig, src_patched = resolve_source(src_orig), resolve_source(src_patched)
    _, _, original = read_header_index(src_orig)
    _, _, patched = read_header_index(src_patched)
    output_folder = os.path.realpath(output_folder)
    for source in (src_orig, src_patched):
        if os.path.splitdrive(output_folder)[0].lower() == os.path.splitdrive(os.path.realpath(source))[0].lower() and os.path.commonpath((output_folder, os.path.realpath(source))) == output_folder:
            raise ValueError("Patch output folder must not contain either input file.")
    parent = os.path.dirname(output_folder)
    os.makedirs(parent, exist_ok=True)
    changed = 0
    with tempfile.TemporaryDirectory(prefix='.patch_', dir=parent) as staged:
        with open(src_orig, 'rb') as old, open(src_patched, 'rb') as new:
            for path, (offset, size) in patched.items():
                same = False
                if path in original and original[path][1] == size:
                    old.seek(original[path][0]); new.seek(offset)
                    remaining = size
                    same = True
                    while remaining:
                        n = min(remaining, 1024 * 1024)
                        if _read(old, n) != _read(new, n):
                            same = False
                            break
                        remaining -= n
                if not same:
                    dest = safe_path(staged, path)
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    new.seek(offset)
                    with open(dest, 'wb') as out:
                        _copy_bytes(new, out, size)
                    changed += 1
        # Only replace files owned by the previous patch; preserve a backup on disk.
        if os.path.exists(output_folder):
            backup = output_folder + '.backup-' + __import__('uuid').uuid4().hex[:8]
            os.rename(output_folder, backup)
        os.rename(staged, output_folder)
        os.makedirs(staged)  # TemporaryDirectory owns this path.
    return changed, len(set(original) - set(patched))


class PatchGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PCK Patch Tool")
        self.worker = ThreadPoolExecutor(max_workers=1)
        self.busy = False
        self.geometry("680x560")
        
        frm1 = tk.LabelFrame(self, text="Create Patch", padx=10, pady=10)
        frm1.pack(fill="x", padx=10, pady=5)

        tk.Label(frm1, text="Original (.pck/.exe):").grid(row=0, column=0, sticky="e")
        self.orig_pck_var = tk.StringVar()
        tk.Entry(frm1, textvariable=self.orig_pck_var, width=50).grid(row=0, column=1)
        tk.Button(frm1, text="Browse...", command=self.browse_orig_pck).grid(row=0, column=2)

        tk.Label(frm1, text="Patched (.pck/.exe):").grid(row=1, column=0, sticky="e")
        self.patched_pck_var = tk.StringVar()
        tk.Entry(frm1, textvariable=self.patched_pck_var, width=50).grid(row=1, column=1)
        tk.Button(frm1, text="Browse...", command=self.browse_patched_pck).grid(row=1, column=2)

        tk.Label(frm1, text="Patch Folder:").grid(row=2, column=0, sticky="e")
        self.patch_folder_var = tk.StringVar()
        tk.Entry(frm1, textvariable=self.patch_folder_var, width=50).grid(row=2, column=1)
        tk.Button(frm1, text="Browse...", command=self.browse_patch_folder).grid(row=2, column=2)

        tk.Button(frm1, text="Create Patch", bg="#4CAF50", fg="white",
                  command=self.on_create_patch).grid(row=3, column=1, pady=10)

        frm2 = tk.LabelFrame(self, text="Apply Patch", padx=10, pady=10)
        frm2.pack(fill="x", padx=10, pady=5)

        tk.Label(frm2, text="Original (.pck/.exe):").grid(row=0, column=0, sticky="e")
        self.apply_orig_var = tk.StringVar()
        tk.Entry(frm2, textvariable=self.apply_orig_var, width=50).grid(row=0, column=1)
        tk.Button(frm2, text="Browse...", command=self.browse_apply_orig).grid(row=0, column=2)

        tk.Label(frm2, text="Patch Folder:").grid(row=1, column=0, sticky="e")
        self.apply_patch_var = tk.StringVar()
        tk.Entry(frm2, textvariable=self.apply_patch_var, width=50).grid(row=1, column=1)
        tk.Button(frm2, text="Browse...", command=self.browse_apply_patch).grid(row=1, column=2)

        tk.Label(frm2, text="Output .pck:").grid(row=2, column=0, sticky="e")
        self.output_pck_var = tk.StringVar(value="game_merged.pck")
        tk.Entry(frm2, textvariable=self.output_pck_var, width=50).grid(row=2, column=1)
        tk.Button(frm2, text="Save As...", command=self.save_output_pck).grid(row=2, column=2)

        self.build_vpk_var = tk.BooleanVar()
        cb = tk.Checkbutton(frm2, text="Build VPK after repack", variable=self.build_vpk_var,
                            command=self.toggle_vpk_options)
        cb.grid(row=3, column=1, sticky="w")

        tk.Label(frm2, text="VPK Template:").grid(row=4, column=0, sticky="e")
        self.vpk_template_var = tk.StringVar()
        self.vpk_template_entry = tk.Entry(frm2, textvariable=self.vpk_template_var, width=50, state="disabled")
        self.vpk_template_entry.grid(row=4, column=1)
        self.vpk_template_btn = tk.Button(frm2, text="Browse...", command=self.browse_vpk_template, state="disabled")
        self.vpk_template_btn.grid(row=4, column=2)

        tk.Label(frm2, text="Output .vpk:").grid(row=5, column=0, sticky="e")
        self.output_vpk_var = tk.StringVar(value="game.vpk")
        self.output_vpk_entry = tk.Entry(frm2, textvariable=self.output_vpk_var, width=50, state="disabled")
        self.output_vpk_entry.grid(row=5, column=1)
        self.output_vpk_btn = tk.Button(frm2, text="Save As...", command=self.save_output_vpk, state="disabled")
        self.output_vpk_btn.grid(row=5, column=2)

        tk.Button(frm2, text="Apply Patch", bg="#2196F3", fg="white",
                  command=self.on_apply_patch).grid(row=6, column=1, pady=10)

    def browse_orig_pck(self):
        path = filedialog.askopenfilename(title="Select original .pck or .exe", filetypes=PCK_EXE_FILETYPES)
        if path: self.orig_pck_var.set(path)

    def browse_patched_pck(self):
        path = filedialog.askopenfilename(title="Select patched .pck or .exe", filetypes=PCK_EXE_FILETYPES)
        if path: self.patched_pck_var.set(path)

    def browse_patch_folder(self):
        path = filedialog.askdirectory(title="Select output patch folder")
        if path: self.patch_folder_var.set(path)

    def browse_apply_orig(self):
        path = filedialog.askopenfilename(title="Select original .pck or .exe", filetypes=PCK_EXE_FILETYPES)
        if path: self.apply_orig_var.set(path)

    def browse_apply_patch(self):
        path = filedialog.askdirectory(title="Select patch folder")
        if path: self.apply_patch_var.set(path)

    def save_output_pck(self):
        path = filedialog.asksaveasfilename(title="Save merged .pck as", defaultextension=".pck",
                                            filetypes=[("PCK files","*.pck")])
        if path: self.output_pck_var.set(path)

    def browse_vpk_template(self):
        path = filedialog.askdirectory(title="Select VPK template folder")
        if path: self.vpk_template_var.set(path)

    def save_output_vpk(self):
        path = filedialog.asksaveasfilename(title="Save .vpk as", defaultextension=".vpk",
                                            filetypes=[("VPK files","*.vpk")])
        if path: self.output_vpk_var.set(path)

    def toggle_vpk_options(self):
        state = "normal" if self.build_vpk_var.get() else "disabled"
        for widget in (self.vpk_template_entry, self.vpk_template_btn,
                       self.output_vpk_entry, self.output_vpk_btn):
            widget.config(state=state)

    def on_create_patch(self):
        orig = self.orig_pck_var.get()
        patched = self.patched_pck_var.get()
        out = self.patch_folder_var.get()
        if not (os.path.isfile(orig) and os.path.isfile(patched)):
            messagebox.showerror("Error", "Please select two valid .pck or .exe files.")
            return
        if not out:
            messagebox.showerror("Error", "Please select an output patch folder.")
            return
        if self.busy:
            return
        self.busy = True
        self.title("PCK Patch Tool - Comparing files...")
        future = self.worker.submit(create_patch, orig, patched, out)

        def poll():
            if not future.done():
                self.after(100, poll)
                return
            self.busy = False
            self.title("PCK Patch Tool")
            try:
                changed, removed = future.result()
                messagebox.showinfo("Success", f"Patch created in:\n{out}\nNew/changed files: {changed}\nFiles absent from patched PCK: {removed} (not deleted by folder patches)")
            except Exception as e:
                messagebox.showerror("Error creating patch", str(e))
        self.after(100, poll)

    def on_apply_patch(self):
        if self.busy:
            return
        orig = self.apply_orig_var.get()
        patch = self.apply_patch_var.get()
        out_pck = self.output_pck_var.get()
        if not (os.path.isfile(orig) and os.path.isdir(patch)):
            messagebox.showerror("Error", "Please select a valid original file and patch folder.")
            return
        try:
            # extract and merge
            tmp = tempfile.mkdtemp()
            extract_pck(orig, tmp)
            
            # merge patch
            for root, _, files in os.walk(patch):
                for fn in files:
                    src = os.path.join(root, fn)
                    rel = os.path.relpath(src, patch)
                    dst = os.path.join(tmp, rel)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(src, dst)
                    
            # repack
            repack_pck(tmp, out_pck, src_pck=orig)
            
            # optionally build VPK
            if self.build_vpk_var.get():
                tpl = self.vpk_template_var.get()
                out_vpk = self.output_vpk_var.get()
                content_tmp = tempfile.mkdtemp()
                try:
                    build_vpk(out_pck, tpl, content_tmp, out_vpk)
                finally:
                    shutil.rmtree(content_tmp, ignore_errors=True)
                messagebox.showinfo("Done", f"Repacked .pck → {out_pck}\nBuilt .vpk → {out_vpk}")
            else:
                messagebox.showinfo("Done", f"Repacked .pck → {out_pck}")
        except Exception as e:
            messagebox.showerror("Error applying patch", str(e))
        finally:
            if 'tmp' in locals() and os.path.isdir(tmp):
                shutil.rmtree(tmp)

if __name__ == "__main__":
    app = PatchGUI()
    app.mainloop()