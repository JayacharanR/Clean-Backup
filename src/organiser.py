import shutil
import re
from pathlib import Path
from collections import defaultdict
from src import constants
from src.metadata import get_image_date, get_video_date, get_file_modification_date
from src.logger import logger
from src.phash import find_duplicates, find_duplicates_from_paths, is_rust_available, THRESHOLD_SIMILAR
from src.undo_manager import undo_manager

def detect_name_based_duplicates(file_paths):
    """
    Detect duplicate files based on common naming patterns from various OS.
    
    Patterns detected:
    - Windows (Download): photo (1).jpg, photo (2).jpg
    - Generic: photo-1.jpg, photo_1.jpg
    - macOS (Duplicate): photo copy.jpg, photoCopy.jpg
    - Windows (Copy): Notes - Copy.txt
    - Linux (Nautilus): Data (copy).csv
    - macOS (Drag/Drop): Image 2.png, Image 3.png
    
    Args:
        file_paths: List of Path objects
        
    Returns:
        set: Paths that should be considered duplicates (keeps original without suffix)
    """
    duplicate_files = set()
    base_name_groups = defaultdict(list)
    
    # Regex patterns to detect duplicate suffixes (order matters - most specific first)
    patterns = [
        r'\s*\((\d+)\)$',                          # (1), (2) - Windows/Android/iOS downloads
        r'\s*\(copy\)$',                           # (copy) - Linux Nautilus
        r'\s*-\s*Copy(\d*)$',                      # - Copy, - Copy2 - Windows
        r'\s+copy(\d*)$',                          # copy, copy2 - macOS (space before)
        r'[-_]copy(\d*)$',                         # -copy, _copy - generic
        r'[-_]Copy(\d*)$',                         # -Copy, _Copy - generic
        r'[-_]COPY(\d*)$',                         # -COPY, _COPY - generic  
        r'[-_](\d+)$',                             # -1, _1 - generic
        r'\s+(\d+)$',                              # (space)2, (space)3 - macOS drag/drop
    ]
    
    # Examples of matched patterns:
    # "Installer (1).exe" → base: "Installer.exe"
    # "Data (copy).csv" → base: "Data.csv"
    # "Notes - Copy.txt" → base: "Notes.txt"
    # "Image copy.png" → base: "Image.png"
    # "Photo_1.jpg" → base: "Photo.jpg"
    # "Image 2.png" → base: "Image.png"
    
    for file_path in file_paths:
        if not file_path.is_file():
            continue
            
        stem = file_path.stem  # filename without extension
        suffix = file_path.suffix
        
        # Try to extract base name by removing duplicate suffixes
        base_name = stem
        is_duplicate = False
        
        for pattern in patterns:
            match = re.search(pattern, stem, re.IGNORECASE)
            if match:
                # Remove the duplicate suffix to get base name
                base_name = re.sub(pattern, '', stem, flags=re.IGNORECASE)
                is_duplicate = True
                break
        
        # Group files by base name + extension
        key = f"{base_name}{suffix}".lower()
        base_name_groups[key].append((file_path, is_duplicate, stem))
    
    # Analyze groups to find duplicates
    for base_key, files in base_name_groups.items():
        if len(files) > 1:
            # Sort: originals (no suffix) first, then by name
            files.sort(key=lambda x: (x[1], x[2]))  # (is_duplicate, stem)
            
            # Keep the first file (original without suffix), mark rest as duplicates
            for file_path, is_dup, stem in files[1:]:
                duplicate_files.add(file_path)
                logger.info(f"Name-based duplicate detected: {file_path.name} (base: {base_key})")
    
    return duplicate_files

