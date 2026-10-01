// @vitest-environment happy-dom
import React, {act} from "react";
import {createRoot} from "react-dom/client";
import {expect,it,vi} from "vitest";
import {GenerateMapButton} from "./GenerateMapButton";
(globalThis as any).IS_REACT_ACT_ENVIRONMENT=true;
it("offers pause-and-generate in HumanCLI and explains actual disabled states",async()=>{
 const host=document.createElement("div"),root=createRoot(host),fn=vi.fn();
 const render=async(recording=false,pending=false)=>act(async()=>root.render(<GenerateMapButton recording={recording} pending={pending} mode="agent" onGenerate={fn}/>));
 await render();expect(host.textContent).toContain("Pause & generate map");
 await act(async()=>host.querySelector("button")!.click());expect(fn).toHaveBeenCalledOnce();
 await render(true);expect(host.querySelector("button")!.disabled).toBe(true);expect(host.textContent).toContain("Save this recording");
 await render(false,true);expect(host.querySelector("button")!.disabled).toBe(true);expect(host.textContent).toContain("current action");
 await act(async()=>root.unmount());
});
