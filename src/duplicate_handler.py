"""
Duplicate Handler Module

Handles detection and management of duplicate images using perceptual hashing.
This module is designed to be modular and can be disabled if buggy.
"""

import shutil
from pathlib import Path
from typing import Optional, List, Literal
from dataclasses import dataclass
from src.phash import (
    find_duplicates, 
    DuplicateGroup, 
    is_rust_available,
    get_backend,
    THRESHOLD_SIMILAR,
    THRESHOLD_VERY_SIMILAR
)
from src.logger import logger
from src.undo_manager import undo_manager


@dataclass
class DuplicateReport:
    """Report of duplicate detection operation."""
    total_scanned: int
    duplicate_groups: int
    total_duplicates: int
    space_recoverable: int  # bytes
    duplicates_moved: int
    errors: int
    groups: List[DuplicateGroup]


def scan_for_duplicates(
    source_dir: str,
    threshold: int = THRESHOLD_SIMILAR
) -> List[DuplicateGroup]:
    """
    Scan a directory for duplicate images using pHash.
    
    Args:
        source_dir: Directory to scan
        threshold: Hamming distance threshold (lower = stricter)
    
    Returns:
        List of DuplicateGroup objects
    """
    logger.info(f"Scanning for duplicates using {get_backend()}")
    logger.info(f"Threshold: {threshold}")
    
    duplicates = find_duplicates(source_dir, threshold)
    
    if duplicates:
        logger.info(f"Found {len(duplicates)} duplicate groups")
        for i, group in enumerate(duplicates, 1):
            logger.debug(f"Group {i}: {len(group.paths)} images, best: {group.best}")
    else:
        logger.info("No duplicates found")
    
    return duplicates


def handle_duplicates(
    source_dir: str,
    duplicates_dir: Optional[str] = None,
    action: Literal["move", "copy", "delete", "report"] = "report",
    threshold: int = THRESHOLD_SIMILAR,
    keep_best: bool = True
) -> DuplicateReport:
    """
    Scan for and handle duplicate images using pHash.
    
    Args:
        source_dir: Directory to scan for duplicates
        duplicates_dir: Where to move/copy duplicates (if action="move" or "copy")
        action: What to do with duplicates:
            - "report": Just report, don't modify files
            - "move": Move duplicates to duplicates_dir
            - "copy": Copy duplicates to duplicates_dir (keeps originals)
            - "delete": Delete duplicate files (keeps best)
        threshold: Hamming distance threshold
        keep_best: If True, keep the highest resolution version
    
    Returns:
        DuplicateReport with statistics and details
    """
    source_path = Path(source_dir)
    
    undo_manager.start_session()

    # Find duplicates
    groups = scan_for_duplicates(source_dir, threshold)
    
    # Calculate statistics
    total_scanned = sum(len(list(source_path.rglob(f'*{ext}'))) 
                       for ext in ['.jpg', '.jpeg', '.png', '.heic', '.bmp', '.tiff', '.gif'])
    total_duplicates = sum(len(g.paths) - 1 for g in groups)  # -1 for keeping best
    
    # Calculate recoverable space
    space_recoverable = 0
    for group in groups:
        for path in group.duplicates:  # Excludes best
            try:
                space_recoverable += Path(path).stat().st_size
            except OSError:
                pass
    
    report = DuplicateReport(
        total_scanned=total_scanned,
        duplicate_groups=len(groups),
        total_duplicates=total_duplicates,
        space_recoverable=space_recoverable,
        duplicates_moved=0,
        errors=0,
        groups=groups
    )
    
    if action == "report":
        return report
    
    # Handle duplicates
    if action in ("move", "copy"):
        if not duplicates_dir:
            duplicates_dir = str(source_path / "Duplicates")
        dup_path = Path(duplicates_dir)
        dup_path.mkdir(parents=True, exist_ok=True)
        
        for group in groups:
            for dup in group.duplicates:
                try:
                    target = dup_path / Path(dup).name
                    # Handle name conflicts
                    counter = 1
                    while target.exists():
                        stem = Path(dup).stem
                        suffix = Path(dup).suffix
                        target = dup_path / f"{stem}_{counter}{suffix}"
                        counter += 1
                    
                    if action == "move":
                        shutil.move(dup, str(target))
                        logger.info(f"Moved duplicate: {dup} -> {target}")
                        undo_manager.log_action('move', dup, target)
                    else:  # copy
                        shutil.copy2(dup, str(target))
                        logger.info(f"Copied duplicate: {dup} -> {target}")
                        undo_manager.log_action('copy', dup, target)
                    report.duplicates_moved += 1
                except Exception as e:
                    logger.error(f"Error {action}ing {dup}: {e}")
                    report.errors += 1
    
    elif action == "delete":
        for group in groups:
            for dup in group.duplicates:
                try:
                    Path(dup).unlink()
                    logger.info(f"Deleted duplicate: {dup}")
                    report.duplicates_moved += 1
                except Exception as e:
                    logger.error(f"Error deleting {dup}: {e}")
                    report.errors += 1
    
    undo_manager.end_session()
    return report