def organise_files(src_dir, dest_dir, operation='move', check_duplicates=False, duplicate_threshold=THRESHOLD_SIMILAR, check_name_duplicates=False):
    """
    Organize media files into year/month folders.
    
    Args:
        src_dir: Source directory
        dest_dir: Destination directory
        operation: 'move' or 'copy'
        check_duplicates: If True, detect and skip duplicate images before organizing (perceptual hashing)
        duplicate_threshold: Hamming distance threshold for duplicate detection
        check_name_duplicates: If True, detect and skip files with duplicate naming patterns (e.g., photo(1).jpg)
    """
    src_path = Path(src_dir)
    dest_path = Path(dest_dir)
    
    undo_manager.start_session()

    # Statistics tracking
    stats = {
        'total_scanned': 0,
        'images': 0,
        'videos': 0,
        'other': 0,
        'duplicates': 0,
        'perceptual_duplicates': 0,
        'name_duplicates': 0,
        'processed': 0,
        'errors': 0,
        'folders_created': defaultdict(int)  # {"2022/November": count}
    }
    
    # Name-based duplicate detection (if enabled)
    name_duplicate_files = set()
    if check_name_duplicates:
        logger.info("Scanning for name-based duplicates (e.g., photo(1).jpg)...")
        all_files = list(src_path.rglob('*'))
        name_duplicate_files = detect_name_based_duplicates(all_files)
        stats['name_duplicates'] = len(name_duplicate_files)
        logger.info(f"Found {len(name_duplicate_files)} name-based duplicates")
    
    # Perceptual duplicate detection (if enabled)
    duplicate_files = set()  # Files to skip due to perceptual duplication
    if check_duplicates:
        logger.info(f"Scanning for perceptual duplicates using {'Rust (phash_rs)' if is_rust_available() else 'Python fallback'}...")
        
        # Collect source images
        src_images = []
        for p in src_path.rglob('*'):
            if p.is_file() and p.suffix.lower() in constants.IMAGE_EXTENSIONS:
                src_images.append(str(p.resolve()))

        # Collect destination images to check against
        dest_images_set = set()
        all_images = list(src_images)
        
        if dest_path.exists():
            logger.info("Including destination folder in duplicate scan...")
            for p in dest_path.rglob('*'):
                if p.is_file() and p.suffix.lower() in constants.IMAGE_EXTENSIONS:
                    abs_path = str(p.resolve())
                    all_images.append(abs_path)
                    dest_images_set.add(abs_path)
        
        duplicate_groups = find_duplicates_from_paths(all_images, threshold=duplicate_threshold)
        
        if duplicate_groups:
            logger.info(f"Found {len(duplicate_groups)} duplicate groups")
            for group in duplicate_groups:
                # Check if group has any file in destination
                group_has_dest = any(p in dest_images_set for p in group.paths)
                
                if group_has_dest:
                    # If duplicate exists in destination, skip ALL source files in this group
                    # (We assume destination files are preferred)
                    for path in group.paths:
                        if path not in dest_images_set:
                            duplicate_files.add(Path(path).resolve())
                            stats['perceptual_duplicates'] += 1
                    logger.info(f"Duplicate group found in destination: skipping source files")
                else:
                    # Mark all duplicates except the best one (source-only group)
                    for dup_path in group.duplicates:
                        # Use absolute path for consistent comparison
                        duplicate_files.add(Path(dup_path).resolve())
                        stats['perceptual_duplicates'] += 1
                    logger.info(f"Duplicate group: keeping {group.best}, skipping {len(group.duplicates)} duplicates")
        else:
            logger.info("No perceptual duplicates found")
    
    for file_path in src_path.rglob('*'):  # recursive glob search 
        if file_path.is_file():
            stats['total_scanned'] += 1
            
            # Skip name-based duplicates
            if check_name_duplicates and file_path in name_duplicate_files:
                logger.info(f"Skipping name-based duplicate: {file_path.name}")
                continue
            
            # Skip perceptual duplicates (use absolute path for comparison)
            if check_duplicates and file_path.resolve() in duplicate_files:
                logger.info(f"Skipping perceptual duplicate: {file_path.name}")
                continue
            
            ext = file_path.suffix.lower()
            
            # Track file type
            is_image = ext in constants.IMAGE_EXTENSIONS
            is_video = ext in constants.VIDEO_EXTENSIONS
            
            if is_image:
                stats['images'] += 1
            elif is_video:
                stats['videos'] += 1
            else:
                stats['other'] += 1
                continue  # Skip non-media files
            
            # get date
            date_taken = None
            
            if is_image:
                date_taken = get_image_date(str(file_path))
            elif is_video:
                date_taken = get_video_date(str(file_path))
            
            # if date not available assign current system date
            if date_taken is None:
                date_taken = get_file_modification_date(str(file_path))
                logger.info(f"Used current file system date for: {file_path.name}")
                
            # create target dest
            year_folder = date_taken.strftime('%Y')
            month_folder = date_taken.strftime('%B')
            
            folder_key = f"{year_folder}/{month_folder}"
            
            target_folder = dest_path / year_folder / month_folder
            target_folder.mkdir(parents=True, exist_ok=True)
            
            target_file = target_folder / file_path.name

            # transfer to target dest (move or copy)
            if target_file.exists():
                stats['duplicates'] += 1
                logger.info(f"Skipped duplicate: {file_path.name} already exists in {target_folder}")
            else:
                try:
                    if operation == 'copy':
                        shutil.copy2(str(file_path), str(target_file))
                        logger.info(f"Copied: {file_path.name} -> {target_folder}")
                        undo_manager.log_action('copy', file_path, target_file)
                    else:
                        shutil.move(str(file_path), str(target_file))
                        logger.info(f"Moved: {file_path.name} -> {target_folder}")
                        undo_manager.log_action('move', file_path, target_file)
                    stats['processed'] += 1
                    stats['folders_created'][folder_key] += 1
                except Exception as e:
                    stats['errors'] += 1
                    logger.error(f"Error {operation}ing {file_path.name}: {e}")
    
    undo_manager.end_session()
    return stats


