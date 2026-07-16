# Recording the Demo GIF

## Overview

The demo GIF should be a 30–45 second screen capture showing:
1. Drop/select photos → dedupe review UI with card/modal duplicate comparison
2. Classify wizard → job running with stage progress
3. People page naming an unidentified face
4. An undo action reverting a change

## Tools

| Platform | Tool | Notes |
|----------|------|-------|
| Linux | [Peek](https://github.com/phw/peek) or [SimpleScreenRecorder](https://www.maartenbaert.be/simplescreenrecorder/) | Peek outputs GIF directly |
| macOS | `Cmd+Shift+5` or [Kap](https://getkap.co/) | Kap outputs GIF/MP4 |
| Cross-platform | [OBS Studio](https://obsproject.com/) | Outputs MP4, convert to GIF below |

## Steps

1. Start the app with populated data:
   ```bash
   DEMO_MODE=true python main.py --web
   ```

2. Open `http://localhost:8080` in a browser with a clean window (no bookmarks bar).

3. Record the sequence above in one take.

4. Convert to optimized GIF (if recording was MP4):
   ```bash
   # Generate palette for high-quality GIF
   ffmpeg -i recording.mp4 -vf "fps=12,scale=960:-1:flags=lanczos,palettegen" palette.png

   # Convert using palette
   ffmpeg -i recording.mp4 -i palette.png -lavfi "fps=12,scale=960:-1:flags=lanczos [x]; [x][1:v] paletteuse" -loop 0 docs/demo.gif
   ```

5. Speed up slow sections (optional):
   ```bash
   ffmpeg -i recording.mp4 -filter:v "setpts=0.5*PTS" -an fast.mp4
   ```

6. Verify size is under 10MB:
   ```bash
   ls -lh docs/demo.gif
   ```

7. Uncomment the GIF embed in README.md:
   ```markdown
   ![Demo](docs/demo.gif)
   ```

## Alternative: MP4

GitHub renders MP4 natively in README files. If the GIF is too large, use MP4:

```markdown
https://github.com/user-attachments/assets/<upload-id>
```

Upload via GitHub's web UI (drag & drop into an issue/PR, copy the URL).
