'use strict';
(()=>{
 const labels={collections:'Nos univers',acheter:'Les modes d’achat',catalogue:'Catalogue Signature',origine:'Fournisseurs',groupage:'Groupage Chine–Cameroun',boutique:'Boutique KHENTY',partenaires:'Devenir fournisseur'};
 if(typeof HTMLDialogElement==='undefined')return; // Keep normal anchors on unsupported browsers.
 const depot=document.createElement('div');depot.hidden=true;depot.id='rubriques-reserve';document.body.append(depot);
 const entries=new Map();for(const id of Object.keys(labels)){const node=document.getElementById(id);if(!node)continue;const marker=document.createComment('Position '+id);node.before(marker);entries.set(id,{node,marker});if(id!=='collections')depot.append(node);}
 const editorial=document.querySelector('.editorial-band');const shop=entries.get('boutique')?.node.querySelector('.wrap');if(editorial&&shop)shop.append(editorial);
 const addLinks=(parent,links,cls='rubrique-links')=>{const group=document.createElement('div');group.className=cls;for(const [target,label]of links){const a=document.createElement('a');a.href='#'+target;a.textContent=label;group.append(a);}parent.append(group);return group;};
 if(shop)addLinks(shop,[['catalogue','Découvrir les 8 concepts Signature'],['catalogue','Explorer Fashion & Prestige']]);
 const quick=document.createElement('div');quick.className='home-quicklinks';const quickTitle=document.createElement('h3');quickTitle.textContent='Votre expérience KHENTY';quick.append(quickTitle);addLinks(quick,[['catalogue','Catalogue Signature'],['acheter','Choisir son mode d’achat'],['groupage','Groupage Chine–Cameroun'],['origine','Découvrir les fournisseurs']]);document.querySelector('#collections>.wrap')?.append(quick);
 const dialog=document.createElement('dialog');dialog.className='rubrique-window';dialog.id='rubrique-window';dialog.setAttribute('aria-labelledby','window-title');
 const bar=document.createElement('div');bar.className='window-bar';const title=document.createElement('h2');title.id='window-title';const actions=document.createElement('div');actions.className='window-actions';const back=document.createElement('button');back.type='button';back.textContent='Retour';back.setAttribute('aria-label','Revenir à la rubrique précédente');const close=document.createElement('button');close.type='button';close.textContent='Fermer';close.setAttribute('aria-label','Fermer la fenêtre et revenir à l’accueil');actions.append(back,close);bar.append(title,actions);
 const trail=document.createElement('p');trail.className='window-trail';const content=document.createElement('div');content.className='window-content';content.tabIndex=-1;dialog.append(bar,trail,content);document.body.append(dialog);
 let stack=[],active='',opener=null,homeScroll=0;
 function restore(){if(!active)return;const entry=entries.get(active);if(active==='collections')entry.marker.after(entry.node);else depot.append(entry.node);active='';}
 function show(){restore();const state=stack[stack.length-1];if(!state)return;active=state.id;content.append(entries.get(active).node);title.textContent=labels[active];trail.textContent='Accueil / '+stack.map(s=>labels[s.id]).join(' / ');back.hidden=stack.length<2;content.scrollTop=state.scroll||0;if(!dialog.open){homeScroll=window.scrollY;dialog.showModal();document.body.classList.add('rubrique-open');}close.focus({preventScroll:true});}
 function route(id,fromLink=false){if(!entries.has(id))return;if(!dialog.open&&fromLink)opener=document.activeElement;if(stack.length)stack[stack.length-1].scroll=content.scrollTop;if(stack[stack.length-1]?.id===id)return;stack.push({id,scroll:0});show();}
 function finish(){if(dialog.open)dialog.close();restore();stack=[];document.body.classList.remove('rubrique-open');window.scrollTo({top:homeScroll,behavior:'instant'});if(opener?.isConnected)opener.focus({preventScroll:true});opener=null;}
 function replaceHash(hash){history.replaceState(null,'',location.pathname+location.search+hash);}
 function closeAll(){finish();replaceHash('#accueil');}
 back.addEventListener('click',()=>{if(stack.length>1)history.back();else closeAll();});close.addEventListener('click',closeAll);
 dialog.addEventListener('cancel',e=>{e.preventDefault();closeAll();});
 dialog.addEventListener('click',e=>{if(e.target!==dialog)return;const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)closeAll();});
 document.addEventListener('click',e=>{const a=e.target.closest('a[href^="#"]');if(!a||e.defaultPrevented||e.button!==0||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;const id=a.getAttribute('href').slice(1);if(entries.has(id)){e.preventDefault();if(stack[stack.length-1]?.id===id)return;history.pushState({khentyWindow:id},'','#'+id);route(id,true);}else if(dialog.open&&(id==='accueil'||id==='contenu')){e.preventDefault();closeAll();}},true);
 function onHistory(){const id=location.hash.slice(1);if(!entries.has(id)){finish();return;}const existing=stack.map(s=>s.id).lastIndexOf(id);if(existing>=0){stack=stack.slice(0,existing+1);show();}else route(id);}
 window.addEventListener('popstate',onHistory);window.addEventListener('hashchange',()=>{const id=location.hash.slice(1);if(entries.has(id)&&active!==id)onHistory();});
 document.querySelectorAll('a[href^="#"]').forEach(a=>{if(entries.has(a.getAttribute('href').slice(1))){a.setAttribute('aria-haspopup','dialog');a.setAttribute('aria-controls','rubrique-window');}});
 const initial=location.hash.slice(1);if(entries.has(initial))route(initial);
})();
