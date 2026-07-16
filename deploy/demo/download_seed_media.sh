#!/usr/bin/env bash
# Download CC0 seed images from Pexels for the demo.
# Run once before deploying the demo instance.
#
# Usage:
#   cd deploy/demo
#   bash download_seed_media.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MEDIA_DIR="$SCRIPT_DIR/seed-media"
mkdir -p "$MEDIA_DIR"

echo "==> Downloading seed images to $MEDIA_DIR"

# Pexels provides direct image download links via their CDN.
# Format: https://images.pexels.com/photos/{id}/pexels-photo-{id}.jpeg?auto=compress&cs=tinysrgb&w=1260
BASE="https://images.pexels.com/photos"
DL_PARAMS="auto=compress&cs=tinysrgb&w=1260&h=750&dpr=1"

declare -A IMAGES=(
    ["travel_01.jpg"]="3278215"
    ["travel_02.jpg"]="2387873"
    ["travel_03.jpg"]="2108845"
    ["travel_04.jpg"]="2539076"
    ["nature_01.jpg"]="1068523"
    ["nature_02.jpg"]="1179229"
    ["nature_03.jpg"]="1287145"
    ["nature_04.jpg"]="1366919"
    ["food_01.jpg"]="1640777"
    ["food_02.jpg"]="1099680"
    ["food_03.jpg"]="376464"
    ["pets_01.jpg"]="1108099"
    ["pets_02.jpg"]="45201"
    ["pets_03.jpg"]="2253275"
    ["document_01.jpg"]="590022"
    ["document_02.jpg"]="1065704"
    ["night_01.jpg"]="1257860"
    ["night_02.jpg"]="1567069"
    ["events_01.jpg"]="1190297"
    ["events_02.jpg"]="2608517"
    ["art_01.jpg"]="1839919"
    ["vehicles_01.jpg"]="3802510"
    ["selfie_01.jpg"]="1382731"
    ["selfie_02.jpg"]="1516680"
    ["family_01.jpg"]="1128318"
    ["family_02.jpg"]="1128317"
)

for filename in "${!IMAGES[@]}"; do
    photo_id="${IMAGES[$filename]}"
    url="$BASE/$photo_id/pexels-photo-$photo_id.jpeg?$DL_PARAMS"
    dest="$MEDIA_DIR/$filename"
    if [ -f "$dest" ]; then
        echo "  [skip] $filename (already exists)"
    else
        echo "  [download] $filename"
        curl -sL "$url" -o "$dest" || echo "  [WARN] Failed to download $filename"
    fi
done

# Generate near-duplicates for dedupe demo
echo ""
echo "==> Generating near-duplicate variants"

if command -v convert &>/dev/null; then
    # Resized variant
    if [ -f "$MEDIA_DIR/travel_01.jpg" ]; then
        convert "$MEDIA_DIR/travel_01.jpg" -resize 50% "$MEDIA_DIR/travel_01_resized.jpg"
        echo "  [created] travel_01_resized.jpg"
    fi

    # Re-compressed variant
    if [ -f "$MEDIA_DIR/nature_01.jpg" ]; then
        convert "$MEDIA_DIR/nature_01.jpg" -quality 30 "$MEDIA_DIR/nature_01_compressed.jpg"
        echo "  [created] nature_01_compressed.jpg"
    fi

    # Cropped variant
    if [ -f "$MEDIA_DIR/food_01.jpg" ]; then
        convert "$MEDIA_DIR/food_01.jpg" -gravity center -crop 80%x80%+0+0 +repage "$MEDIA_DIR/food_01_crop.jpg"
        echo "  [created] food_01_crop.jpg"
    fi
else
    echo "  [skip] ImageMagick (convert) not found — duplicate variants not created"
    echo "         Install with: sudo apt install imagemagick"
fi

# Generate simple screenshots (colored rectangles as PNG)
echo ""
echo "==> Generating placeholder screenshots"

if command -v convert &>/dev/null; then
    convert -size 1280x720 xc:"#1e293b" \
        -fill white -pointsize 40 -gravity center -annotate +0+0 "Clean-Backup UI" \
        "$MEDIA_DIR/screenshot_01.png"
    echo "  [created] screenshot_01.png"

    convert -size 1280x720 xc:"#0f172a" \
        -fill "#22d3ee" -pointsize 40 -gravity center -annotate +0+0 "Code Editor" \
        "$MEDIA_DIR/screenshot_02.png"
    echo "  [created] screenshot_02.png"
else
    echo "  [skip] Screenshots require ImageMagick"
fi

echo ""
TOTAL=$(find "$MEDIA_DIR" -type f | wc -l)
echo "==> Done. $TOTAL files in $MEDIA_DIR"
