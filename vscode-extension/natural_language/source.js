'use strict';
const fs = require('fs').promises;
const flags = require('fs').constants;
const path = require('path');
const crypto = require('crypto');
const {TextDecoder} = require('util');
const hash = value => crypto.createHash('sha256').update(value).digest('hex');
const MAX_FILE = 2 * 1024 * 1024;
const normalize = text => text.replace(/^\uFEFF/, '').replace(/\r\n?/g, '\n');
async function readSource(root, file) {
  if (typeof file !== 'string' || path.isAbsolute(file)) throw new Error('잘못된 소스 경로입니다.');
  const base = await fs.realpath(root), target = await fs.realpath(path.resolve(base, file));
  const relative = path.relative(base, target);
  if (relative === '..' || relative.startsWith('..' + path.sep) || path.isAbsolute(relative)) throw new Error('프로젝트 밖의 파일은 읽지 않습니다.');
  // Read at most MAX_FILE+1 even if the file grows after stat.
  const info = await fs.stat(target);
  if (!info.isFile() || info.size > MAX_FILE) throw new Error('2MB 이하의 일반 소스 파일만 지원합니다.');
  const handle = await fs.open(target, flags.O_RDONLY | (flags.O_NOFOLLOW || 0) | (flags.O_NONBLOCK || 0));
  try {
    const stat = await handle.stat();
    if (!stat.isFile() || stat.size > MAX_FILE) throw new Error('2MB 이하의 일반 소스 파일만 지원합니다.');
    const buffer = Buffer.alloc(MAX_FILE + 1);
    let bytesRead = 0;
    while (bytesRead < buffer.length) {
      const part = await handle.read(buffer, bytesRead, buffer.length - bytesRead, bytesRead);
      if (!part.bytesRead) break;
      bytesRead += part.bytesRead;
    }
    if (bytesRead > MAX_FILE) throw new Error('소스 파일이 너무 큽니다.');
    try { return normalize(new TextDecoder('utf-8', {fatal:true}).decode(buffer.subarray(0, bytesRead))); }
    catch { throw new Error('AI 설명은 UTF-8 소스 파일을 지원합니다.'); }
  } finally { await handle.close(); }
}
async function checkSnapshot(root, context) {
  for (const [file,digest] of Object.entries(context.snapshots)) {
    if (hash(await readSource(root,file)) !== digest) throw new Error('미리보기 이후 코드가 변경되었습니다. 저장·재분석 후 다시 준비하세요.');
  }
}
module.exports = {checkSnapshot, readSource, hash};
