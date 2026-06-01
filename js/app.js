const WIDTH = 128;
const HEIGHT = 64;
const PREVIEW_BG = [202, 214, 180, 255];
const PREVIEW_FG = [39, 52, 35, 255];
const MAX_UPLOAD_BYTES = 64 * 1024 * 1024;
const MAX_DECODED_FRAMES = 500;
const MAX_THUMBNAILS = 180;
const MAX_CACHE_FRAMES = 260;
const MAX_FRAME_SOURCE_DIMENSION = 256;
const MAX_FALLBACK_GIF_PIXELS = 4096 * 4096;
const MAX_HOLD_FRAMES = 1000;
const MAX_PACK_NAME_LENGTH = 31;
const MAX_ANIMATION_NAME_LENGTH = 64;
const META_MAX_VALUE = 100000;

const state = {
  sourceFrames: [],
  activeIndices: [],
  removedIndices: new Set(),
  removedStack: [],
  current: 0,
  playing: false,
  playTimer: null,
  previewTimer: null,
  thumbsTimer: null,
  processCache: new Map(),
  loadToken: 0,
  originalName: "animation"
};

const el = id => document.getElementById(id);
const canvas = el("previewCanvas");
const ctx = canvas.getContext("2d", { willReadFrequently: true });

function setStatus(title, text, isError = false) {
  el("statusTitle").textContent = title;
  el("statusText").textContent = text;
  el("statusTitle").style.color = isError ? "var(--danger)" : "var(--ok)";
}

function disposeCanvas(item) {
  if (item && typeof item.width === "number") {
    item.width = 0;
    item.height = 0;
  }
}

function clearCache() {
  for (const canvasItem of state.processCache.values()) {
    disposeCanvas(canvasItem);
  }
  state.processCache.clear();
}

function clearScheduledRefresh() {
  if (state.previewTimer) {
    clearTimeout(state.previewTimer);
    state.previewTimer = null;
  }

  if (state.thumbsTimer) {
    clearTimeout(state.thumbsTimer);
    state.thumbsTimer = null;
  }
}

function clearProjectFrames() {
  clearScheduledRefresh();
  clearPlayback();
  clearCache();
  for (const frame of state.sourceFrames) {
    disposeCanvas(frame);
  }
  state.sourceFrames = [];
  state.activeIndices = [];
  state.removedIndices = new Set();
  state.removedStack = [];
  state.current = 0;
}

function disposeFrames(frames) {
  for (const frame of frames || []) {
    disposeCanvas(frame);
  }
}

