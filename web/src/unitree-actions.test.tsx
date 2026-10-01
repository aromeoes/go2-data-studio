// @vitest-environment happy-dom
import React, {act} from "react";
import {createRoot} from "react-dom/client";
import {it, expect, vi} from "vitest";
import {UnitreeActions} from "./UnitreeActions";
(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
it("lists upstream actions and only dispatches an explicitly confirmed selection", async () => {
  const fetchMock=vi.spyOn(globalThis,"fetch").mockResolvedValue({ok:true,json:async()=>({actions:[{name:"Hello",description:"Greeting",category:"Gestures",available:true,api_id:1016},{name:"BodyHeight",description:"Height",category:"Settings",available:false,reason:"Requires arguments"}]})} as Response);
  const host=document.createElement("div");document.body.append(host);const root=createRoot(host), api=vi.fn().mockResolvedValue({message:"Acknowledged"});
  try {
    await act(async()=>root.render(<UnitreeActions connected mode="idle" stopped={false} epoch={3} enabled api={api}/>));
    await act(async()=>{host.querySelector("details")!.open=true;host.querySelector("details")!.dispatchEvent(new Event("toggle"));});
    expect(host.querySelectorAll("option")).toHaveLength(2);
    const button=(name:string)=>[...host.querySelectorAll("button")].find(b=>b.textContent===name)!;
    await act(async()=>button("Run selected action").click());
    expect(api).not.toHaveBeenCalled();
    expect(host.querySelector("dialog")?.open).toBe(true);
    await act(async()=>button("Run Hello").click());
    expect(api).toHaveBeenCalledExactlyOnceWith("/unitree/action",{name:"Hello",confirmed:"Hello",epoch:3});
    expect(host.textContent).toContain("Acknowledged");
    await act(async()=>{const select=host.querySelector("select")!;select.value="BodyHeight";select.dispatchEvent(new Event("change",{bubbles:true}));});
    expect(button("Run selected action").disabled).toBe(true);
    expect(host.textContent).toContain("Requires arguments");
  } finally {await act(async()=>root.unmount());host.remove();fetchMock.mockRestore();}
});
