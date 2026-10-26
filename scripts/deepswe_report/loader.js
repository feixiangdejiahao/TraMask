// Independently decode embedded evidence only when the reader asks for it.
function createEvidenceStore(index) {
  const stats=window.__deepswePerformance={ready:false,decodedCases:[],decodedAssets:[],decodedStories:[],searchDecoded:false,decodes:{},pending:0};
  const trials=new Map(),assets=new Map(),stories=new Map();
  let search;
  async function chunkNode(id) {
    let node=document.getElementById(id);
    if(!node && document.readyState==='loading') {
      await new Promise(resolve=>document.addEventListener('DOMContentLoaded',resolve,{once:true}));
      node=document.getElementById(id);
    }
    if(!node) throw new Error(`Missing embedded data: ${id}`);
    return node;
  }
  async function decode(descriptor,json) {
    if(typeof DecompressionStream==='undefined') throw new Error('This browser cannot decode gzip data. Please use a current browser. / 浏览器不支持 gzip 解码，请使用较新版本浏览器。');
    stats.pending++;
    try {
      const node=await chunkNode(descriptor.chunk);
      const binary=atob(node.textContent.trim()),bytes=new Uint8Array(binary.length);
      for(let i=0;i<binary.length;i++) bytes[i]=binary.charCodeAt(i);
      const stream=new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
      const value=await new Response(stream).text();
      stats.decodes[descriptor.chunk]=(stats.decodes[descriptor.chunk]||0)+1;
      return json ? JSON.parse(value) : value;
    } finally {stats.pending--;}
  }
  function cached(map,key,descriptor,json,done) {
    if(!map.has(key)) {
      const pending=decode(descriptor,json).then(value=>{done();return value;}).catch(error=>{map.delete(key);throw error;});
      map.set(key,pending);
    }
    return map.get(key);
  }
  return {
    stats,
    getCase(trial) {return cached(trials,trial,index.cases[trial],true,()=>stats.decodedCases.push(trial));},
    getAsset(id) {return cached(assets,id,index.assets[id],false,()=>stats.decodedAssets.push(id));},
    getStory(trial) {return cached(stories,trial,index.cases[trial].story,true,()=>stats.decodedStories.push(trial));},
    getSearch() {
      if(!search) search=decode(index.search,true).then(value=>{stats.searchDecoded=true;return value;}).catch(error=>{search=undefined;throw error;});
      return search;
    }
  };
}
