/* Tiny no-dependency ZIP writer using STORE method. */
(function () {
  const ZIP32_LIMIT = 0xffffffff;
  const UTF8_FLAG = 0x0800;

  function crcTable() {
    if (crcTable.cache) return crcTable.cache;
    const table = [];
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) {
        c = (c & 1) ? (0xedb88320 ^ (c >>> 1)) : (c >>> 1);
      }
      table[n] = c >>> 0;
    }
    crcTable.cache = table;
    return table;
  }

  function crc32(bytes) {
    const table = crcTable();
    let c = 0xffffffff;
    for (let i = 0; i < bytes.length; i++) {
      c = table[(c ^ bytes[i]) & 255] ^ (c >>> 8);
    }
    return (c ^ 0xffffffff) >>> 0;
  }

  function u16(n) {
    return [n & 255, (n >>> 8) & 255];
  }

  function u32(n) {
    return [n & 255, (n >>> 8) & 255, (n >>> 16) & 255, (n >>> 24) & 255];
  }

  function encodeText(text) {
    return new TextEncoder().encode(text);
  }

  function toBytes(data) {
    if (data instanceof Uint8Array) return data;
    if (data instanceof ArrayBuffer) return new Uint8Array(data);
    return encodeText(String(data));
  }

  function makeZip(files) {
    if (!Array.isArray(files) || files.length === 0) {
      throw new Error("No files were provided for ZIP export.");
    }

    if (files.length > 65535) {
      throw new Error("Too many files for this simple ZIP writer.");
    }

    const localParts = [];
    const centralParts = [];
    const seenNames = new Set();
    let offset = 0;

    for (const file of files) {
      const safeName = String(file.name || "").replace(/^\/+/, "");
      if (!safeName) throw new Error("ZIP file entry has no name.");
      if (seenNames.has(safeName)) throw new Error(`Duplicate ZIP entry: ${safeName}`);
      seenNames.add(safeName);

      const nameBytes = encodeText(safeName);
      const data = toBytes(file.data);
      const crc = crc32(data);
      if (nameBytes.length > 65535) throw new Error(`ZIP entry name is too long: ${safeName}`);
      if (data.length > ZIP32_LIMIT) throw new Error(`ZIP entry is too large: ${safeName}`);

      const localHeader = new Uint8Array([
        0x50,0x4b,0x03,0x04,
        ...u16(20), ...u16(UTF8_FLAG), ...u16(0),
        ...u16(0), ...u16(0),
        ...u32(crc), ...u32(data.length), ...u32(data.length),
        ...u16(nameBytes.length), ...u16(0)
      ]);

      localParts.push(localHeader, nameBytes, data);

      const centralHeader = new Uint8Array([
        0x50,0x4b,0x01,0x02,
        ...u16(20), ...u16(20), ...u16(UTF8_FLAG), ...u16(0),
        ...u16(0), ...u16(0),
        ...u32(crc), ...u32(data.length), ...u32(data.length),
        ...u16(nameBytes.length), ...u16(0), ...u16(0),
        ...u16(0), ...u16(0), ...u32(0), ...u32(offset)
      ]);

      centralParts.push(centralHeader, nameBytes);
      offset += localHeader.length + nameBytes.length + data.length;
      if (offset > ZIP32_LIMIT) throw new Error("ZIP archive is too large for this exporter.");
    }

    const centralStart = offset;
    const centralSize = centralParts.reduce((sum, part) => sum + part.length, 0);
    if (centralStart + centralSize > ZIP32_LIMIT) {
      throw new Error("ZIP archive is too large for this exporter.");
    }

    const end = new Uint8Array([
      0x50,0x4b,0x05,0x06,
      ...u16(0), ...u16(0),
      ...u16(files.length), ...u16(files.length),
      ...u32(centralSize), ...u32(centralStart),
      ...u16(0)
    ]);

    return new Blob([...localParts, ...centralParts, end], { type: "application/zip" });
  }

  window.SimpleZip = { makeZip };
})();