def print_duplicate_report(report: DuplicateReport):
    """Print a formatted duplicate detection report."""
    print("\n" + "=" * 50)
    print("        🔍 DUPLICATE DETECTION REPORT")
    print("=" * 50)
    
    print(f"\n📊 Backend: {get_backend()}")
    print(f"   Rust acceleration: {'✅ Yes' if is_rust_available() else '❌ No (using Python fallback)'}")
    
    print(f"\n📁 Scanned: ~{report.total_scanned:,} images")
    print(f"🔄 Duplicate groups: {report.duplicate_groups:,}")
    print(f"📋 Total duplicates: {report.total_duplicates:,}")
    
    # Format recoverable space
    if report.space_recoverable >= 1024 * 1024 * 1024:
        space_str = f"{report.space_recoverable / (1024**3):.2f} GB"
    elif report.space_recoverable >= 1024 * 1024:
        space_str = f"{report.space_recoverable / (1024**2):.2f} MB"
    else:
        space_str = f"{report.space_recoverable / 1024:.2f} KB"
    
    print(f"💾 Recoverable space: {space_str}")
    
    if report.duplicates_moved > 0:
        print(f"\n✅ Processed: {report.duplicates_moved:,} duplicates")
    
    if report.errors > 0:
        print(f"❌ Errors: {report.errors:,}")
    
    # Show detailed groups
    if report.groups:
        print(f"\n📂 Duplicate Groups:")
        for i, group in enumerate(report.groups[:10], 1):  # Show first 10
            print(f"\n   Group {i} ({len(group.paths)} images):")
            print(f"   Best (keeping): {Path(group.best).name}")
            for dup in group.duplicates[:3]:  # Show first 3 duplicates
                print(f"   └─ Duplicate: {Path(dup).name}")
            if len(group.duplicates) > 3:
                print(f"   └─ ... and {len(group.duplicates) - 3} more")
        
        if len(report.groups) > 10:
            print(f"\n   ... and {len(report.groups) - 10} more groups")
    
    print("\n" + "=" * 50 + "\n")


# CLI entry point for standalone duplicate detection
def main():
    """Command-line interface for duplicate detection."""
    print("🔍 Duplicate Image Detector")
    print("-" * 30)
    
    source = input("Enter folder to scan: ").strip()
    if not source or not Path(source).exists():
        print("❌ Invalid source folder")
        return
    
    print("\nOptions:")
    print("  [1] Report only (no changes)")
    print("  [2] Move duplicates to subfolder")
    print("  [3] Delete duplicates (keep best)")
    
    choice = input("Choose action (1/2/3): ").strip()
    
    action_map = {"1": "report", "2": "move", "3": "delete"}
    action = action_map.get(choice, "report")
    
    if action == "delete":
        confirm = input("⚠️  This will DELETE files. Type 'yes' to confirm: ")
        if confirm.lower() != 'yes':
            print("Cancelled.")
            return
    
    print(f"\n⏳ Scanning for duplicates...")
    report = handle_duplicates(source, action=action)
    print_duplicate_report(report)


if __name__ == "__main__":
    main()
