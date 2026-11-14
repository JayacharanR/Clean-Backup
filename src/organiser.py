from pathlib import Path
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from multiprocessing import cpu_count
from tqdm import tqdm
from src import constants
from src.metadata import get_image_date, get_video_date, get_file_modification_date
from src.logger import logger
from src.phash import find_duplicates_from_paths, is_rust_available, THRESHOLD_SIMILAR
from src.undo_manager import UndoManager
from src.file_operations import file_identity, validate_roots, verified_transfer

def detect_name_based_duplicates(file_paths):
    """Legacy API: return content-identical files, never infer identity from names.

    Organization retains all inputs even when filename hints are requested. Use
    duplicate review to decide whether a redundant copy should be omitted.
    """
    seen = {}
    duplicates = set()
    for path in file_paths:
        path = Path(path)
        if not path.is_file() or path.is_symlink():
            continue
        identity = file_identity(path)
        key = (identity["size"], identity["sha256"])
        if key in seen:
            duplicates.add(path)
        else:
            seen[key] = path
    return duplicates


def _process_single_file(args):
    """
    Worker function for parallel file processing.
    
    Args:
        args: Tuple of (file_path, dest_path, operation, duplicate_files, name_duplicate_files)
        
    Returns:
        dict: Result dictionary with status, file info, and statistics
    """
    file_path, dest_path, operation, duplicate_files, name_duplicate_files = args[:5]
    journal = args[5] if len(args) > 5 else None
    
    result = {
        'status': 'skipped',
        'reason': None,
        'file_type': None,
        'folder_key': None,
        'source': None,
        'destination': None,
        'error': None
    }
    
    try:
        # Skip perceptual duplicates (use absolute path for comparison)
        if duplicate_files and file_path.resolve() in duplicate_files:
            result['status'] = 'skipped'
            result['reason'] = 'perceptual_duplicate'
            logger.info(f"Skipping perceptual duplicate: {file_path.name}")
            return result
        
        ext = file_path.suffix.lower()
        
        # Check file type
        is_image = ext in constants.IMAGE_EXTENSIONS
        is_video = ext in constants.VIDEO_EXTENSIONS
        
        if is_image:
            result['file_type'] = 'image'
        elif is_video:
            result['file_type'] = 'video'
        else:
            result['status'] = 'skipped'
            result['reason'] = 'not_media'
            return result
        
        # Get date
        date_taken = None
        if is_image:
            date_taken = get_image_date(str(file_path))
        elif is_video:
            date_taken = get_video_date(str(file_path))
        
        # Fallback to file modification date
        if date_taken is None:
            date_taken = get_file_modification_date(str(file_path))
            logger.info(f"Used file system date for: {file_path.name}")
        
        # Create target destination
        year_folder = date_taken.strftime('%Y')
        month_folder = date_taken.strftime('%B')
        folder_key = f"{year_folder}/{month_folder}"
        
        target_folder = dest_path / year_folder / month_folder
        target_folder.mkdir(parents=True, exist_ok=True)
        
        target_file = target_folder / file_path.name
        
        target_file = verified_transfer(file_path, target_file, operation, journal=journal)
        logger.info(f"Verified {operation}: {file_path.name} -> {target_file}")

        result['status'] = 'success'
        result['folder_key'] = folder_key
        result['source'] = file_path
        result['destination'] = target_file
        
    except Exception as e:
        result['status'] = 'error'
        result['error'] = str(e)
        logger.error(f"Error processing {file_path.name}: {e}")
    
    return result


def organise_files(
    src_dir,
    dest_dir,
    operation='move',
    check_duplicates=False,
    duplicate_threshold=THRESHOLD_SIMILAR,
    check_name_duplicates=False,
    progress_callback=None,
    target_files: list[str] | None = None,
):
    """
    Organize media files into year/month folders.
    
    Args:
        src_dir: Source directory
        dest_dir: Destination directory
        operation: 'move' or 'copy'
        check_duplicates: If True, detect and skip duplicate images before organizing (perceptual hashing)
        duplicate_threshold: Hamming distance threshold for duplicate detection
        check_name_duplicates: Legacy option; named variants are retained for content review
        progress_callback: Optional callback(completed, total, result_dict) invoked per processed file
        target_files: Optional list of specific absolute file paths to organize. If provided, only these files are processed.
    """
    if operation not in {"copy", "move"}:
        raise ValueError("operation must be copy or move")
    src_path, dest_path = validate_roots(src_dir, dest_dir)

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
    
    # Gather files
    if target_files is not None:
        all_files = [Path(f).absolute() for f in target_files]
        if any(p.is_symlink() or src_path not in p.resolve().parents for p in all_files):
            raise ValueError("target_files must be regular files inside the source directory")
    else:
        all_files = list(src_path.rglob('*'))
    
    # Filename resemblance never authorizes omitting an input.
    name_duplicate_files = set()
    if check_name_duplicates:
        logger.info("Filename hints no longer skip inputs; retaining all named variants")

    # Perceptual duplicate detection (if enabled)
    duplicate_files = set()  # Files to skip due to perceptual duplication
    if check_duplicates:
        logger.info(f"Scanning for perceptual duplicates using {'Rust (phash_rs)' if is_rust_available() else 'Python fallback'}...")
        
        # Collect source images
        src_images = []
        for p in all_files:
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
                    logger.info("Duplicate group found in destination: skipping source files")
                else:
                    # Mark all duplicates except the best one (source-only group)
                    for dup_path in group.duplicates:
                        # Use absolute path for consistent comparison
                        duplicate_files.add(Path(dup_path).resolve())
                        stats['perceptual_duplicates'] += 1
                    logger.info(f"Duplicate group: keeping {group.best}, skipping {len(group.duplicates)} duplicates")
        else:
            logger.info("No perceptual duplicates found")
    
    # Collect all files to process
    file_list = []
    for file_path in all_files:
        if file_path.is_file() and not file_path.is_symlink():
            stats['total_scanned'] += 1
            file_list.append(file_path)
    
    if not file_list:
        logger.info("No files found to process")
        if progress_callback:
            try:
                progress_callback(0, 0, None)
            except Exception:
                pass
        return stats
    
    num_workers = min(8, max(1, cpu_count() - 1), len(file_list))
    results = []
    total_files = len(file_list)
    # Threads share one explicitly scoped journal; no forked singleton state.
    with UndoManager() as journal:
        worker_args = [
            (p, dest_path, operation, duplicate_files if check_duplicates else None,
             name_duplicate_files, journal)
            for p in file_list
        ]
        with ThreadPoolExecutor(max_workers=num_workers) as pool:
            for completed, result in enumerate(tqdm(
                pool.map(_process_single_file, worker_args), total=total_files,
                desc="Organizing files", unit="file",
            ), 1):
                results.append(result)
                if progress_callback:
                    progress_callback(completed, total_files, result)

    # Aggregate results and update statistics
    for result in results:
        # Track file types
        if result['file_type'] == 'image':
            stats['images'] += 1
        elif result['file_type'] == 'video':
            stats['videos'] += 1
        elif result['status'] == 'skipped' and result['reason'] == 'not_media':
            stats['other'] += 1
        
        # Track processing results
        if result['status'] == 'success':
            stats['processed'] += 1
            if result['folder_key']:
                stats['folders_created'][result['folder_key']] += 1
            
            
        elif result['status'] == 'skipped':
            if result['reason'] == 'duplicate_filename':
                stats['duplicates'] += 1
            # perceptual and name duplicates already counted during detection
            
        elif result['status'] == 'error':
            stats['errors'] += 1
    
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
        print("\n🗂  Organized into:")
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