export function featureLabels(entry:{features:{key:string;expected:string}[]}, keys:string[]):string[]{
  return keys.map(key=>entry.features.find(f=>f.key===key)?.expected==='absent'?`${key}（原文明确无）`:key)
}
