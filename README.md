# Clean-Backup

**Clean-Backup** is a lightweight, pure-Python automation tool designed to organize your photo and video collections. It scans your media files, extracts their creation dates (using EXIF data for images and metadata for videos), and sorts them into a structured `Year/Month` directory hierarchy.

This project is built with open-source principles in mind, avoiding heavy external dependencies like FFmpeg in favor of reliable Python libraries.

## 🚀 Features

- **Automatic Sorting**: Moves files into `Destination/Year/Month/` folders.
- **Metadata Extraction**:
  - **Images**: Extracts EXIF `DateTimeOriginal` (supports JPG, PNG, TIFF, BMP, GIF).
  - **HEIC Support**: Native support for Apple's High Efficiency Image Format.
  - **Videos**: Extracts creation date metadata (supports MP4, MOV, AVI, MKV, etc.).
- **Smart Fallback**: Uses file system modification time if metadata is missing.
- **Duplicate Handling**: Skips files if they already exist in the destination to prevent overwrites.
- **Summary Report**: Displays a detailed summary after organization completes.
- **Logging**: Generates detailed logs of all operations in the `logs/` directory.
- **Pure Python**: Easy to install and run without complex system dependencies.

## 📋 Supported Formats

- **Images**: `.jpg`, `.jpeg`, `.png`, `.heic`, `.bmp`, `.tiff`, `.gif`, `.raf`
- **Videos**: `.mp4`, `.mov`, `.avi`, `.mkv`, `.wmv`, `.flv`, `.webm`

## 🛠️ Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/JayacharanR/Clean-Backup.git
   cd Clean-Backup
   ```

2. **Set up a virtual environment (Recommended)**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

## 💻 Usage

Run the main script from the terminal:

```bash
python main.py
```

Follow the interactive prompts:
1. Enter the **Source Folder Path** (where your messy files are).
2. Enter the **Destination Folder Path** (where you want them organized).

The script will process the files and generate a log file in the `logs/` folder.

### 📊 Summary Report

After organization completes, you'll see a detailed summary, Example snippet:
```
==================================================
           📊 SUMMARY REPORT
==================================================

✅ 1,240 files scanned
📸 820 images
🎥 420 videos

🗂  Organized into:
   - 2022/November (340 files)
   - 2023/May (210 files)

⚠️  34 duplicates detected (skipped)

✨ 1,186 files successfully moved!
==================================================
```

## 📂 Project Structure

```
Clean-Backup/
├── logs/                   # Log files generated 
├── src/                    # Source code
│   ├── __init__.py
│   ├── constants.py        # Configuration for 
│   ├── logger.py           # Logging setup
│   ├── metadata.py         # Metadata extraction 
│   └── organiser.py        # Core file 
├── main.py                 # Entry point
├── requirements.txt        # Python dependencies
└── README.md               # Documentation
```

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the project
2. Create your feature branch (`git checkout -b feature/Feature`)
3. Commit your changes (`git commit -m 'Add some Feature'`)
4. Push to the branch (`git push origin feature/Feature`)
5. Open a Pull Request

## 📄 License

This project is open source and available under the [MIT License](LICENSE).
