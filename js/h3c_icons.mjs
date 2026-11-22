import {setText} from './h3c_dom.mjs?v=584a9bf55653';
// Shared 24-unit stroke icons for Studio actions and navigation.
const paths={
 video:'M3 5h18v14H3z M3 9h18 M7 5v4 M17 5v4', audio:'M9 18V5l11-2v13 M9 9l11-2 M5 16a3 3 0 1 0 0 6 3 3 0 0 0 0-6 M17 14a3 3 0 1 0 0 6 3 3 0 0 0 0-6',
 text:'M4 5h16 M12 5v15 M8 20h8',plus:'M12 5v14 M5 12h14',trash:'M4 7h16 M9 7V4h6v3 M6 7l1 14h10l1-14 M10 10v8 M14 10v8',
 expand:'M6 9l6 6 6-6',collapse:'M6 15l6-6 6 6',left:'M15 5l-7 7 7 7',right:'M9 5l7 7-7 7',
 duplicate:'M8 8h12v13H8z M16 8V3H3v13h5',undo:'M8 4L3 9l5 5 M3 9h11a7 7 0 0 1 0 14',redo:'M16 4l5 5-5 5 M21 9H10a7 7 0 0 0 0 14',
 history:'M3 12a9 9 0 1 0 3-6 M3 3v6h6 M12 7v5l3 2',new:'M4 3h11l5 5v13H4z M15 3v6h5 M8 15h8 M12 11v8',
 settings:'M4 6h16 M4 12h16 M4 18h16 M8 3v6 M16 9v6 M10 15v6',download:'M12 3v12 M7 10l5 5 5-5 M4 16v5h16v-5',
 close:'M6 6l12 12 M18 6L6 18',play:'M7 4l14 8-14 8z',next:'M4 4l12 8-12 8z M20 4v16',all:'M3 5l10 7L3 19z M13 5l10 7-10 7',
 stills:'M3 5h18v15H3z M3 16l6-7 5 5 3-3 4 5 M16 8h1',viewer:'M3 4h18v14H3z M8 22h8 M12 18v4',
 story:'M4 3h16v18H4z M8 7h8 M8 11h8 M8 15h5',cast:'M8 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8 M2 21v-3a6 6 0 0 1 12 0v3 M16 4a4 4 0 0 1 0 8 M17 15a5 5 0 0 1 5 5v1',
 refs:'M8 3h13v13H8z M3 8v13h13 M10 13l4-4 5 5',prompt:'M4 4h16v13H9l-5 4z M8 8h8 M8 12h6',shots:'M3 5h18v15H3z M3 10h18 M8 5v5 M16 5v5 M10 13l5 3-5 3z',
 takes:'M3 5h14v12H3z M7 21h14V9 M6 9h8 M6 13h5',write:'M4 20h4L19 9l-4-4L4 16z M13.5 6.5l4 4',rewrite:'M20 11a8 8 0 0 0-14.3-4.9 M4 13a8 8 0 0 0 14.3 4.9 M5 3v4h4 M19 21v-4h-4',
 check:'M4 12.5l5 5L20 6.5',shuffle:'M3 7h3.5c2.5 0 3.5 1.2 5 5s2.5 5 5 5H21 M3 17h3.5c1.4 0 2.3-.4 3-1.3 M14.5 8.3c.7-.9 1.6-1.3 3-1.3H21 M18 4l3 3-3 3 M18 14l3 3-3 3',
 save:'M5 3h11l3 3v15H5z M8 3v5h7V3 M8 21v-7h8v7',image:'M3 5h18v14H3z M3 15l5-5 4 4 3-3 6 6 M15.5 9.5h.01',upload:'M12 16V3 M7 8l5-5 5 5 M4 16v5h16v-5',search:'M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14 M15 15l7 7',stop:'M5 5h14v14H5z',sound:'M4 9h4l5-4v14l-5-4H4z M16 9a4 4 0 0 1 0 6 M19 6a8 8 0 0 1 0 12',more:'M4 12h2 M11 12h2 M18 12h2',snap:'M5 3v11a7 7 0 0 0 14 0V3 M5 7h5 M14 7h5 M10 3v11a2 2 0 0 0 4 0V3',
};
export function icon(name) {
 const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
 for(const [key,value] of Object.entries({viewBox:'0 0 24 24',width:'18',height:'18',fill:'none',stroke:'currentColor','stroke-width':'1.6','stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true',focusable:'false'}))svg.setAttribute(key,value);
 const path=document.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('d',paths[name]??paths.more);svg.append(path);return svg;
}
export function setIconLabel(button,label) {button.title=label;button.setAttribute('aria-label',label);const caption=[...button.children].find(n=>n.classList.contains('h3ci-caption')||n.classList.contains('h3ci-sr'));if(caption)setText(caption,label);}
export function decorateIcon(button,name,label,{text=false}={}) {
 const caption=document.createElement('span');caption.textContent=label;caption.className=text?'h3ci-caption':'h3ci-sr';
 button.replaceChildren(icon(name),caption);button.classList.add('h3ci-button');setIconLabel(button,label);return button;
}
export function iconButton(name,label,action) {
 const button=document.createElement('button');button.type='button';button.className='h3ct-button';button.addEventListener('click',action);return decorateIcon(button,name,label);
}
