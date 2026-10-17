# VaultShare — Secure File Sharing Web App

VaultShare is a Flask-based web application designed to make file management and sharing simple. It provides a modern interface for uploading, organizing, analyzing, and sharing files.

## Live Demo
https://vaultshare-pj6y.onrender.com

## Features
- User registration and login
- File upload and download
- File management and deletion
- File sharing links
- Favorites and Trash
- File previews
- AI-powered document analysis using Google Gemini
- Storage usage dashboard
- Activity history
- Responsive dark-themed interface

## Technology Stack
- **Frontend:** HTML, CSS, JavaScript
- **Backend:** Python, Flask
- **Database:** SQLite
- **AI Integration:** Google Gemini API
- **Hosting:** Render

## Run Locally

1. Clone the repository:

   ```bash
   git clone https://github.com/vizer770/VaultShare.git
   cd VaultShare
   ```

2. Create and activate a virtual environment:

   ```bash
   python -m venv venv
   ```

   Windows PowerShell:

   ```powershell
   .\venv\Scripts\Activate.ps1
   ```

3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Create a `.env` file with your configuration:

   ```env
   SECRET_KEY=your-random-secret-key
   GEMINI_API_KEY=your-gemini-api-key
   ```

   Replace the placeholder values with your own secrets. Never commit the `.env` file.

5. Run the application:

   ```bash
   python app.py
   ```

## Security Note
Do not commit API keys, secret keys, user databases, uploaded files, or virtual environment files to GitHub.

## Project Purpose
Developed as an academic project to demonstrate web development, backend programming, database integration, file handling, and AI integration.
