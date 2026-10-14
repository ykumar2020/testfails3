import * as THREE from "/static/vendor/three/three.module.min.js";

const $ = (id) => document.getElementById(id);
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const TAU = Math.PI * 2;
const GRID = 21;
const CELL = 1.5;
const HALF = GRID * CELL / 2;
const FIXED_DT = 1 / 60;
const MAX_TIME = 90;
const COLORS = [0xc8ff4d, 0xff5b4d, 0x36a3ff, 0xffc53d, 0xba68ff, 0x28e0c1];
const NAMES = ["EVO-01", "EMBER", "AZURE", "SOLAR", "VIOLET", "MINT"];
const canvas = $("arena-canvas");

function rngFromSeed(seed) {
  let s = (Number(seed) >>> 0) || 1;
  return () => { s ^= s << 13; s ^= s >>> 17; s ^= s << 5; return (s >>> 0) / 4294967296; };
}
function hashSeed(value) {
  const text = String(value).trim();
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) { h ^= text.charCodeAt(i); h = Math.imul(h, 16777619); }
  return h >>> 0;
}
function genome(rng) {
  return { speed: 2.2 + rng() * 2.5, turn: 2.2 + rng() * 3.8, sensor: 7 + rng() * 8, damage: 7 + rng() * 10, cooldown: .38 + rng() * .72, aggression: .35 + rng() * .62, evade: .2 + rng() * .75, armor: rng() };
}
function mutate(g, rng, scale=.16) {
  const n = (v, lo, hi) => clamp(v + (rng() * 2 - 1) * (hi - lo) * scale, lo, hi);
  return {speed:n(g.speed,2.2,4.7),turn:n(g.turn,2.2,6),sensor:n(g.sensor,7,15),damage:n(g.damage,7,17),cooldown:n(g.cooldown,.38,1.1),aggression:n(g.aggression,.35,.97),evade:n(g.evade,.2,.95),armor:n(g.armor,0,1)};
}
function trial(g, variant) {
  const dt=.08, enemy={x:8-variant*.7,z:-5+variant*2.6,hp:100}, bot={x:-8+variant,z:5-variant*.8,hp:100}, cover={x:(variant-1.5)*1.7,z:0,r:2};
  let shots=0,hits=0,moved=0,near=0,cool=0;
  for(let step=0;step<240&&bot.hp>0&&enemy.hp>0;step++){
    const dx=enemy.x-bot.x,dz=enemy.z-bot.z,dist=Math.hypot(dx,dz)||1;
    const low=bot.hp<38, desired=low?Math.atan2(-dx,-dz):Math.atan2(dx,dz);
    const heading=desired + Math.sin(step*.21+variant)*(.35*g.evade);
    const pace=g.speed*dt*(low?.75:1); const nx=bot.x+Math.sin(heading)*pace,nz=bot.z+Math.cos(heading)*pace;
    if(Math.hypot(nx-cover.x,nz-cover.z)>cover.r){bot.x=nx;bot.z=nz;moved+=pace;}
    cool-=dt;
    const lineBlocked=Math.abs((cover.x-(bot.x+enemy.x)/2))<1.8&&Math.abs((cover.z-(bot.z+enemy.z)/2))<1.8;
    if(dist<g.sensor&&!lineBlocked&&cool<=0){shots++;const accuracy=clamp(.94-dist/(g.sensor*2)-g.speed*.025, .18,.9);if(((step*37+variant*19)%100)/100<accuracy){enemy.hp-=g.damage;hits++;}cool=g.cooldown;}
    if(dist<12&&!lineBlocked&&step%Math.max(5,Math.round(11-g.aggression*5))===0)bot.hp-=8*(1-g.armor*.35);
    near+=Math.max(0,1-dist/24);
  }
  return (100-enemy.hp)*1.6 + bot.hp*.5 + hits*2 - shots*.18 + near*.025 + moved*.03 - g.speed*g.speed*.55 - g.sensor*.18 - g.damage*.25 - (1-g.cooldown)*4;
}
function evolve(seed) {
  const rng=rngFromSeed(seed^0x9e3779b9), POP=18, GENS=12;
  let pop=Array.from({length:POP},()=>genome(rng)), best=null;
  for(let generation=0;generation<GENS;generation++){
    const ranked=pop.map(g=>({g,fitness:[0,1,2,3].reduce((s,v)=>s+trial(g,v),0)/4})).sort((a,b)=>b.fitness-a.fitness);
    best=ranked[0]; const elite=ranked.slice(0,5).map(x=>x.g); pop=[...elite];
    while(pop.length<POP)pop.push(mutate(elite[Math.floor(rng()*elite.length)],rng,.19-generation*.008));
  }
  return {genome:best.g,fitness:best.fitness,generations:GENS,evaluations:POP*GENS*4};
}

