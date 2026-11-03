import React from 'react';
import Image from 'next/image';
import {Dialog,DialogContent,DialogTitle,DialogTrigger} from './ui/dialog';
import {VisuallyHidden} from './ui/visually-hidden';
import {About} from './About';
const Logo=React.forwardRef<HTMLButtonElement,{isCollapsed:boolean}>(({isCollapsed},ref)=>(
 <Dialog aria-describedby={undefined}>
  <DialogTrigger asChild>
   <button ref={ref} type="button" className={`meaty-brand ${isCollapsed?'meaty-brand-compact':''}`} aria-label="About MEATY">
    <Image src="/meaty-mark.png" alt="" width={isCollapsed?38:48} height={isCollapsed?38:48} className="shrink-0 object-contain" priority/>
    {!isCollapsed&&<span className="text-left"><strong>MEATY<span className="meaty-brand-dot">.</span></strong><small>GET TO THE MEAT OF IT.</small></span>}
   </button>
  </DialogTrigger>
  <DialogContent><VisuallyHidden><DialogTitle>About MEATY</DialogTitle></VisuallyHidden><About/></DialogContent>
 </Dialog>
));
Logo.displayName='Logo';export default Logo;
