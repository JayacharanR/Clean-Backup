import shutil
from pathlib import Path
from collections import defaultdict
from src import constants
from src.metadata import get_image_date, get_video_date, get_file_modification_date
from src.logger import logger

def organise_files(src_dir, dest_dir):
    src_path = Path(src_dir)
    dest_path = Path(dest_dir)
    
    # Statistics tracking
    stats = {
        'total_scanned': 0,
        'images': 0,
        'videos': 0,
        'other': 0,
        'duplicates': 0,
        'moved': 0,
        'errors': 0,
        'folders_created': defaultdict(int)  # {"2022/November": count}
    }
    
    for file_path in src_path.rglob('*'):  # recursive glob search 
        if file_path.is_file():
            stats['total_scanned'] += 1
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

            # move to target dest
            if target_file.exists():
                stats['duplicates'] += 1
                logger.info(f"Skipped duplicate: {file_path.name} already exists in {target_folder}")
            else:
                try:
                    shutil.move(str(file_path), str(target_file))
                    stats['moved'] += 1
                    stats['folders_created'][folder_key] += 1
                    logger.info(f"Moved: {file_path.name} -> {target_folder}")
                except Exception as e:
                    stats['errors'] += 1
                    logger.error(f"Error moving {file_path.name}: {e}")
    
    return stats


def print_summary(stats):
    """Print a formatted summary report of the organization operation."""
    print("\n" + "=" * 50)
    print("           📊 SUMMARY REPORT")
    print("=" * 50)
    
    # Format numbers with commas for readability
    total = f"{stats['total_scanned']:,}"
    images = f"{stats['images']:,}"
    videos = f"{stats['videos']:,}"
    moved = f"{stats['moved']:,}"
    duplicates = f"{stats['duplicates']:,}"
    
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
        print(f"\n⚠️  {duplicates} duplicates detected (skipped)")
    
    # Show errors if any
    if stats['errors'] > 0:
        print(f"\n❌ {stats['errors']:,} errors occurred")
    
    print(f"\n✨ {moved} files successfully moved!")
    print("=" * 50 + "\n")

if __name__ == "__main__":
    # Example usage
    source = input("Enter source folder path: ")
    destination = input("Enter destination folder path: ")
    organise_files(source, destination)