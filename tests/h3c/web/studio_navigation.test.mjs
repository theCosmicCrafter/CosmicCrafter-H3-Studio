import test from 'node:test';
import assert from 'node:assert/strict';
import {installDom} from './fake_dom.mjs';
import {iconButton,setIconLabel} from '../../../js/h3c_icons.mjs';
installDom();
test('dynamic action counts update accessible names without destroying the icon',()=>{
 const button=iconButton('all','Render remaining',()=>{}),svg=button.children[0];
 setIconLabel(button,'Render 12 remaining');
 assert.equal(button.getAttribute('aria-label'),'Render 12 remaining');assert.equal(button.title,'Render 12 remaining');assert.equal(button.textContent,'Render 12 remaining');assert.equal(button.children[0],svg);
 setIconLabel(button,'All rendered');assert.equal(button.getAttribute('aria-label'),'All rendered');assert.equal(button.children[0],svg);
});
