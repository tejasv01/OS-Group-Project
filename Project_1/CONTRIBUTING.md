# Developer Setup and Team Workflow

## 1. Python environment (one-time, per person)

From the repo root:

```bash
python3 -m venv .venv
source .venv/bin/activate        # run this in every new terminal
pip install --upgrade pip
pip install -r requirements.txt
```

Check it worked:

```bash
python -c "import fuse; print('fusepy OK')"
```

Leave the environment with `deactivate`.

## 2. Adding or updating dependencies

If you install a new package, record it so everyone gets the same versions:

```bash
pip install <package>
pip freeze > requirements.txt
```

Commit `requirements.txt` in the same commit as the code that needs it.
After pulling changes from others, re-sync with:

```bash
pip install -r requirements.txt
```

Never commit the `.venv/` folder (it is in `.gitignore`).

## 3. System packages (Ubuntu)

```bash
sudo apt-get install -y fuse3 libfuse3-dev pkg-config python3-venv python3-pip \
    qemu-system-riscv gcc-riscv64-linux-gnu binutils-riscv64-linux-gnu
```

On older Ubuntu/Debian use `qemu-system-misc` instead of `qemu-system-riscv`.

## 4. Disk images

- Keep a clean copy: `cp fs.img fs.clean.img`. Reset with `cp fs.clean.img fs.img`.
- Do not commit `*.img` files.
- Unmount before booting xv6 on the same image: `fusermount3 -u <mountpoint>`.
- Never run FUSE and QEMU on the same image simultaneously.

## 5. Git workflow

- Work on a branch: `git checkout -b <yourname>/<feature>`.
- Pull before you push: `git pull --rebase origin main`.
- Open a pull request; at least one teammate reviews before merging.
- Keep commits small, with clear messages.

## 6. Troubleshooting

- `ModuleNotFoundError: fuse`: the venv is not active, or `pip install -r requirements.txt` was not run.
- `Transport endpoint is not connected`: a previous mount crashed. Run `fusermount3 -u <mountpoint>`.
- `/dev/fuse: Permission denied`: make sure `fuse3` is installed and you are in the `fuse` group if your distro requires it.