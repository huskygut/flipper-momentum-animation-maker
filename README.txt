Flipper Animation Maker Web

https://huskygut.github.io/flipper-momentum-animation-maker/

What this is

A browser-based Flipper Zero Momentum animation maker.

It loads a GIF, converts the frames to 128x64 black-and-white Flipper-style frames, and exports a Momentum-compatible asset pack ZIP.

Files

index.html
css/styles.css
js/app.js
js/zip.js
README.txt
REVIEW_NOTES.txt

How to run

Open index.html in Brave, Chrome, or Edge.

No install is required.

How to use

1. Open index.html.
2. Choose a GIF.
3. Adjust threshold, contrast, brightness, sharpen, and fit mode.
4. Try the Balanced, Darker, or Line Art presets.
5. Use Remove Current, Restore Last, Reduce Evenly, Apply Trim, or Reset All.
6. Click Export Momentum ZIP.
7. Extract the exported ZIP.
8. Copy the generated pack folder to:

/ext/asset_packs/

Output structure

PackName/
  Anims/
    manifest.txt
    AnimationName_128x64/
      meta.txt
      frame_0.bm
      frame_1.bm
      frame_2.bm

Preview zoom

The preview buttons are:

2x
3x
4x
5x

The exported animation always remains 128x64.

Windows note

If Windows shows a warning about files from the exported ZIP, right-click the exported ZIP, choose Properties, check Unblock if shown, click Apply, then extract again.

Browser note

This version uses ImageDecoder when the browser supports it, then falls back to a built-in GIF parser when ImageDecoder is unavailable or fails.

Brave, Chrome, and Edge are still the fastest path. Safari and Firefox should handle standard GIFs through the compatibility decoder.

Known limitation

The BM export uses the simple uncompressed BM payload format. This is larger than heatshrink-compressed BM files but simpler and avoids needing a Python server or WebAssembly compressor.

Very large GIFs are capped to protect the browser tab:

- File warning starts at 64 MB.
- Decoding is capped at 500 frames.
- Source frames are stored at a bounded size because export is always 128x64.
- Hold-last-frame repeats are capped at 1000.

https://huskygut.github.io/flipper-momentum-animation-maker/
