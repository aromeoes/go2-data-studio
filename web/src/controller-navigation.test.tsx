// @vitest-environment happy-dom
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import { focusNext, useControllerNavigation } from './useControllerNavigation';
(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
afterEach(() => { document.body.innerHTML = ''; vi.restoreAllMocks(); vi.unstubAllGlobals(); delete (navigator as any).getGamepads; });
function visible() {
  vi.spyOn(HTMLElement.prototype, 'getClientRects').mockReturnValue([{}] as any);
  vi.spyOn(HTMLElement.prototype, 'scrollIntoView').mockImplementation(() => {});
}
it('focus navigation skips disabled controls and stays in an open dialog', () => {
  visible();
  document.body.innerHTML='<button id="outside">Outside</button><div role="dialog"><button disabled>Skip</button><button id="first">First</button><button id="last">Last</button></div>';
  focusNext(1); expect(document.activeElement?.id).toBe('first');
  focusNext(1); expect(document.activeElement?.id).toBe('last');
  focusNext(1); expect(document.activeElement?.id).toBe('first');
});
it('activation requires a new press while disarmed and focused', async () => {
  visible();
  let next:FrameRequestCallback=()=>{}, enabled=true, focused=true;
  const buttons=Array.from({length:17},()=>({pressed:false}));
  const clicked=vi.fn();
  vi.stubGlobal('requestAnimationFrame',(fn:FrameRequestCallback)=>{next=fn;return 1;});
  vi.stubGlobal('cancelAnimationFrame',vi.fn());
  vi.spyOn(document,'hasFocus').mockImplementation(()=>focused);
  vi.spyOn(document,'hidden','get').mockReturnValue(false);
  Object.defineProperty(navigator,'getGamepads',{configurable:true,value:()=>[{connected:true,mapping:'standard',id:'pad',index:0,buttons,axes:[0,0,0,0]}]});
  const container=document.createElement('div'); document.body.append(container);
  const root=createRoot(container);
  function Harness(){useControllerNavigation(()=>enabled);return <button onClick={clicked}>Activate</button>;}
  await act(async()=>root.render(<Harness/>));
  container.querySelector('button')!.focus();
  await act(async()=>{buttons[0].pressed=true;next(0);next(16);});
  expect(clicked).not.toHaveBeenCalled();
  await act(async()=>{buttons[0].pressed=false;next(32);buttons[0].pressed=true;next(48);next(64);});
  expect(clicked).toHaveBeenCalledTimes(1);
  await act(async()=>{enabled=false;buttons[0].pressed=false;next(80);buttons[0].pressed=true;next(96);enabled=true;next(112);});
  expect(clicked).toHaveBeenCalledTimes(1);
  await act(async()=>{focused=false;buttons[0].pressed=false;next(128);buttons[0].pressed=true;next(144);focused=true;next(160);});
  expect(clicked).toHaveBeenCalledTimes(1);
  await act(async()=>root.unmount());
});
