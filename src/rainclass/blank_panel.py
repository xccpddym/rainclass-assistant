"""Locate the visible, separate 填空题作答 panel without broad page filling."""
EDITOR_SELECTOR='input:not([type=hidden]):not([type=password]):not([type=radio]):not([type=checkbox]):not([type=button]):not([type=submit]):not([type=file]):not([type=image]):not([type=range]):not([type=color]):not([type=reset]),textarea,[contenteditable="true"],[contenteditable=""],[contenteditable="plaintext-only"]'


def fields(root):
    return [n for n in root.query_selector_all(EDITOR_SELECTOR) if n.is_visible() and n.evaluate(
        "e=>(e.tagName!=='INPUT'||['text','search','email','tel','url','number'].includes(e.type))&&!e.disabled&&!e.readOnly&&!e.closest('[aria-disabled=true]')&&!(e.parentElement.closest('[contenteditable=true],[contenteditable=\"\"],[contenteditable=plaintext-only]'))")]


def panel(page,kind='blank'):
    title=page.locator(':text-is("填空题作答"):visible' if kind=='blank' else ':text-is("主观题作答"):visible,:text-is("简答题作答"):visible')
    if title.count()!=1:return None
    handle=title.element_handle().evaluate_handle('''e=>{
      const visible=n=>n.getClientRects().length&&getComputedStyle(n).visibility!=='hidden';
      for(let p=e.parentElement;p&&p!==document.body;p=p.parentElement){
        if(p.querySelector('.slide__wrap'))return null;
        const inputs=Array.from(p.querySelectorAll('input,textarea,[contenteditable]')).filter(visible);
        const buttons=Array.from(p.querySelectorAll('button,[role=button],.submit-btn')).filter(n=>visible(n)&&n.innerText.trim()==='提交答案');
        if(inputs.length&&buttons.length===1)return p;
      }
      return null;
    }''')
    return handle.as_element()


def ordered_fields(root):
    nodes=fields(root)
    numbers=[]
    for n in nodes:
        number=n.evaluate('''(e,root)=>{
          for(let p=e,i=0;p&&p!==root&&i<3;p=p.parentElement,i++){
            const s=p.previousElementSibling;
            if(s&&/^\\d+$/.test(s.innerText.trim()))return Number(s.innerText.trim());
          }
          return null;
        }''',root)
        numbers.append(number)
    if any(v is not None for v in numbers):
        if sorted(v for v in numbers if v is not None)!=list(range(1,len(nodes)+1)):return None
        nodes=[n for _,n in sorted(zip(numbers,nodes),key=lambda pair:pair[0])]
    return nodes