def print_summary(stats, operation='move'):
    """Print a formatted summary report of the organization operation."""
    print("\n" + "=" * 50)
    print("           📊 SUMMARY REPORT")
    print("=" * 50)
    
    # Format numbers with commas for readability
    total = f"{stats['total_scanned']:,}"
    images = f"{stats['images']:,}"
    videos = f"{stats['videos']:,}"
    processed = f"{stats['processed']:,}"
    duplicates = f"{stats['duplicates']:,}"
    
    # Determine action word based on operation
    action_word = "copied" if operation == 'copy' else "moved"
    
    print(f"\n✅ {total} files scanned")
    print(f"📸 {images} images")
    print(f"🎥 {videos} videos")
    
    if stats['other'] > 0:
        print(f"📄 {stats['other']:,} other files (skipped)")
    
    # Show folders created with file counts
    if stats['folders_created']:
        print(f"\n🗂  Organized into:")
        for folder, count in sorted(stats['folders_created'].items()):
            print(f"   - {folder} ({count:,} files)")
    
    # Show duplicates warning
    if stats['duplicates'] > 0:
        print(f"\n⚠️  {duplicates} exact filename duplicates detected (skipped)")
    
    # Show name-based duplicates
    if stats.get('name_duplicates', 0) > 0:
        print(f"📝 {stats['name_duplicates']:,} OS duplicate patterns detected (Windows/macOS/Linux)")
    
    # Show perceptual duplicates
    if stats.get('perceptual_duplicates', 0) > 0:
        print(f"🔍 {stats['perceptual_duplicates']:,} perceptual duplicates detected (skipped)")
    
    # Show errors if any
    if stats['errors'] > 0:
        print(f"\n❌ {stats['errors']:,} errors occurred")
    
    print(f"\n✨ {processed} files successfully {action_word}!")
    print("=" * 50 + "\n")

if __name__ == "__main__":
    # Example usage
    source = input("Enter source folder path: ")
    destination = input("Enter destination folder path: ")
    organise_files(source, destination)