function sanitizeName(name, fallback = "item", maxLength = 120) {
  const cleaned = String(name || "")
    .trim()
    .replace(/[^A-Za-z0-9_-]+/g, "_")
    .replace(/_+/g, "_")
    .replace(/^[._\s]+|[._\s]+$/g, "")
    .slice(0, maxLength);

  const safe = cleaned || fallback;
  const reserved = new Set(["CON","PRN","AUX","NUL","COM1","COM2","COM3","COM4","COM5","COM6","COM7","COM8","COM9","LPT1","LPT2","LPT3","LPT4","LPT5","LPT6","LPT7","LPT8","LPT9"]);
  const reservedSafe = reserved.has(safe.toUpperCase()) ? "_" + safe : safe;
  return reservedSafe.slice(0, maxLength);
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function number(id, fallback, min = null, max = null) {
  let value = Number(el(id).value);
  if (!Number.isFinite(value)) value = fallback;
  if (min !== null) value = Math.max(min, value);
  if (max !== null) value = Math.min(max, value);
  return value;
}

function intNumber(id, fallback, min = null, max = null) {
  return Math.round(number(id, fallback, min, max));
}

function intFieldValue(id, fallback, min, max) {
  const value = intNumber(id, fallback, min, max);
  el(id).value = String(value);
  return value;
}

function conversionKey() {
  return [
    intNumber("threshold", 140, 0, 255),
    number("contrast", 2.2, 0.2, 4).toFixed(2),
    intNumber("brightness", 0, -100, 100),
    number("sharpen", 0.0, 0, 3).toFixed(2),
    el("fitMode").value
  ].join("|");
}

function updateOutputs() {
  el("thresholdOut").textContent = el("threshold").value;
  el("contrastOut").textContent = Number(el("contrast").value).toFixed(1);
  el("brightnessOut").textContent = el("brightness").value;
  el("sharpenOut").textContent = Number(el("sharpen").value).toFixed(1);
}

function clearPlayback() {
  if (state.playTimer) {
    clearInterval(state.playTimer);
    state.playTimer = null;
  }
  state.playing = false;
  el("playBtn").textContent = "Play";
}

function setPreviewScale(scale) {
  const safeScale = Math.max(2, Math.min(5, Number(scale) || 5));
  document.body.dataset.previewScale = String(safeScale);
  setStatus("Preview zoom", `Preview set to ${safeScale}x. Export remains 128x64.`);
}

function staleLoadError() {
  const err = new Error("A newer GIF was selected.");
  err.cancelled = true;
  return err;
}

function assertCurrentLoad(loadToken) {
  if (loadToken !== state.loadToken) {
    throw staleLoadError();
  }
}

function yieldToBrowser() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

function scaledFrameCanvas(source, width, height) {
  const safeWidth = Math.max(1, Math.round(width || WIDTH));
  const safeHeight = Math.max(1, Math.round(height || HEIGHT));
  const scale = Math.min(1, MAX_FRAME_SOURCE_DIMENSION / Math.max(safeWidth, safeHeight));
  const frameCanvas = document.createElement("canvas");
  frameCanvas.width = Math.max(1, Math.round(safeWidth * scale));
  frameCanvas.height = Math.max(1, Math.round(safeHeight * scale));

  const frameCtx = frameCanvas.getContext("2d");
  frameCtx.imageSmoothingEnabled = true;
  frameCtx.imageSmoothingQuality = "high";
  frameCtx.drawImage(source, 0, 0, frameCanvas.width, frameCanvas.height);
  return frameCanvas;
}

async function maybeWarnForLargeGif(file) {
  if (file.size > MAX_UPLOAD_BYTES) {
    const mb = (file.size / (1024 * 1024)).toFixed(1);
    const proceed = confirm(`This GIF is ${mb} MB. Large GIFs can slow or crash a browser tab. Continue?`);
    if (!proceed) throw new Error("Large GIF load cancelled.");
  }
}

async function decodeGifWithImageDecoder(data, file, loadToken) {
  if (!("ImageDecoder" in window)) {
    throw new Error("ImageDecoder is not available.");
  }

  let decoder;
  const frames = [];

  try {
    decoder = new ImageDecoder({ data, type: file.type || "image/gif" });
    await decoder.tracks.ready;

    const track = decoder.tracks.selectedTrack;
    const reportedCount = Number(track && track.frameCount);
    const hasKnownCount = Number.isFinite(reportedCount) && reportedCount > 0;
    const count = hasKnownCount ? reportedCount : MAX_DECODED_FRAMES;
    const limit = Math.min(count, MAX_DECODED_FRAMES);

    for (let i = 0; i < limit; i++) {
      let decoded;
      try {
        decoded = await decoder.decode({ frameIndex: i });
      } catch (err) {
        if (!hasKnownCount && frames.length) break;
        throw err;
      }

      assertCurrentLoad(loadToken);
      const bitmap = decoded.image;

      try {
        frames.push(scaledFrameCanvas(
          bitmap,
          bitmap.displayWidth || bitmap.width || WIDTH,
          bitmap.displayHeight || bitmap.height || HEIGHT
        ));
      } finally {
        if (bitmap && typeof bitmap.close === "function") bitmap.close();
      }

      if ((i + 1) % 8 === 0) {
        setStatus("Loading", `Decoded ${frames.length} frame(s)...`);
        await yieldToBrowser();
        assertCurrentLoad(loadToken);
      }
    }

    if (hasKnownCount && count > limit) {
      setStatus("Large GIF capped", `Loaded first ${limit} frames out of ${count}. Reduce frames before export.`);
    } else if (!hasKnownCount && frames.length === MAX_DECODED_FRAMES) {
      setStatus("Large GIF capped", `Loaded first ${MAX_DECODED_FRAMES} frames. Reduce frames before export.`);
    }
  } catch (err) {
    disposeFrames(frames);
    throw err;
  } finally {
    if (decoder && typeof decoder.close === "function") decoder.close();
  }

  return frames;
}

function readColorTable(reader, size) {
  const table = [];
  for (let i = 0; i < size; i++) {
    table.push([reader.byte(), reader.byte(), reader.byte()]);
  }
  return table;
}

function makeGifReader(bytes) {
  let pos = 0;

  return {
    get pos() {
      return pos;
    },
    byte() {
      if (pos >= bytes.length) throw new Error("Unexpected end of GIF data.");
      return bytes[pos++];
    },
    u16() {
      const lo = this.byte();
      const hi = this.byte();
      return lo | (hi << 8);
    },
    bytes(length) {
      if (pos + length > bytes.length) throw new Error("Unexpected end of GIF data.");
      const out = bytes.slice(pos, pos + length);
      pos += length;
      return out;
    },
    text(length) {
      return String.fromCharCode(...this.bytes(length));
    },
    subBlocks() {
      const chunks = [];
      let total = 0;

      while (true) {
        const size = this.byte();
        if (size === 0) break;
        const chunk = this.bytes(size);
        chunks.push(chunk);
        total += chunk.length;
      }

      const out = new Uint8Array(total);
      let offset = 0;
      for (const chunk of chunks) {
        out.set(chunk, offset);
        offset += chunk.length;
      }
      return out;
    },
    skipSubBlocks() {
      while (true) {
        const size = this.byte();
        if (size === 0) break;
        pos += size;
        if (pos > bytes.length) throw new Error("Unexpected end of GIF data.");
      }
    }
  };
}

function decodeLzw(minCodeSize, data, expectedLength) {
  if (minCodeSize < 2 || minCodeSize > 8) {
    throw new Error("Unsupported GIF LZW code size.");
  }

  const clearCode = 1 << minCodeSize;
  const endCode = clearCode + 1;
  let codeSize = minCodeSize + 1;
  let nextCode = endCode + 1;
  let previous = null;
  let bitPos = 0;
  let table = [];
  const output = new Uint8Array(expectedLength);
  let outPos = 0;

  function resetTable() {
    table = [];
    for (let i = 0; i < clearCode; i++) table[i] = [i];
    table[clearCode] = null;
    table[endCode] = null;
    codeSize = minCodeSize + 1;
    nextCode = endCode + 1;
    previous = null;
  }

  function readCode() {
    let code = 0;
    for (let i = 0; i < codeSize; i++) {
      if ((bitPos >> 3) >= data.length) return null;
      code |= ((data[bitPos >> 3] >> (bitPos & 7)) & 1) << i;
      bitPos++;
    }
    return code;
  }

  function writeEntry(entry) {
    for (const value of entry) {
      if (outPos < output.length) output[outPos++] = value;
    }
  }

  resetTable();

  while (outPos < expectedLength) {
    const code = readCode();
    if (code === null) break;
    if (code === clearCode) {
      resetTable();
      continue;
    }
    if (code === endCode) break;

    let entry;
    if (table[code]) {
      entry = table[code];
    } else if (code === nextCode && previous) {
      entry = previous.concat(previous[0]);
    } else {
      throw new Error("Invalid GIF LZW stream.");
    }

    writeEntry(entry);

    if (previous && nextCode < 4096) {
      table[nextCode++] = previous.concat(entry[0]);
      if (nextCode === (1 << codeSize) && codeSize < 12) codeSize++;
    }

    previous = entry;
  }

  if (outPos < expectedLength) {
    throw new Error("GIF frame ended before all pixels were decoded.");
  }

  return output;
}

function deinterlace(indices, width, height) {
  const out = new Uint8Array(indices.length);
  const passes = [[0, 8], [4, 8], [2, 4], [1, 2]];
  let src = 0;

  for (const [start, step] of passes) {
    for (let y = start; y < height; y += step) {
      const row = y * width;
      for (let x = 0; x < width; x++) {
        out[row + x] = indices[src++];
      }
    }
  }

  return out;
}

function fillGifRegion(pixels, screenWidth, screenHeight, rect, rgba) {
  const left = clamp(rect.left, 0, screenWidth);
  const top = clamp(rect.top, 0, screenHeight);
  const right = clamp(rect.left + rect.width, 0, screenWidth);
  const bottom = clamp(rect.top + rect.height, 0, screenHeight);

  for (let y = top; y < bottom; y++) {
    for (let x = left; x < right; x++) {
      const offset = ((y * screenWidth) + x) * 4;
      pixels[offset] = rgba[0];
      pixels[offset + 1] = rgba[1];
      pixels[offset + 2] = rgba[2];
      pixels[offset + 3] = rgba[3];
    }
  }
}

function applyGifDisposal(previous, pixels, screenWidth, screenHeight, background) {
  if (!previous) return;

  if (previous.disposal === 2) {
    fillGifRegion(pixels, screenWidth, screenHeight, previous.rect, background);
  } else if (previous.disposal === 3 && previous.backup) {
    pixels.set(previous.backup);
  }
}

function drawGifFrame(pixels, screenWidth, screenHeight, frame, colorTable, transparentIndex) {
  const { left, top, width, height, indices } = frame;
  let src = 0;

  for (let y = 0; y < height; y++) {
    const destY = top + y;
    for (let x = 0; x < width; x++, src++) {
      const destX = left + x;
      if (destX < 0 || destY < 0 || destX >= screenWidth || destY >= screenHeight) continue;

      const colorIndex = indices[src];
      if (colorIndex === transparentIndex) continue;

      const color = colorTable[colorIndex] || [0, 0, 0];
      const offset = ((destY * screenWidth) + destX) * 4;
      pixels[offset] = color[0];
      pixels[offset + 1] = color[1];
      pixels[offset + 2] = color[2];
      pixels[offset + 3] = 255;
    }
  }
}

function canvasFromGifPixels(pixels, width, height) {
  const fullCanvas = document.createElement("canvas");
  fullCanvas.width = width;
  fullCanvas.height = height;
  fullCanvas.getContext("2d").putImageData(new ImageData(new Uint8ClampedArray(pixels), width, height), 0, 0);
  const scaled = scaledFrameCanvas(fullCanvas, width, height);
  disposeCanvas(fullCanvas);
  return scaled;
}

async function decodeGifWithFallback(data, loadToken) {
  const bytes = new Uint8Array(data);
  const reader = makeGifReader(bytes);
  const signature = reader.text(6);

  if (signature !== "GIF87a" && signature !== "GIF89a") {
    throw new Error("The selected file is not a valid GIF.");
  }

  const screenWidth = reader.u16();
  const screenHeight = reader.u16();
  const area = screenWidth * screenHeight;

  if (!screenWidth || !screenHeight || area > MAX_FALLBACK_GIF_PIXELS) {
    throw new Error("This GIF is too large for the compatibility decoder. Try a smaller GIF or use Chrome/Edge.");
  }

  const packed = reader.byte();
  const hasGlobalColorTable = Boolean(packed & 0x80);
  const globalColorTableSize = 1 << ((packed & 0x07) + 1);
  const backgroundIndex = reader.byte();
  reader.byte();

  const globalColorTable = hasGlobalColorTable ? readColorTable(reader, globalColorTableSize) : null;
  const backgroundColor = globalColorTable?.[backgroundIndex] || [255, 255, 255];
  const background = [backgroundColor[0], backgroundColor[1], backgroundColor[2], 255];
  const canvasPixels = new Uint8ClampedArray(area * 4);
  fillGifRegion(canvasPixels, screenWidth, screenHeight, { left: 0, top: 0, width: screenWidth, height: screenHeight }, background);

  const frames = [];
  let gce = { disposal: 0, transparentIndex: null };
  let previous = null;
  let capped = false;

  try {
    while (reader.pos < bytes.length) {
      assertCurrentLoad(loadToken);
      const block = reader.byte();

      if (block === 0x3b) break;

      if (block === 0x21) {
        const label = reader.byte();
        if (label === 0xf9) {
          const size = reader.byte();
          if (size !== 4) throw new Error("Invalid GIF graphics control block.");
          const flags = reader.byte();
          const transparent = Boolean(flags & 1);
          reader.u16();
          const transparentIndex = reader.byte();
          reader.byte();
          gce = {
            disposal: (flags >> 2) & 0x07,
            transparentIndex: transparent ? transparentIndex : null
          };
        } else {
          reader.skipSubBlocks();
        }
        continue;
      }

      if (block !== 0x2c) {
        throw new Error("Invalid GIF block.");
      }

      if (frames.length >= MAX_DECODED_FRAMES) {
        capped = true;
        break;
      }

      const left = reader.u16();
      const top = reader.u16();
      const width = reader.u16();
      const height = reader.u16();
      const imagePacked = reader.byte();
      const hasLocalColorTable = Boolean(imagePacked & 0x80);
      const interlaced = Boolean(imagePacked & 0x40);
      const localColorTableSize = 1 << ((imagePacked & 0x07) + 1);
      const colorTable = hasLocalColorTable ? readColorTable(reader, localColorTableSize) : globalColorTable;
      const minCodeSize = reader.byte();
      const imageData = reader.subBlocks();

      if (!colorTable) throw new Error("GIF frame has no color table.");
      if (!width || !height) continue;

      applyGifDisposal(previous, canvasPixels, screenWidth, screenHeight, background);

      const decoded = decodeLzw(minCodeSize, imageData, width * height);
      const indices = interlaced ? deinterlace(decoded, width, height) : decoded;
      const rect = { left, top, width, height };
      const backup = gce.disposal === 3 ? canvasPixels.slice() : null;

      drawGifFrame(canvasPixels, screenWidth, screenHeight, { ...rect, indices }, colorTable, gce.transparentIndex);
      frames.push(canvasFromGifPixels(canvasPixels, screenWidth, screenHeight));

      previous = { disposal: gce.disposal, rect, backup };
      gce = { disposal: 0, transparentIndex: null };

      if (frames.length % 8 === 0) {
        setStatus("Loading", `Decoded ${frames.length} frame(s)...`);
        await yieldToBrowser();
      }
    }

    if (capped) {
      setStatus("Large GIF capped", `Loaded first ${MAX_DECODED_FRAMES} frames. Reduce frames before export.`);
    }
  } catch (err) {
    disposeFrames(frames);
    throw err;
  }

  return frames;
}

async function decodeGifFile(file, loadToken) {
  await maybeWarnForLargeGif(file);
  const data = await file.arrayBuffer();
  assertCurrentLoad(loadToken);

  let imageDecoderError = null;
  if ("ImageDecoder" in window) {
    try {
      return await decodeGifWithImageDecoder(data, file, loadToken);
    } catch (err) {
      imageDecoderError = err;
      if (err.cancelled) throw err;
      console.warn("ImageDecoder failed, trying compatibility GIF decoder.", err);
    }
  }

  try {
    return await decodeGifWithFallback(data, loadToken);
  } catch (err) {
    if (imageDecoderError && !err.cancelled) {
      throw new Error(`GIF decode failed. ImageDecoder: ${imageDecoderError.message || imageDecoderError}; fallback: ${err.message || err}`);
    }
    throw err;
  }
}

function drawFitTo128(source) {
  const out = document.createElement("canvas");
  out.width = WIDTH;
  out.height = HEIGHT;
  const octx = out.getContext("2d", { willReadFrequently: true });
  octx.fillStyle = "white";
  octx.fillRect(0, 0, WIDTH, HEIGHT);

  if (!source || source.width <= 0 || source.height <= 0) {
    return out;
  }

  const fitMode = el("fitMode").value;
  const scale = fitMode === "cover"
    ? Math.max(WIDTH / source.width, HEIGHT / source.height)
    : Math.min(WIDTH / source.width, HEIGHT / source.height);

  const dw = Math.max(1, Math.round(source.width * scale));
  const dh = Math.max(1, Math.round(source.height * scale));
  const dx = Math.round((WIDTH - dw) / 2);
  const dy = Math.round((HEIGHT - dh) / 2);
  octx.drawImage(source, dx, dy, dw, dh);
  return out;
}

function sharpenGray(gray, amount) {
  if (amount <= 0) return gray;

  const out = new Float32Array(gray.length);

  for (let y = 0; y < HEIGHT; y++) {
    const y0 = Math.max(0, y - 1);
    const y1 = y;
    const y2 = Math.min(HEIGHT - 1, y + 1);

    for (let x = 0; x < WIDTH; x++) {
      const x0 = Math.max(0, x - 1);
      const x1 = x;
      const x2 = Math.min(WIDTH - 1, x + 1);

      const idx = y * WIDTH + x;
      const blur =
        (
          gray[y0 * WIDTH + x0] + gray[y0 * WIDTH + x1] + gray[y0 * WIDTH + x2] +
          gray[y1 * WIDTH + x0] + gray[y1 * WIDTH + x1] + gray[y1 * WIDTH + x2] +
          gray[y2 * WIDTH + x0] + gray[y2 * WIDTH + x1] + gray[y2 * WIDTH + x2]
        ) / 9;

      out[idx] = clamp(gray[idx] + (gray[idx] - blur) * amount, 0, 255);
    }
  }

  return out;
}

function processFrameToCanvas(source) {
  const fitted = drawFitTo128(source);
  const fctx = fitted.getContext("2d", { willReadFrequently: true });
  const img = fctx.getImageData(0, 0, WIDTH, HEIGHT);
  const data = img.data;

  const threshold = intNumber("threshold", 140, 0, 255);
  const contrast = number("contrast", 2.2, 0.2, 4);
  const brightness = intNumber("brightness", 0, -100, 100);
  const sharpen = number("sharpen", 0.0, 0, 3);

  let gray = new Float32Array(WIDTH * HEIGHT);

  for (let p = 0, i = 0; i < data.length; i += 4, p++) {
    const baseGray = data[i] * 0.299 + data[i + 1] * 0.587 + data[i + 2] * 0.114;
    gray[p] = clamp((baseGray - 128) * contrast + 128 + brightness, 0, 255);
  }

  gray = sharpenGray(gray, sharpen);

  for (let p = 0, i = 0; i < data.length; i += 4, p++) {
    const dark = gray[p] <= threshold;
    data[i] = dark ? PREVIEW_FG[0] : PREVIEW_BG[0];
    data[i + 1] = dark ? PREVIEW_FG[1] : PREVIEW_BG[1];
    data[i + 2] = dark ? PREVIEW_FG[2] : PREVIEW_BG[2];
    data[i + 3] = 255;
  }

  fctx.putImageData(img, 0, 0);
  return fitted;
}

function getProcessedFrame(sourceIndex) {
  const cacheKey = `${conversionKey()}|${sourceIndex}`;
  if (state.processCache.has(cacheKey)) {
    const cached = state.processCache.get(cacheKey);
    state.processCache.delete(cacheKey);
    state.processCache.set(cacheKey, cached);
    return cached;
  }

  const source = state.sourceFrames[sourceIndex];
  const processed = processFrameToCanvas(source);
  state.processCache.set(cacheKey, processed);

  while (state.processCache.size > MAX_CACHE_FRAMES) {
    const oldestKey = state.processCache.keys().next().value;
    const oldCanvas = state.processCache.get(oldestKey);
    state.processCache.delete(oldestKey);
    disposeCanvas(oldCanvas);
  }

  return processed;
}

function currentSourceIndex() {
  if (!state.activeIndices.length) return null;
  return state.activeIndices[state.current] ?? null;
}

function scheduleRefresh(withThumbs = true) {
  if (state.previewTimer) clearTimeout(state.previewTimer);
  state.previewTimer = setTimeout(() => {
    state.previewTimer = null;
    refreshPreview(false);
  }, 25);

  if (withThumbs) {
    if (state.thumbsTimer) clearTimeout(state.thumbsTimer);
    state.thumbsTimer = setTimeout(() => {
      state.thumbsTimer = null;
      renderThumbs();
    }, 180);
  }
}

function refreshPreview(skipThumbs = false) {
  updateOutputs();

  const sourceIndex = currentSourceIndex();
  if (sourceIndex === null) {
    ctx.fillStyle = `rgb(${PREVIEW_BG[0]},${PREVIEW_BG[1]},${PREVIEW_BG[2]})`;
    ctx.fillRect(0, 0, WIDTH, HEIGHT);
    updateStats();
    updateOutputText();
    if (!skipThumbs) renderThumbs();
    return;
  }

  const processed = getProcessedFrame(sourceIndex);
  ctx.drawImage(processed, 0, 0);
  el("frameSlider").max = Math.max(0, state.activeIndices.length - 1);
  el("frameSlider").value = state.current;
  updateStats();
  updateOutputText();
  if (!skipThumbs) renderThumbs();
}

function updateStats() {
  const active = state.activeIndices.length;
  el("stats").innerHTML = `
    <span>Original: ${state.sourceFrames.length}</span>
    <span>Active: ${active}</span>
    <span>Removed: ${state.removedIndices.size}</span>
    <span>Frame: ${active ? state.current + 1 : 0}/${active}</span>
  `;
  el("exportBtn").disabled = active === 0;
}

function packNameValue() {
  return sanitizeName(el("packName").value, "MomentumPack", MAX_PACK_NAME_LENGTH);
}

function animationBaseValue() {
  return sanitizeName(el("animationName").value, "animation", MAX_ANIMATION_NAME_LENGTH);
}

function buildPlaybackPlan(frameCount) {
  const basePassive = Math.min(Math.max(1, intFieldValue("passiveFrames", 1, 1, frameCount)), frameCount);
  const baseActive = Math.max(0, frameCount - basePassive);
  const holdLast = intFieldValue("holdLastFrame", 0, 0, MAX_HOLD_FRAMES);
  const order = Array.from({ length: frameCount }, (_, i) => i);

  for (let i = 0; i < holdLast; i++) {
    order.push(frameCount - 1);
  }

  return {
    passive: baseActive > 0 ? basePassive : basePassive + holdLast,
    active: baseActive > 0 ? baseActive + holdLast : 0,
    holdLast,
    order
  };
}

function updateOutputText() {
  const activeCount = state.activeIndices.length;
  if (!activeCount) {
    el("outputText").textContent = "No GIF loaded.";
    return;
  }

  const pack = packNameValue();
  const anim = animationBaseValue() + "_128x64";
  const playback = buildPlaybackPlan(activeCount);

  el("outputText").textContent =
`Pack folder:
${pack}/Anims/

Animation folder:
${anim}

Original frames: ${state.sourceFrames.length}
Active frames: ${activeCount}
Removed frames: ${state.removedIndices.size}
Passive frames: ${playback.passive}
Active animation frames: ${playback.active}
Frame order entries: ${playback.order.length}
Hold last frame repeats: ${playback.holdLast}
Frame rate: ${intFieldValue("frameRate", 5, 1, 60)} fps
Threshold: ${intNumber("threshold", 140, 0, 255)}
Contrast: ${number("contrast", 2.2, 0.2, 4).toFixed(1)}
Brightness: ${intNumber("brightness", 0, -100, 100)}
Sharpen: ${number("sharpen", 0, 0, 3).toFixed(1)}

Export will create:
${pack}/Anims/manifest.txt
${pack}/Anims/${anim}/meta.txt
${pack}/Anims/${anim}/frame_0.bm ...`;
}

async function loadGif(file) {
  const loadToken = ++state.loadToken;
  const fileName = file && file.name ? file.name : "";
  const fileType = file && file.type ? file.type.toLowerCase() : "";
  const looksLikeGif = fileName.toLowerCase().endsWith(".gif") || fileType.includes("gif");

  if (!file || !looksLikeGif) {
    clearProjectFrames();
    refreshPreview();
    el("gifFile").value = "";
    setStatus("Load failed", "Please choose a GIF file.", true);
    return;
  }

  clearProjectFrames();
  setStatus("Loading", "Decoding GIF frames...");
  el("fileName").textContent = fileName;

  const baseName = fileName.replace(/\.[^.]+$/, "");
  state.originalName = sanitizeName(baseName, "animation", MAX_ANIMATION_NAME_LENGTH);
  el("animationName").value = state.originalName;

  let frames = [];
  try {
    frames = await decodeGifFile(file, loadToken);
    if (loadToken !== state.loadToken) {
      disposeFrames(frames);
      return;
    }
    if (!frames.length) throw new Error("No GIF frames were decoded.");

    state.sourceFrames = frames;
    state.activeIndices = frames.map((_, i) => i);
    state.removedIndices = new Set();
    state.removedStack = [];
    state.current = 0;
    el("targetFrames").value = Math.min(50, frames.length);
    el("trimStart").value = 0;
    el("trimEnd").value = 0;
    refreshPreview();
    setStatus("Loaded", `${frames.length} frame(s) decoded.`);
    el("gifFile").value = "";
  } catch (err) {
    disposeFrames(frames);
    if (err.cancelled) return;
    console.error(err);
    clearProjectFrames();
    refreshPreview();
    el("gifFile").value = "";
    setStatus("Load failed", err.message || String(err), true);
  }
}

function markRemoved(indices) {
  for (const idx of indices) {
    if (!state.removedIndices.has(idx)) {
      state.removedIndices.add(idx);
      state.removedStack.push(idx);
    }
  }
}

function reduceEvenly() {
  if (!state.activeIndices.length) return;
  const current = state.activeIndices.slice();
  const target = intNumber("targetFrames", current.length, 1, current.length);

  if (target >= current.length) {
    setStatus("No reduction", "Target frame count is not lower than active frame count.");
    return;
  }

  let picked;
  if (target === 1) {
    picked = [current[0]];
  } else {
    const step = (current.length - 1) / (target - 1);
    picked = [];
    const seen = new Set();
    for (let i = 0; i < target; i++) {
      const idx = current[Math.round(i * step)];
      if (!seen.has(idx)) {
        picked.push(idx);
        seen.add(idx);
      }
    }
    let cursor = 0;
    while (picked.length < target && cursor < current.length) {
      const idx = current[cursor++];
      if (!seen.has(idx)) picked.push(idx);
    }
    picked.sort((a, b) => a - b);
  }

  const pickedSet = new Set(picked);
  markRemoved(current.filter(idx => !pickedSet.has(idx)));
  state.activeIndices = picked;
  state.current = Math.min(state.current, state.activeIndices.length - 1);
  refreshPreview();
  setStatus("Reduced", `Active frames reduced to ${state.activeIndices.length}.`);
}

function applyTrim() {
  if (!state.activeIndices.length) return;
  const start = intNumber("trimStart", 0, 0);
  const end = intNumber("trimEnd", 0, 0);
  const total = state.activeIndices.length;

  if (start + end >= total) {
    setStatus("Trim blocked", "Trim would remove every frame.", true);
    return;
  }

  markRemoved(state.activeIndices.slice(0, start));
  markRemoved(state.activeIndices.slice(total - end));

  state.activeIndices = state.activeIndices.slice(start, total - end);
  state.current = 0;
  refreshPreview();
  setStatus("Trimmed", `Active frames now ${state.activeIndices.length}.`);
}

function removeCurrentFrame() {
  if (state.activeIndices.length <= 1) {
    setStatus("Remove blocked", "You must keep at least one frame.", true);
    return;
  }

  const sourceIndex = state.activeIndices[state.current];
  markRemoved([sourceIndex]);
  state.activeIndices.splice(state.current, 1);
  state.current = Math.min(state.current, state.activeIndices.length - 1);
  refreshPreview();
  setStatus("Frame removed", `Removed original frame ${sourceIndex}.`);
}

function restoreFrame(sourceIndex) {
  if (!state.removedIndices.has(sourceIndex)) return;
  state.removedIndices.delete(sourceIndex);
  state.removedStack = state.removedStack.filter(idx => idx !== sourceIndex);
  state.activeIndices.push(sourceIndex);
  state.activeIndices.sort((a, b) => a - b);
  state.current = state.activeIndices.indexOf(sourceIndex);
}

function restoreLastRemoved() {
  while (state.removedStack.length) {
    const sourceIndex = state.removedStack.pop();
    if (state.removedIndices.has(sourceIndex)) {
      restoreFrame(sourceIndex);
      refreshPreview();
      setStatus("Frame restored", `Restored original frame ${sourceIndex}.`);
      return;
    }
  }
  setStatus("Nothing to restore", "No removed frames exist.");
}

function resetFrames() {
  clearPlayback();
  state.activeIndices = state.sourceFrames.map((_, i) => i);
  state.removedIndices = new Set();
  state.removedStack = [];
  state.current = 0;
  el("trimStart").value = 0;
  el("trimEnd").value = 0;
  el("targetFrames").value = Math.min(50, Math.max(1, state.activeIndices.length));
  refreshPreview();
  setStatus("Reset", "All frames restored.");
}

function applyPreset(kind) {
  if (kind === "dark") {
    el("threshold").value = 155;
    el("contrast").value = 2.4;
    el("brightness").value = -8;
    el("sharpen").value = 0.4;
  } else if (kind === "line") {
    el("threshold").value = 170;
    el("contrast").value = 3.0;
    el("brightness").value = 5;
    el("sharpen").value = 1.0;
  } else {
    el("threshold").value = 140;
    el("contrast").value = 2.2;
    el("brightness").value = 0;
    el("sharpen").value = 0.2;
  }

  clearCache();
  refreshPreview();
}

function renderThumbs() {
  const strip = el("thumbStrip");
  strip.innerHTML = "";

  if (!state.sourceFrames.length) {
    strip.textContent = "No frames loaded.";
    return;
  }

  const activeSet = new Set(state.activeIndices);
  const activeSourceIndex = currentSourceIndex();
  const limit = Math.min(state.sourceFrames.length, MAX_THUMBNAILS);
  const fragment = document.createDocumentFragment();

  for (let i = 0; i < limit; i++) {
    const wrapper = document.createElement("button");
    wrapper.type = "button";
    wrapper.className = "thumb";
    if (!activeSet.has(i)) wrapper.classList.add("removed");
    if (activeSourceIndex === i) wrapper.classList.add("active");

    const thumbCanvas = document.createElement("canvas");
    thumbCanvas.width = WIDTH;
    thumbCanvas.height = HEIGHT;
    thumbCanvas.getContext("2d").drawImage(getProcessedFrame(i), 0, 0);

    const label = document.createElement("small");
    label.textContent = activeSet.has(i) ? `#${i}` : `#${i} removed`;

    wrapper.appendChild(thumbCanvas);
    wrapper.appendChild(label);

    wrapper.addEventListener("click", () => {
      if (!activeSet.has(i)) {
        restoreFrame(i);
      }
      state.current = Math.max(0, state.activeIndices.indexOf(i));
      refreshPreview();
    });

    fragment.appendChild(wrapper);
  }

  strip.appendChild(fragment);

  if (state.sourceFrames.length > limit) {
    const more = document.createElement("div");
    more.className = "small-note";
    more.textContent = `Showing first ${limit} thumbnails of ${state.sourceFrames.length}. Export still uses all active frames.`;
    strip.appendChild(more);
  }
}

function canvasToBmBytes(processed) {
  const pctx = processed.getContext("2d", { willReadFrequently: true });
  const data = pctx.getImageData(0, 0, WIDTH, HEIGHT).data;
  const bytes = new Uint8Array((WIDTH * HEIGHT) / 8);
  let out = 0;

  for (let y = 0; y < HEIGHT; y++) {
    for (let x = 0; x < WIDTH; x += 8) {
      let b = 0;
      for (let bit = 0; bit < 8; bit++) {
        const idx = ((y * WIDTH) + (x + bit)) * 4;
        const dark = data[idx] === PREVIEW_FG[0] && data[idx + 1] === PREVIEW_FG[1] && data[idx + 2] === PREVIEW_FG[2];
        if (dark) b |= (1 << bit);
      }
      bytes[out++] = b;
    }
  }

  const bm = new Uint8Array(bytes.length + 1);
  bm[0] = 0;
  bm.set(bytes, 1);
  return bm;
}

function buildMeta(frameCount) {
  if (frameCount <= 0) {
    throw new Error("At least one frame is required to build meta.txt.");
  }

  const playback = buildPlaybackPlan(frameCount);
  const activeCycles = playback.active ? intFieldValue("activeCycles", 1, 1, META_MAX_VALUE) : 0;
  const activeCooldown = playback.active ? intFieldValue("activeCooldown", 1, 0, META_MAX_VALUE) : 0;

  return `Filetype: Flipper Animation
Version: 1

Width: ${WIDTH}
Height: ${HEIGHT}
Passive frames: ${playback.passive}
Active frames: ${playback.active}
Frames order: ${playback.order.join(" ")}
Active cycles: ${activeCycles}
Frame rate: ${intFieldValue("frameRate", 5, 1, 60)}
Duration: ${intFieldValue("duration", 360, 1, META_MAX_VALUE)}
Active cooldown: ${activeCooldown}

Bubble slots: 0
`;
}

function buildManifest(animDir) {
  const minButthurt = intFieldValue("minButthurt", 0, 0, 18);
  const maxButthurt = intFieldValue("maxButthurt", 18, minButthurt, 18);
  const minLevel = intFieldValue("minLevel", 1, 0, 30);
  const maxLevel = intFieldValue("maxLevel", 30, minLevel, 30);

  return `Filetype: Flipper Animation Manifest
Version: 1

Name: ${animDir}
Min butthurt: ${minButthurt}
Max butthurt: ${maxButthurt}
Min level: ${minLevel}
Max level: ${maxLevel}
Weight: ${intFieldValue("weight", 3, 1, META_MAX_VALUE)}
`;
}

function buildExportFiles() {
  if (!state.activeIndices.length) {
    throw new Error("Load a GIF first.");
  }

  const pack = packNameValue();
  const animBase = animationBaseValue();
  const animDir = `${animBase}_128x64`;
  const base = `${pack}/Anims/`;
  const frameBase = `${base}${animDir}/`;
  const files = [];

  files.push({ name: `${base}manifest.txt`, data: buildManifest(animDir) });
  files.push({ name: `${frameBase}meta.txt`, data: buildMeta(state.activeIndices.length) });

  state.activeIndices.forEach((sourceIndex, exportIndex) => {
    const processed = getProcessedFrame(sourceIndex);
    files.push({ name: `${frameBase}frame_${exportIndex}.bm`, data: canvasToBmBytes(processed) });
  });

  return { pack, animDir, files };
}

function exportZip() {
  try {
    clearPlayback();
    setStatus("Exporting", "Building BM files and ZIP...");

    const { pack, files } = buildExportFiles();
    const blob = window.SimpleZip.makeZip(files);
    if (!blob || blob.size <= 0) throw new Error("ZIP export produced an empty file.");

    const a = document.createElement("a");
    const url = URL.createObjectURL(blob);
    a.href = url;
    a.download = `${pack}.zip`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1500);

    setStatus("Export complete", `${pack}.zip created with ${state.activeIndices.length} frame(s).`);
  } catch (err) {
    console.error(err);
    setStatus("Export failed", err.message || String(err), true);
  }
}

