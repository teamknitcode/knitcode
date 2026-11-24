'use strict';
const fs = require('node:fs/promises');
const path = require('node:path');

function sameVersion(trace, node, digest) {
  const evidence = trace.files?.[node.file];
  return Boolean(digest && evidence?.changed_during_run === false &&
    evidence.sha256 === digest && evidence.sha256_after === digest);
}

function location(node) {
  return JSON.stringify([node.file, node.profile_first_line ?? node.lineno, node.name.split('.').at(-1)]);
}

function sameName(staticNode, runtimeNode) {
  if (!runtimeNode.qualified_name) return true;
  if (typeof runtimeNode.qualified_name !== 'string') return false;
  const qualified = runtimeNode.qualified_name.replaceAll('.<locals>.', '.');
  return staticNode.name === qualified || staticNode.name.endsWith('.' + qualified);
}

// Compare only outgoing call candidates with a unique function at the recorded location.
function observedCallees(trace, data, calleeIds, caller) {
  const destinations = new Set((trace.edges || [])
    .filter(e => e?.source === caller.id && e.count > 0).map(e => e.target));
  const byLocation = new Map();
  for (const n of data.nodes) {
    if (!calleeIds.has(n.id) || !['method', 'function'].includes(n.type) ||
        !sameVersion(trace, n, data.source_hashes?.[n.file])) continue;
    const key = location(n);
    if (!byLocation.has(key)) byLocation.set(key, []);
    byLocation.get(key).push(n);
  }
  const names = new Set();
  for (const n of trace.nodes) {
    if (n?.kind !== 'FUNCTION' || !destinations.has(n.id)) continue;
    const candidates = byLocation.get(JSON.stringify([n.file, n.first_line, n.name])) || [];
    const matches = candidates.filter(c => sameName(c, n));
    if (matches.length === 1) names.add(matches[0].name);
  }
  return [...names].slice(0, 3);
}

// dynamic_value_flow.py --vscode-data keeps the source hashes from the selected export.
function valueFlowEvidence(report, target, digest) {
  const flow = report.dynamic_value_flow;
  if (flow.schema_version !== 1 || report.source_hashes?.[target.file] !== digest ||
      flow.file_verification?.[target.file] !== 'verified') {
    return '동적 값 흐름을 현재 소스와 대조할 수 없습니다. 동일 소스의 --vscode-data 통합 결과를 선택하세요.';
  }
  const entry = flow.functions?.[target.id];
  if (!entry) return '이번 값 흐름 기록에서는 이 함수의 관측값을 찾지 못했습니다.';
  const lines = [`동적 값 흐름 · ${flow.trace_complete ? '완료 기록' : '부분 기록'}`];
  function describe(label, slot) {
    const types = Array.isArray(slot?.inferred) ? slot.inferred
      .map(item => item?.type).filter(type => typeof type === 'string').slice(0, 6) : [];
    if (types.length) {
      const mismatch = slot.mismatch === true ? ' (선언 타입과 불일치)' : '';
      lines.push(`${label}: ${types.join(', ')}${mismatch}`);
    }
  }
  for (const [name, slot] of Object.entries(entry.parameters || {}).slice(0, 12)) describe(name, slot);
  describe('반환', entry.returns);
  describe('yield', entry.yields);
  return lines.join(' · ');
}

async function runtimeEvidence(root, traceFile, target, digest, data, calleeIds) {
  let trace;
  try {
    const filename = path.resolve(root, traceFile);
    const stat = await fs.stat(filename);
    if (!stat.isFile() || stat.size > 32 * 1024 * 1024)
      return '실행 기록을 읽을 수 없습니다. 32 MiB 이하의 JSON 파일을 지정하세요.';
    trace = JSON.parse(await fs.readFile(filename, 'utf8'));
  } catch (error) {
    if (error.code === 'ENOENT') return '연결된 실행 기록이 없습니다.';
    return '실행 기록 파일을 열거나 해석할 수 없습니다.';
  }
  if (trace?.dynamic_value_flow) return valueFlowEvidence(trace,target,digest);
  if (trace?.format !== 'knitcode-profile-1' || !Array.isArray(trace.nodes))
    return 'KnitCode record 형식의 실행 기록이 필요합니다.';
  if (typeof trace.root !== 'string' || !path.isAbsolute(trace.root) || path.relative(root, trace.root) !== '')
    return '다른 프로젝트에서 수집한 실행 기록입니다.';
  if (!trace.files?.[target.file]) return '이번 실행 기록에서 이 파일의 관측 근거를 찾지 못했습니다.';
  if (!sameVersion(trace, target, digest)) return '실행 기록과 분석 소스의 버전이 달라 관측값을 제외했습니다.';
  const matches = trace.nodes.filter(n => n?.kind === 'FUNCTION' && n.file === target.file &&
    n.first_line === (target.profile_first_line ?? target.lineno) &&
    n.name === target.name.split('.').at(-1) && sameName(target, n));
  if (matches.length !== 1 || !Number.isSafeInteger(matches[0].profile_calls) || matches[0].profile_calls < 0)
    return '이번 기록에서 이 함수에 대응하는 실행 관측값을 특정하지 못했습니다.';
  const fn = matches[0];
  const status = trace.complete === true ? '수집 완료' : '부분 기록';
  const lines = [`이번 실행에서 ${target.name}의 프로파일 호출 이벤트 ${fn.profile_calls}회를 관측했습니다 (${status}).`];
  if (Array.isArray(trace.edges)) {
    const called = observedCallees(trace, data, calleeIds, fn);
    if (called.length) lines.push(`정적 호출 후보 중 ${called.join(', ')} 호출이 이 실행에서도 관측됐습니다.`);
  }
  const types = Array.isArray(fn.return_types) ? fn.return_types.filter(t => typeof t === 'string').slice(0, 5) : [];
  if (types.length) lines.push(`관측된 반환 타입은 ${types.join(', ')}입니다.`);
  return lines.join(' ');
}

function staticEvidence(data, target) {
  const role = data.architecture_hierarchy?.symbols?.[target.id];
  if (!role || role.basis === 'none') return [];
  const basis = {ast: 'AST 동작', mixed: '코드와 이름 단서', name: '이름 단서'};
  const lines = [`KnitCode는 ${basis[role.basis] || '정적 분석 결과'}를 근거로 이 코드의 역할을 ‘${role.label}’ 후보로 분류했습니다.`];
  for (const item of (role.evidence || []).slice(0, 3)) lines.push(`${item.line}행 · ${item.detail}`);
  return lines;
}

module.exports = {runtimeEvidence, staticEvidence};
