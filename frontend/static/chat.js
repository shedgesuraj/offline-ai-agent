const form=document.getElementById("chatForm"), input=document.getElementById("message"), box=document.getElementById("chatBox");
function esc(s){return String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]))}
async function send(message, approve="0"){
 const fd=new FormData(); fd.append("message",message); fd.append("approve",approve);
 const r=await fetch("/api/chat",{method:"POST",body:fd}); return await r.json();
}
form?.addEventListener("submit",async e=>{
 e.preventDefault(); const message=input.value.trim(); if(!message)return;
 box.innerHTML += `<div class="bubble user"><b>You</b><br>${esc(message)}</div>`; input.value="";
 try{
  let d=await send(message);
  let html=`<div class="bubble assistant"><b>Agent</b><br>${esc(d.response||d.error||"No response")}<br><small>Tool: ${esc(d.tool||"-")} | Verified: ${esc(d.verified)} | Plan: ${esc((d.plan||[]).join(" → "))}</small>`;
  if(d.approval_required){ html += `<br><button class="approveBtn">Approve this action once</button>`; }
  html += `</div>`; box.innerHTML += html;
  if(d.approval_required){
    const btn=box.querySelector('.approveBtn:last-child'); btn.onclick=async()=>{btn.disabled=true; btn.textContent='Running...'; const x=await send(message,"1"); btn.parentElement.innerHTML += `<br><b>Approved result:</b><br>${esc(x.response||x.error)}<br><small>Verified: ${esc(x.verified)}</small>`;};
  }
 }catch(err){box.innerHTML += `<div class="bubble assistant">Request failed: ${esc(err)}</div>`}
 box.scrollTop=box.scrollHeight;
});

