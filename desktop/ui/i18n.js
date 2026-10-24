'use strict';
// Only explicit application-copy markers are translated. Personal content is
// never scanned, replaced, sent to a translator, or written back to storage.
(function(scope){
 function createTranslator(initial={}){
  let language='zh-CN',catalog={...initial};
  const texts=new WeakMap(),attributes=new WeakMap(),titles=new WeakMap();
  function t(value){
   if(language!=='en'||typeof value!=='string')return value;
   if(Object.hasOwn(catalog,value))return catalog[value];
   const trimmed=value.trim();
   return Object.hasOwn(catalog,trimmed)?value.replace(trimmed,()=>catalog[trimmed]):value;
  }
  function applyStatic(root=scope.document){
   if(!root?.createTreeWalker)return;
   const walker=root.createTreeWalker(root,128);let comment;
   while((comment=walker.nextNode())){
    if(comment.data.trim()!=='i18n'||comment.nextSibling?.nodeType!==3)continue;
    const text=comment.nextSibling;if(!texts.has(text))texts.set(text,text.data);
    text.data=t(texts.get(text));
   }
   for(const node of root.querySelectorAll('[data-i18n-attrs]')){
    if(!attributes.has(node))attributes.set(node,new Map());
    const originals=attributes.get(node);
    for(const name of node.getAttribute('data-i18n-attrs').split(',')){
     if(!['aria-label','placeholder','title','alt'].includes(name))continue;
     if(!originals.has(name))originals.set(name,node.getAttribute(name));
     const value=originals.get(name);if(value!==null)node.setAttribute(name,t(value));
    }
   }
   root.documentElement.lang=language==='en'?'en':'zh-CN';
   if(typeof root.title==='string'){if(!titles.has(root))titles.set(root,root.title);root.title=t(titles.get(root));}
  }
  function notify(){applyStatic();if(scope.dispatchEvent&&scope.Event)scope.dispatchEvent(new scope.Event('evomyn-language-change'));}
  return Object.freeze({t,get language(){return language;},applyStatic,markStatic:applyStatic,
   setLanguage(value){if(!['zh-CN','en'].includes(value))throw new Error('Unsupported language');if(language===value){applyStatic();return;}language=value;notify();},
   setCatalog(value){catalog={...value};notify();}
  });
 }
 if(typeof module==='object'&&module.exports)module.exports={createTranslator};
 else if(!scope.EvoMynI18n)scope.EvoMynI18n=createTranslator();
})(globalThis);