function wireEvents() {
  el("gifFile").addEventListener("change", event => {
    const file = event.target.files?.[0];
    if (!file) return;

    loadGif(file).catch(err => {
      if (!err.cancelled) console.error(err);
    });
  });

  ["threshold", "contrast", "brightness", "sharpen", "fitMode"].forEach(id => {
    el(id).addEventListener("input", () => {
      clearCache();
      scheduleRefresh(true);
    });
  });

  ["frameRate", "packName", "animationName", "duration", "passiveFrames", "activeCycles",
   "activeCooldown", "holdLastFrame", "minButthurt", "maxButthurt", "minLevel", "maxLevel", "weight"].forEach(id => {
    el(id).addEventListener("input", () => scheduleRefresh(false));
  });

  el("frameSlider").addEventListener("input", () => {
    state.current = intNumber("frameSlider", 0, 0, Math.max(0, state.activeIndices.length - 1));
    refreshPreview(true);
  });

  el("prevBtn").addEventListener("click", () => {
    if (!state.activeIndices.length) return;
    state.current = (state.current - 1 + state.activeIndices.length) % state.activeIndices.length;
    refreshPreview();
  });

  el("nextBtn").addEventListener("click", () => {
    if (!state.activeIndices.length) return;
    state.current = (state.current + 1) % state.activeIndices.length;
    refreshPreview();
  });

  el("playBtn").addEventListener("click", () => {
    if (!state.activeIndices.length) return;

    if (state.playing) {
      clearPlayback();
      return;
    }

    state.playing = true;
    el("playBtn").textContent = "Stop";
    const delay = Math.max(20, Math.round(1000 / intFieldValue("frameRate", 5, 1, 60)));
    state.playTimer = setInterval(() => {
      state.current = (state.current + 1) % state.activeIndices.length;
      refreshPreview(true);
    }, delay);
  });

  el("reduceBtn").addEventListener("click", reduceEvenly);
  el("trimBtn").addEventListener("click", applyTrim);
  el("resetBtn").addEventListener("click", resetFrames);
  el("removeCurrentBtn").addEventListener("click", removeCurrentFrame);
  el("restoreLastBtn").addEventListener("click", restoreLastRemoved);
  el("presetBalancedBtn").addEventListener("click", () => applyPreset("balanced"));
  el("presetDarkBtn").addEventListener("click", () => applyPreset("dark"));
  el("presetLineBtn").addEventListener("click", () => applyPreset("line"));
  el("zoom2Btn").addEventListener("click", () => setPreviewScale(2));
  el("zoom3Btn").addEventListener("click", () => setPreviewScale(3));
  el("zoom4Btn").addEventListener("click", () => setPreviewScale(4));
  el("zoom5Btn").addEventListener("click", () => setPreviewScale(5));
  el("exportBtn").addEventListener("click", exportZip);
  window.addEventListener("beforeunload", () => {
    clearProjectFrames();
  });
}

wireEvents();
refreshPreview();
