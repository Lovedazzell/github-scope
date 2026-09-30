# GitScope

A local, open-source web app for browsing and comparing git branches, editing files on any local branch, and hard-resetting safely while keeping the files you care about.

## Run it
```
python run.py
```
Needs Python 3.9+ and Git. The launcher creates a `.venv`, installs `requirements.txt`, starts the server on `http://127.0.0.1:8765` and opens your browser. Set `PORT` to change the port. The server only listens on localhost.

## Features
- Open any repo by folder path (remembered next time)
- **ⓘ Info**: remote URL, status, last commit with changed files, recent commits, **Fetch origin**, stash list with **Restore**
- **Compare branches**: pick any two local or `origin/*` branches; the tree marks files and folders that differ with a red dot
- Side-by-side editors; **Commit** to either local branch, even if it isn't checked out (working tree untouched)
- **Pin** files once: they're backed up before every hard reset and optionally restored afterwards, on every branch, with no re-selecting
- **Hard reset** with a checkbox: put pinned files back, or reset cleanly and bring nothing back
- **Backup** any file version from any branch; restore from the Info panel
- Backups and pins live in `.git/gitscope/` and are never committed


Hard reset asks for confirmation and shows the old HEAD hash so you can undo with `git reset --hard <hash>`.


