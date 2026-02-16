#!/usr/bin/env python3
"""
Demonstration: How perceptual duplicate detection works in Mode 1
"""

print("""
╔═══════════════════════════════════════════════════════════════╗
║         HOW PERCEPTUAL DUPLICATE DETECTION WORKS              ║
╚═══════════════════════════════════════════════════════════════╝

When you enable perceptual hashing in Mode 1:

1. 📂 It scans SOURCE directory for images
2. 📂 It scans DESTINATION directory for images  
3. 🔍 It finds duplicate groups across BOTH directories
4. 🎯 It keeps the BEST quality image (highest resolution)
5. ⏭️  It SKIPS moving/copying the duplicates

IMPORTANT BEHAVIORS:

✅ If duplicate exists in DESTINATION:
   → ALL source duplicates are SKIPPED
   → Nothing is copied/moved
   → Files stay in source (not organized)

✅ If duplicates only in SOURCE:
   → Keeps best quality version
   → Skips the rest
   → Only best file is organized

WHY YOU MIGHT NOT SEE RESULTS:

❌ Duplicates already in destination
   → They were processed in a previous run
   → Nothing to do this time

❌ Running on empty source folder
   → No files to organize

❌ Expecting duplicates to be MOVED to "Duplicates" folder
   → Mode 1 SKIPS them, doesn't move them
   → Use Mode 2 for moving duplicates

TO SEE PERCEPTUAL HASHING WORKING:

1. Put duplicate images in SOURCE (s/)
2. Empty DESTINATION (d/) 
3. Run Mode 1 with:
   - Perceptual hashing: YES
   - Name-based: NO (optional)
4. Check summary: "🔍 X perceptual duplicates detected (skipped)"
5. Check logs: logs/backup_YYYYMMDD.log

╚═══════════════════════════════════════════════════════════════╝
""")

# Show current state
from pathlib import Path

source = Path("s")
dest = Path("d" )

if source.exists():
    source_images = list(source.rglob("*.jpg")) + list(source.rglob("*.png"))
    print(f"📸 Source (s/) has {len(source_images)} images")
    
if dest.exists():
    dest_images = list(dest.rglob("*.jpg")) + list(dest.rglob("*.png"))
    print(f"📸 Destination (d/) has {len(dest_images)} images")

print("\n💡 TIP: Check today's log for details:")
print("   tail -30 logs/backup_$(date +%Y%m%d).log")
