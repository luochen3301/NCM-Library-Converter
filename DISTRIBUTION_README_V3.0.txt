NCM Library Converter V3.0 - Windows Portable Release
======================================================

1. Extract the ZIP to a writable folder.
2. Run "NCM Converter.exe".
3. Choose your music library folder, scan it, then convert pending NCM files.
4. Optional: open Tools > FLAC -> MP3, then choose or drag in files/folders to create MP3 copies.

Important
---------
- The NCM workflow decrypts the original audio stream stored in each NCM file and does not transcode it.
- The separate FLAC -> MP3 tool transcodes only files you explicitly add. It always keeps the source FLAC.
- FLAC -> MP3 uses bundled SoundFile/libsndfile and lameenc/LAME components; no system FFmpeg installation is required.
- The FLAC tool has its own focused controls. After conversion, right-click a finished row and choose "Show MP3 in folder" to reveal the exact output file.
- Your existing V2.x library index, history, and settings are upgraded automatically.
- Completed conversion batches are automatically deselected; search remains available while selecting files.
- Live task text stays separated from pause/cancel controls, and all application scrollbars use the V3 visual style.
- "Delete source after success" is disabled by default. Enable it only after verifying your outputs and backups.
- Windows SmartScreen may warn because the executable is not commercially code-signed.

Portable data
-------------
Application state is normally stored at:
  %APPDATA%\ncmdump\ncmdump.sqlite3

Package contents
----------------
- NCM Converter.exe
- VERSION
- LICENSE
- RELEASE_NOTES_V3.0.md
- DISTRIBUTION_README_V3.0.txt
- SHA256SUMS.txt

This software is intended for lawful processing of files you are authorized to use.

Third-party audio components
----------------------------
- python-soundfile: BSD-3-Clause; bundled libsndfile: LGPL-2.1-or-later.
  Source and license information: https://github.com/bastibe/python-soundfile
  libsndfile source and license information: https://github.com/libsndfile/libsndfile
- lameenc / LAME: LGPL-3.0-or-later.
  Source and license information: https://github.com/chrisstaite/lameenc
