'use strict';
// Translate only complete, supported sentences. Never discard unknown clauses.
const VERSION = 'ko-patterns-1';
const nouns = new Map(Object.entries({
  'a file':'파일', 'the file':'파일', 'files':'파일들', 'a list':'목록', 'the list':'목록',
  'a string':'문자열', 'the string':'문자열', 'a dictionary':'딕셔너리', 'the dictionary':'딕셔너리',
  'a value':'값', 'the value':'값', 'values':'값들', 'the result':'결과', 'the results':'결과 목록',
  'results':'결과 목록', 'a list of results':'결과 목록', 'the input':'입력값',
  'the input string':'입력 문자열', 'the input data':'입력 데이터', 'data':'데이터', 'the data':'데이터',
  'the configuration':'설정', 'a configuration file':'설정 파일', 'the configuration file':'설정 파일',
  'a json string':'JSON 문자열', 'a json object':'JSON 객체', 'json':'JSON',
  'a list of strings':'문자열 목록', 'a list of files':'파일 목록', 'a list of subdomains':'서브도메인 목록',
  'the subdomains':'서브도메인 목록', 'a set':'집합', 'a set of values':'값의 집합',
  'the cache':'캐시', 'the response':'응답', 'the url':'URL', 'the path':'경로',
  'file':'파일', 'a file path':'파일 경로', 'the file path':'파일 경로', 'file path':'파일 경로',
  'list':'목록', 'string':'문자열', 'dictionary':'딕셔너리', 'configuration':'설정',
  'the sorted list':'정렬된 목록', 'a sorted list':'정렬된 목록',
  'the sorted list of results':'정렬된 결과 목록', 'a list of unique items':'중복 없는 항목 목록',
  'a json file':'JSON 파일', 'the json file':'JSON 파일', 'a dict':'딕셔너리',
  'a list of dicts':'딕셔너리 목록', 'the number of items':'항목 수', 'the number of files':'파일 수',
  'a boolean':'불리언 값', 'true':'참', 'false':'거짓', 'none':'None',
}));
function noun(value) {
  if (nouns.has(value.toLowerCase())) return nouns.get(value.toLowerCase());
  // Only explicitly quoted identifiers are passed through. Arbitrary prose is not a noun.
  if (/^`[A-Za-z_][A-Za-z0-9_.]*`$/.test(value)) return value;
  return null;
}
function object(value) {
  const last=value.replace(/`/g,'').at(-1), cp=last?.charCodeAt(0);
  return value + (cp>=0xac00 && cp<=0xd7a3 ? ((cp-0xac00)%28 ? '을' : '를') : '을/를');
}
const rules = [
  [/^(?:return|returns) (.+)$/i, x=>`${object(x)} 반환합니다.`],
  [/^(?:sort|sorts) (.+)$/i, x=>`${object(x)} 정렬합니다.`],
  [/^(?:read|reads) (.+)$/i, x=>`${object(x)} 읽습니다.`],
  [/^(?:save|saves) (.+)$/i, x=>`${object(x)} 저장합니다.`],
  [/^(?:load|loads) (.+)$/i, x=>`${object(x)} 불러옵니다.`],
  [/^(?:parse|parses) (.+)$/i, x=>`${object(x)} 파싱합니다.`],
  [/^(?:validate|validates) (.+)$/i, x=>`${object(x)} 검증합니다.`],
  [/^(?:create|creates) (.+)$/i, x=>`${object(x)} 생성합니다.`],
  [/^(?:delete|deletes) (.+)$/i, x=>`${object(x)} 삭제합니다.`],
  [/^(?:remove|removes) (?:duplicates|duplicate entries|duplicate items) from (.+)$/i,
    x=>`${x}에서 중복 항목을 제거합니다.`],
  [/^(?:convert|converts) (.+) (?:to|into) (.+)$/i, (a,b)=>`${object(a)} ${b} 형태로 변환합니다.`],
  [/^(?:read|reads) (.+) from (.+)$/i, (a,b)=>`${b}에서 ${object(a)} 읽습니다.`],
  [/^(?:save|saves|write|writes) (.+) to (.+)$/i, (a,b)=>`${object(a)} ${b}에 저장합니다.`],
  [/^(?:read|reads) (.+) into (.+)$/i, (a,b)=>`${object(a)} ${b} 형태로 읽습니다.`],
];
function translate(english) {
  const original=typeof english==='string' ? english.trim() : '';
  const unsupported=()=>({english:original,korean:null,status:'unsupported',rule:null});
  if (!original || original.length>1000 || /[\r\n]/.test(original)) return unsupported();
  const sentence=original.replace(/\s*[.]$/, '').trim();
  // Whole-sentence matching plus a closed noun vocabulary prevents partial translations.
  for (let i=0;i<rules.length;i++) {
    const match=sentence.match(rules[i][0]); if (!match) continue;
    const args=match.slice(1).map(noun); if (args.some(x=>x===null)) continue;
    return {english:original,korean:rules[i][1](...args),status:'translated',rule:`pattern-${i+1}`};
  }
  return unsupported();
}
module.exports={translate,VERSION};
