import React,{useEffect,useState} from "react";
import {createRoot} from "react-dom/client";
import "./style.css";

const API=import.meta.env.VITE_API_URL||"http://localhost:8000";

function App(){
 const [mode,setMode]=useState("creative"),[topic,setTopic]=useState(""),[job,setJob]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState("");
 useEffect(()=>{if(!job?.id)return; const t=setInterval(async()=>{try{const r=await fetch(`${API}/jobs/${job.id}`);const d=await r.json();setJob(d);if(["completed","failed"].includes(d.status)){setBusy(false);clearInterval(t)}}catch(e){setError(e.message)}},3000);return()=>clearInterval(t)},[job?.id]);
 async function generate(){
  setError("");setBusy(true);setJob(null);
  try{const r=await fetch(`${API}/generate`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({mode,topic})});const d=await r.json();if(!r.ok)throw Error(d.detail||"Generation failed");setJob(d)}
  catch(e){setError(e.message);setBusy(false)}
 }
 async function regenerate(){if(!job?.topic)return;setBusy(true);setError("");const r=await fetch(`${API}/generate`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({mode:job.mode,topic:job.topic})});setJob(await r.json())}
 function createAnother(){setJob(null);setTopic("");setError("");setBusy(false)}
 const video=job?.video_url;
 return <main>
  <section className="card">
   <div className="brand">AI VIDEO STUDIO</div>
   <h1>Create short-form videos.</h1>
   <p className="muted">Generate a Reel / Short from one idea.</p>
   <label>Content type</label>
   <div className="modes"><button className={mode==="creative"?"active":""} onClick={()=>setMode("creative")}>Creative Reel</button><button className={mode==="business"?"active":""} onClick={()=>setMode("business")}>Business / Product</button></div>
   <label>{mode==="creative"?"Topic":"Product / business details"}</label>
   <textarea value={topic} onChange={e=>setTopic(e.target.value)} placeholder={mode==="creative"?"A mysterious abandoned military academy at night":"Describe the product, business and key selling point..."}/>
   <button className="generate" disabled={busy||!topic.trim()} onClick={generate}>{busy?"Generating…":"Generate Video"}</button>
   {job&&<div className="status"><b>{job.status==="completed"?"VIDEO READY":job.status==="failed"?"GENERATION FAILED":job.status.toUpperCase()}</b><span>{job.message||"GPU generation in progress…"}</span></div>}
   {error&&<div className="error">{error}</div>}
   {video&&<><video className="video" controls playsInline src={video}/><div className="actions"><a className="action primary" href={video} download>↓ Download</a><button className="action" onClick={regenerate}>↻ Regenerate</button><button className="action" onClick={createAnother}>＋ Create Another</button></div></>}
  </section>
 </main>
}
createRoot(document.getElementById("root")).render(<App/>);
