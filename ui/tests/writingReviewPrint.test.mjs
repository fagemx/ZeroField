import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {build} from 'esbuild';

const root = fileURLToPath(new URL('../..', import.meta.url));
function python(script, input) {
  return new Promise((resolve, reject) => {
    const child = spawn('python', ['-X', 'utf8', '-B', '-c', script], {cwd: root});
    let stdout = '', stderr = '';
    const timeout = setTimeout(() => child.kill(), 60000);
    child.stdout.on('data', data => stdout += data);
    child.stderr.on('data', data => stderr += data);
    child.on('error', error => {clearTimeout(timeout); reject(error);});
    child.on('close', code => {
      clearTimeout(timeout);
      if (code === 0) resolve(stdout);
      else reject(new Error(`Python exited ${code}\n${stdout}\n${stderr}`));
    });
    child.stdin.end(JSON.stringify(input));
  });
}

// Pure server renderer, actual sanitizer, and browser layout: no database or mock export HTML.
test('render_export → cleanPrintHtml → Chromium preserves manuscript layout without author HTML/CSS', {timeout: 90000}, async () => {
  const text = value => ({type: 'text', text: value});
  const paragraph = content => ({type: 'paragraph', content});
  const literal = '<img src="https://invalid.test/author" onerror="window.pwned=true"><script>window.pwned=true</script> & "quoted"';
  const doc = {type: 'doc', content: [
    paragraph([text('First'), {type: 'hardBreak'}, text('Second')]),
    paragraph([text('Top'), {type: 'hardBreak'}, {type: 'hardBreak'}, text('Bottom')]),
    paragraph([]),
    paragraph([text('繁體中文'), {type: 'hardBreak'}, text('第二行　保留空白 😀')]),
    paragraph([text(literal)]),
  ]};
  const title = '稿件 <script> & "Title"';
  const html = await python(`import json,sys
from project_docs.writing_files import render_export
value=json.load(sys.stdin)
sys.stdout.buffer.write(render_export(value['doc'], 'print', title=value['title']))`, {doc, title});
  assert.ok(html.includes('First\nSecond'), 'server hardBreak must reach the sanitizer');
  const bundle = await build({stdin: {
    contents: "import {cleanPrintHtml} from './src/writing/writingToolsModel.js';window.cleanPrintHtml=cleanPrintHtml;",
    resolveDir: fileURLToPath(new URL('..', import.meta.url)),
  }, bundle: true, write: false, format: 'iife'});
  const output = await python(String.raw`import json,sys
from playwright.sync_api import sync_playwright
value=json.load(sys.stdin)
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True)
 try:
  context=browser.new_context(viewport={'width':1280,'height':900})
  requests=[]
  context.on('request',lambda request:requests.append(request.url))
  context.route('**/*',lambda route:route.abort())
  page=context.new_page()
  page.add_script_tag(content=value['bundle'])
  clean=page.evaluate('(html)=>window.cleanPrintHtml(html)',value['html'])
  # Deliberately supplied author markup must not gain permission through the owned stylesheet.
  hostile=page.evaluate('(html)=>window.cleanPrintHtml(html)', '''<style>@import url(https://invalid.test/css);p{display:none}</style><link rel="stylesheet" href="https://invalid.test/link"><base href="https://invalid.test/"><p style="white-space:normal;background:url(https://invalid.test/background)" onclick="window.pwned=true">First
Second</p><script>window.pwned=true</script><iframe src="https://invalid.test/frame"></iframe><img src="https://invalid.test/image"><svg onload="window.pwned=true"></svg><a href="javascript:window.pwned=true">safe text</a>''')
  results=[]
  for media in ['screen','print']:
   page.emulate_media(media=media)
   page.set_content(clean)
   metrics=page.evaluate(r'''()=>{
    const ps=[...document.querySelectorAll('p')];
    const y=(p,word)=>{const node=p.firstChild,range=document.createRange(),start=node.textContent.indexOf(word);range.setStart(node,start);range.setEnd(node,start+word.length);return range.getBoundingClientRect().top;};
    return {texts:ps.map(p=>p.textContent),title:document.querySelector('h1').textContent,
      whiteSpace:getComputedStyle(ps[0]).whiteSpace,lineHeight:parseFloat(getComputedStyle(ps[0]).lineHeight),
      hardBreak:y(ps[0],'Second')-y(ps[0],'First'),blankLine:y(ps[1],'Bottom')-y(ps[1],'Top'),
      emptyHeight:ps[2].getBoundingClientRect().height,cjkBreak:y(ps[3],'第二行')-y(ps[3],'繁體中文'),
      active:document.querySelectorAll('script,img,iframe,link,svg,[style],[onclick]').length,
      csp:document.querySelector('meta[http-equiv="Content-Security-Policy"]').content};
   }''')
   assert metrics['hardBreak'] >= metrics['lineHeight']*.9, (media,metrics)
   assert metrics['blankLine'] >= metrics['lineHeight']*1.9, (media,metrics)
   assert metrics['emptyHeight'] >= metrics['lineHeight']*.9, (media,metrics)
   assert metrics['cjkBreak'] >= metrics['lineHeight']*.9, (media,metrics)
   assert metrics['texts']==['First\nSecond','Top\n\nBottom','','繁體中文\n第二行　保留空白 😀',value['literal']],metrics
   assert metrics['title']==value['title'],metrics
   assert metrics['active']==0,metrics
   assert "default-src 'none'" in metrics['csp'],metrics
   results.append({'media':media,**metrics})
  page.set_content(hostile)
  page.locator('p').click()
  assert page.locator('p').inner_text()=='First\nSecond'
  assert page.locator('body').inner_text().endswith('safe text')
  assert page.locator('script,img,iframe,link,base,svg,[style],[onclick],[href],[src]').count()==0
  assert page.locator('style').count()==1, 'only the bounded application-owned stylesheet survives'
  assert page.evaluate('getComputedStyle(document.querySelector("p")).display')=='block'
  assert page.evaluate('window.pwned===undefined')
  page.wait_for_timeout(100)
  assert requests==[],requests
  print(json.dumps({'layout':results,'authorMarkup':'stripped','requests':requests},ensure_ascii=False))
 finally:
  browser.close()
`, {bundle: bundle.outputFiles[0].text, html, title, literal});
  console.log(output.trim());
  assert.equal(JSON.parse(output).layout.length, 2);
});