let renderer,scene,camera,arenaGroup,clockLast=performance.now(),accumulator=0;
let cameraMode=0,azimuth=.72,elevation=.83,radius=35,drag=null;
let seedInput=$("seed").value.trim(),seed=hashSeed(seedInput),rng=rngFromSeed(seed),obstacles=[],blocked=[],robots=[],shots=[],events=[];
let running=false,finished=false,simTime=0,replans=0,totalShots=0,totalHits=0,totalDistance=0,evolution=null;

function initThree(){
  try{
    renderer=new THREE.WebGLRenderer({canvas,antialias:true,alpha:true}); renderer.setPixelRatio(Math.min(devicePixelRatio,2)); renderer.shadowMap.enabled=true; renderer.shadowMap.type=THREE.PCFSoftShadowMap;
    scene=new THREE.Scene(); scene.fog=new THREE.FogExp2(0x080b11,.026); camera=new THREE.PerspectiveCamera(48,1,.1,120); arenaGroup=new THREE.Group(); scene.add(arenaGroup);
    scene.add(new THREE.HemisphereLight(0xaacbff,0x142033,2.1)); const sun=new THREE.DirectionalLight(0xffffff,2.3);sun.position.set(-8,18,9);sun.castShadow=true;sun.shadow.mapSize.set(1024,1024);scene.add(sun);
    const floor=new THREE.Mesh(new THREE.PlaneGeometry(GRID*CELL,GRID*CELL),new THREE.MeshStandardMaterial({color:0x111a27,roughness:.92,metalness:.08}));floor.rotation.x=-Math.PI/2;floor.receiveShadow=true;arenaGroup.add(floor);
    const grid=new THREE.GridHelper(GRID*CELL,GRID,0x52617a,0x263246);grid.position.y=.012;arenaGroup.add(grid);
    const rim=new THREE.Mesh(new THREE.BoxGeometry(GRID*CELL+1,.45,GRID*CELL+1),new THREE.MeshStandardMaterial({color:0x101822,wireframe:true,transparent:true,opacity:.3}));rim.position.y=-.28;arenaGroup.add(rim);
    resize(); $("render-state").textContent="WebGL live · fixed 60 Hz"; document.documentElement.dataset.robotArena="ready";
    addControls(); requestAnimationFrame(frame);
  }catch(err){$("render-state").textContent="WebGL unavailable";$("match-state").textContent="Renderer unavailable";console.error(err);}
}
function addControls(){
  canvas.addEventListener("pointerdown",e=>{drag={x:e.clientX,y:e.clientY,a:azimuth,e:elevation};canvas.setPointerCapture(e.pointerId)});
  canvas.addEventListener("pointermove",e=>{if(!drag||cameraMode!==0)return;azimuth=drag.a-(e.clientX-drag.x)*.007;elevation=clamp(drag.e+(e.clientY-drag.y)*.005,.32,1.28)});
  canvas.addEventListener("pointerup",()=>drag=null); canvas.addEventListener("wheel",e=>{radius=clamp(radius+e.deltaY*.02,18,54);e.preventDefault()},{passive:false});
  window.addEventListener("resize",resize);
  $("toggle").addEventListener("click",()=>{if(finished)resetMatch();running=!running;$("toggle").textContent=running?"Pause":"Start";$("match-state").textContent=running?"Autonomous match live":"Match paused"});
  $("reset").addEventListener("click",resetMatch); $("generate").addEventListener("click",generateExperiment);
  $("camera").addEventListener("click",()=>{cameraMode=(cameraMode+1)%3;$("camera").textContent=["Camera: orbit","Camera: overhead","Camera: follow EVO-01"][cameraMode]});
  $("export").addEventListener("click",exportEvidence);
}
function resize(){if(!renderer)return;const w=canvas.clientWidth,h=canvas.clientHeight;renderer.setSize(w,h,false);camera.aspect=w/h;camera.updateProjectionMatrix()}
function cellOf(x,z){return {x:clamp(Math.floor((x+HALF)/CELL),0,GRID-1),y:clamp(Math.floor((z+HALF)/CELL),0,GRID-1)}}
function worldOf(x,y){return {x:(x+.5)*CELL-HALF,z:(y+.5)*CELL-HALF}}
function index(x,y){return y*GRID+x}
function makeMap(){blocked=new Array(GRID*GRID).fill(false);for(const o of obstacles){const a=cellOf(o.x-o.w/2-.55,o.z-o.d/2-.55),b=cellOf(o.x+o.w/2+.55,o.z+o.d/2+.55);for(let y=a.y;y<=b.y;y++)for(let x=a.x;x<=b.x;x++)blocked[index(x,y)]=true}}
function astar(start,goal){
  const sk=index(start.x,start.y),gk=index(goal.x,goal.y); if(blocked[gk])return [];
  const open=[sk],came=new Int32Array(GRID*GRID).fill(-1),g=new Float32Array(GRID*GRID).fill(Infinity),f=new Float32Array(GRID*GRID).fill(Infinity);g[sk]=0;f[sk]=Math.abs(start.x-goal.x)+Math.abs(start.y-goal.y);
  while(open.length){open.sort((a,b)=>f[a]-f[b]);const cur=open.shift();if(cur===gk){const path=[];let c=cur;while(c!==sk&&c>=0){path.push(worldOf(c%GRID,Math.floor(c/GRID)));c=came[c]}return path.reverse()}
    const x=cur%GRID,y=Math.floor(cur/GRID);for(const [dx,dy] of [[1,0],[-1,0],[0,1],[0,-1]]){const nx=x+dx,ny=y+dy;if(nx<0||ny<0||nx>=GRID||ny>=GRID)continue;const ni=index(nx,ny);if(blocked[ni])continue;const ng=g[cur]+1;if(ng<g[ni]){came[ni]=cur;g[ni]=ng;f[ni]=ng+Math.abs(nx-goal.x)+Math.abs(ny-goal.y);if(!open.includes(ni))open.push(ni)}}}
  return [];
}
function addObstacle(x,z,w,d,h){const mesh=new THREE.Mesh(new THREE.BoxGeometry(w,h,d),new THREE.MeshStandardMaterial({color:0x26344a,roughness:.65,metalness:.4}));mesh.position.set(x,h/2,z);mesh.castShadow=mesh.receiveShadow=true;arenaGroup.add(mesh);obstacles.push({x,z,w,d,h,mesh})}
function clearDynamic(){for(const o of obstacles)arenaGroup.remove(o.mesh);for(const r of robots)arenaGroup.remove(r.mesh);for(const s of shots)arenaGroup.remove(s.mesh);obstacles=[];robots=[];shots=[]}
function buildRobot(color,scale=1){
  const root=new THREE.Group(),mat=new THREE.MeshStandardMaterial({color,roughness:.34,metalness:.63}),dark=new THREE.MeshStandardMaterial({color:0x111823,roughness:.5,metalness:.8}),glow=new THREE.MeshStandardMaterial({color,emissive:color,emissiveIntensity:1.3});
  const body=new THREE.Mesh(new THREE.BoxGeometry(1.15*scale,.58*scale,1.38*scale),mat);body.position.y=.64*scale;body.castShadow=true;root.add(body);
  for(const x of [-.68,.68]){const wheel=new THREE.Mesh(new THREE.CylinderGeometry(.31*scale,.31*scale,.22*scale,16),dark);wheel.rotation.z=Math.PI/2;wheel.position.set(x*scale,.36*scale,0);wheel.castShadow=true;root.add(wheel)}
  const head=new THREE.Mesh(new THREE.SphereGeometry(.35*scale,18,12),mat);head.position.y=1.17*scale;head.castShadow=true;root.add(head);const eye=new THREE.Mesh(new THREE.BoxGeometry(.46*scale,.1*scale,.06*scale),glow);eye.position.set(0,1.2*scale,.33*scale);root.add(eye);
  const gun=new THREE.Mesh(new THREE.CylinderGeometry(.065*scale,.09*scale,.72*scale,10),dark);gun.rotation.x=Math.PI/2;gun.position.set(.38*scale,.9*scale,.65*scale);root.add(gun);return root;
}
function addRobot(i,pos,g){const mesh=buildRobot(COLORS[i],i===0?1.05:.92);mesh.position.set(pos.x,0,pos.z);arenaGroup.add(mesh);robots.push({id:i,name:NAMES[i],color:COLORS[i],mesh,x:pos.x,z:pos.z,angle:0,hp:100,cool:0,path:[],pathAt:0,replan:0,genome:g,alive:true,kills:0,shots:0,hits:0,distance:0,state:"scan"})}
function baseline(i){return {speed:2.55+i*.17,turn:3.1+i*.14,sensor:10.5+(i%2),damage:9.4+i*.45,cooldown:.68+(i%3)*.07,aggression:.62+(i%4)*.07,evade:.4+(i%2)*.2,armor:.32+(i%3)*.13}}
function resetMatch(){
  rng=rngFromSeed(seed);clearDynamic();simTime=0;replans=0;totalShots=0;totalHits=0;totalDistance=0;events=[];finished=false;running=false;
  [[0,0,4.8,2.2,2.2],[-7,-1,2.6,6,2.7],[6,2,3,7,2.2],[-2,-7,6,2.4,3.2],[8,-7,2.7,4.7,2.6]].forEach(o=>addObstacle(...o));makeMap();
  const spawns=[{x:-13,z:-13},{x:13,z:13},{x:-13,z:13},{x:13,z:-13},{x:0,z:13},{x:0,z:-13}];spawns.forEach((p,i)=>addRobot(i,p,i===0?evolution.genome:baseline(i)));
  logEvent(`Seed ${seedInput}: six robots deployed; EVO-01 uses generation ${evolution.generations}.`);updateUI();$("toggle").disabled=false;$("reset").disabled=false;$("toggle").textContent="Start";$("match-state").textContent="Ready to run";
}
function generateExperiment(){seedInput=($("seed").value.trim().replace(/[^\w.-]/g,"").slice(0,32)||"1");$("seed").value=seedInput;seed=hashSeed(seedInput);$("metric-seed").textContent=seedInput;$("generate").disabled=true;$("match-state").textContent="Evolving challenger…";$("genome-name").textContent="Running fitness trials";setTimeout(()=>{evolution=evolve(seed);showGenome();resetMatch();$("generate").disabled=false;running=true;$("toggle").textContent="Pause";$("match-state").textContent="Autonomous match live"},30)}
function showGenome(){const g=evolution.genome;$("genome-name").textContent=`EVO-${seedInput.slice(-4)}`;$("genome-values").innerHTML=[["speed",`${g.speed.toFixed(2)} m/s`],["sensor",`${g.sensor.toFixed(1)} m`],["damage",g.damage.toFixed(1)],["cooldown",`${g.cooldown.toFixed(2)} s`],["aggression",g.aggression.toFixed(2)],["armor",g.armor.toFixed(2)]].map(([k,v])=>`<div><dt>${k}</dt><dd>${v}</dd></div>`).join("");$("evolution-proof").textContent=`Fitness ${evolution.fitness.toFixed(2)} · ${evolution.generations} generations · ${evolution.evaluations} deterministic scenario evaluations.`}
function blockedLine(ax,az,bx,bz){const steps=Math.ceil(Math.hypot(bx-ax,bz-az)/.35);for(let i=1;i<steps;i++){const t=i/steps,x=ax+(bx-ax)*t,z=az+(bz-az)*t;for(const o of obstacles)if(Math.abs(x-o.x)<o.w/2&&Math.abs(z-o.z)<o.d/2)return true}return false}
function nearestEnemy(r){let best=null,dist=Infinity;for(const e of robots)if(e.alive&&e!==r){const d=Math.hypot(e.x-r.x,e.z-r.z);if(d<dist){dist=d;best=e}}return {enemy:best,dist}}
function updateRobot(r,dt){
  if(!r.alive)return;r.cool-=dt;r.replan-=dt;const {enemy,dist}=nearestEnemy(r);if(!enemy)return;const g=r.genome,los=!blockedLine(r.x,r.z,enemy.x,enemy.z);
  r.state=r.hp<34?"evade":(los&&dist<g.sensor?"engage":"pursue");
  if(r.replan<=0||!r.path.length){let tx=enemy.x,tz=enemy.z;if(r.state==="evade"){const dx=r.x-enemy.x,dz=r.z-enemy.z,l=Math.hypot(dx,dz)||1;tx=clamp(r.x+dx/l*7,-HALF+1,HALF-1);tz=clamp(r.z+dz/l*7,-HALF+1,HALF-1)}r.path=astar(cellOf(r.x,r.z),cellOf(tx,tz));r.pathAt=0;r.replan=.7+rng()*.55;replans++}
  if(los&&dist<g.sensor&&r.cool<=0){fire(r,enemy);r.cool=g.cooldown}
  const shouldMove=r.state!=="engage"||dist>5.2||r.hp<34;if(shouldMove&&r.pathAt<r.path.length){const p=r.path[r.pathAt],dx=p.x-r.x,dz=p.z-r.z,d=Math.hypot(dx,dz);if(d<.3){r.pathAt++}else{const desired=Math.atan2(dx,dz),delta=Math.atan2(Math.sin(desired-r.angle),Math.cos(desired-r.angle));r.angle+=clamp(delta,-g.turn*dt,g.turn*dt);const step=Math.min(d,g.speed*dt*(r.state==="evade"?1.08:.9));const nx=r.x+Math.sin(r.angle)*step,nz=r.z+Math.cos(r.angle)*step;if(!blocked[index(cellOf(nx,nz).x,cellOf(nx,nz).y)]){r.x=nx;r.z=nz;r.distance+=step;totalDistance+=step}}}
  r.mesh.position.set(r.x,0,r.z);r.mesh.rotation.y=r.angle;
}
function fire(r,target){const dir=new THREE.Vector3(target.x-r.x,0,target.z-r.z).normalize(),mesh=new THREE.Mesh(new THREE.SphereGeometry(.12,8,6),new THREE.MeshBasicMaterial({color:r.color}));mesh.position.set(r.x,.9,r.z);arenaGroup.add(mesh);shots.push({mesh,x:r.x,z:r.z,vx:dir.x*14,vz:dir.z*14,life:1.4,owner:r});r.shots++;totalShots++;if(totalShots<8||totalShots%12===0)logEvent(`${r.name} fires while in ${r.state} state.`)}
function updateShots(dt){for(let i=shots.length-1;i>=0;i--){const s=shots[i],ox=s.x,oz=s.z;s.x+=s.vx*dt;s.z+=s.vz*dt;s.life-=dt;s.mesh.position.set(s.x,.9,s.z);let remove=s.life<=0||blockedLine(ox,oz,s.x,s.z);for(const r of robots)if(!remove&&r.alive&&r!==s.owner&&Math.hypot(r.x-s.x,r.z-s.z)<.72){const damage=s.owner.genome.damage*(1-r.genome.armor*.32);r.hp=clamp(r.hp-damage,0,100);s.owner.hits++;totalHits++;remove=true;if(r.hp<=0){r.alive=false;r.mesh.visible=false;s.owner.kills++;logEvent(`${r.name} eliminated by ${s.owner.name} at ${simTime.toFixed(1)} s.`)}}if(remove){arenaGroup.remove(s.mesh);shots.splice(i,1)}}}
function step(dt){simTime+=dt;for(const r of robots)updateRobot(r,dt);updateShots(dt);const alive=robots.filter(r=>r.alive);if(alive.length<=1||simTime>=MAX_TIME){finished=true;running=false;const winner=alive.length===1?alive[0]:[...alive].sort((a,b)=>b.hp-a.hp)[0];$("match-state").textContent=winner?`${winner.name} wins`:"No winner";$("toggle").textContent="Run again";logEvent(winner?`${winner.name} wins with ${winner.hp.toFixed(1)} health and ${winner.kills} eliminations.`:"The match ended without a survivor.")}if(Math.floor(simTime*4)!==Math.floor((simTime-dt)*4))updateUI()}
function updateUI(){const alive=robots.filter(r=>r.alive).length;$("metric-time").textContent=`${simTime.toFixed(1)} s`;$("metric-alive").textContent=`${alive} / 6`;$("metric-replans").textContent=String(replans);$("metric-shots").textContent=`${totalShots} / ${totalHits}`;$("metric-distance").textContent=`${totalDistance.toFixed(1)} m`;$("score-strip").innerHTML=robots.map(r=>`<div class="bot-chip ${r.alive?"":"out"}" style="--bot:#${r.color.toString(16).padStart(6,"0")}"><strong>${r.name} · ${r.state}</strong><div class="health-track"><i style="width:${r.hp}%"></i></div></div>`).join("")}
function logEvent(text){events.push({time:Number(simTime.toFixed(3)),text});events=events.slice(-100);$("event-log").innerHTML=events.slice(-18).reverse().map(e=>`<li><b>${e.time.toFixed(1)}s</b> ${e.text}</li>`).join("")}
function setCamera(){let target=new THREE.Vector3(0,0,0);if(cameraMode===1){camera.position.set(.01,42,.01);camera.up.set(0,0,-1)}else if(cameraMode===2&&robots[0]){const r=robots[0];target.set(r.x,0,r.z);camera.position.set(r.x-8,9,r.z-10);camera.up.set(0,1,0)}else{camera.position.set(Math.sin(azimuth)*Math.cos(elevation)*radius,Math.sin(elevation)*radius,Math.cos(azimuth)*Math.cos(elevation)*radius);camera.up.set(0,1,0)}camera.lookAt(target)}
function frame(now){resize();const elapsed=Math.min(.1,(now-clockLast)/1000);clockLast=now;if(running){accumulator+=elapsed;while(accumulator>=FIXED_DT){step(FIXED_DT);accumulator-=FIXED_DT}}setCamera();renderer.render(scene,camera);requestAnimationFrame(frame)}
function exportEvidence(){const payload={schema:"testfails3.robot-arena.v1",createdAt:new Date().toISOString(),seed:seedInput,numericSeed:seed,evolution,arena:{grid:GRID,cellMeters:CELL,obstacles:obstacles.map(({x,z,w,d,h})=>({x,z,w,d,h}))},result:{elapsedSeconds:simTime,finished,winner:robots.filter(r=>r.alive).sort((a,b)=>b.hp-a.hp)[0]?.name||null,replans,shots:totalShots,hits:totalHits,distanceMeters:totalDistance,robots:robots.map(r=>({name:r.name,health:r.hp,alive:r.alive,kills:r.kills,shots:r.shots,hits:r.hits,distance:r.distance,genome:r.genome}))},events};const blob=new Blob([JSON.stringify(payload,null,2)],{type:"application/json"}),a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download=`robot-arena-${seedInput}.json`;a.click();URL.revokeObjectURL(a.href)}

window.__robotArena={version:1,getState:()=>({seed:seedInput,numericSeed:seed,simTime,running,finished,replans,totalShots,totalHits,alive:robots.filter(r=>r.alive).length,evolution})};
initThree();generateExperiment();
