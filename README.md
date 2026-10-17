# VaultShare

VaultShare is a Flask-based file management and sharing project for a BCA minor project.

## Features

- User registration and login
- File upload, download and management
- Shareable file links and QR codes
- Favorites, trash, profile, settings and security pages
- Dark and refined lavender light themes
- Document analysis for TXT, PDF and PPTX using the Gemini API
- Dedicated AI Tools page

## Setup (Windows)

1. Install Python 3.10 or newer.
2. Open a terminal in this folder.
3. Create and activate a virtual environment if you do not already have one:
   ```powershell
   py -m venv venv
   .\venv\Scripts\Activate.ps1
   ```
4. Install dependencies:
   ```powershell
   pip install -r requirements.txt
   ```
5. Copy `.env.example` to `.env` and set your Google AI Studio key:
   ```env
   GEMINI_API_KEY=your_actual_key
   GEMINI_MODEL=gemini-3.8-flash
   ```
6. Run:
   ```powershell
   python app.py
   ```

The app creates `database.db` and the `storage` folder beside `app.py` if they do not exist. Existing database and storage files should be backed up before replacing project code.

## Notes

- Do not upload `.env`, `database.db`, uploaded files, or the virtual environment to a public repository.
- QR codes encode the generated share link. A recipient needs network access to the host running VaultShare; `127.0.0.1` links only work on the same device.
- Gemini analysis requires a valid API key, an available model, internet access and remaining API quota.


## Recent improvements

- Recently opened files are shown on the dashboard after previewing or downloading.
- Image, PDF and plain-text previews are available from My Files.
- Share links can be configured to expire or be revoked.
- Activity History records uploads, previews, downloads, trash actions and share-link changes.
- Storage values use one byte formatter for used, available and total space.
