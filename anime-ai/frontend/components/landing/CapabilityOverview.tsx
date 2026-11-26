import { useEffect, useState } from 'react';
import { MessageCircle, Code2, Image, FileText, Layers } from 'lucide-react';
import { apiUrl } from '../../lib/api';
type Capabilities = { subsystems?: Record<string, {status?: string}>; providers?: Record<string, {status?: string}> };
const cards = [
  {title:'AI Chat', icon:MessageCircle, key:'chat', description:'Ask questions, brainstorm, summarize, write, and reason through problems in natural conversation.'},
  {title:'Sakura Code', icon:Code2, key:'sakura_code', description:'Inspect repositories, plan changes, edit files, run tests with a configured execution environment, and review the diff.'},
  {title:'Image Generation', icon:Image, key:'image_gen', description:'Turn ideas into original visuals with an available image provider, directly inside your workspace.'},
  {title:'Files & Knowledge', icon:FileText, key:'rag_engine', description:'Upload supported documents, notes, and code to analyze, summarize, and use in your work.'},
  {title:'Projects & Workflows', icon:Layers, key:'projects', description:'Keep conversations, repositories, files, and tasks organized around the work that matters.'},
];
export const CapabilityOverview = () => {
  const [capabilities,setCapabilities]=useState<Capabilities | null>(null);
  useEffect(() => {
    const controller=new AbortController();
    fetch(apiUrl('/api/v1/capabilities'), {signal:controller.signal}).then(res => {
      if (!res.ok) throw new Error('Status unavailable');
      return res.json();
    }).then(setCapabilities).catch(() => {});
    return () => controller.abort();
  }, []);
  const label = (key:string) => {
    if (key === 'projects') return 'Workspace organization';
    if (!capabilities) return 'Check availability in workspace';
    const status = key === 'chat'
      ? (Object.values(capabilities.providers || {}).some(p => p.status === 'AVAILABLE') ? 'AVAILABLE' : Object.values(capabilities.providers || {}).some(p => p.status === 'CONFIGURED') ? 'CONFIGURED' : 'UNAVAILABLE')
      : capabilities.subsystems?.[key]?.status;
    return ({AVAILABLE:'Available',DEGRADED:'Limited availability',CONFIGURED:'Configured · not yet verified',UNAVAILABLE:'Currently unavailable',NOT_CONFIGURED:'Setup required'} as Record<string,string>)[status || ''] || 'Check availability in workspace';
  };
  return <section id="capabilities" className="landing-section landing-container">
    <div className="landing-section-heading"><p className="landing-eyebrow">MORE THAN A CHATBOT</p><h2>Everything you need.<br />One intelligent workspace.</h2><p>Powerful AI models and practical tools to help you think, create, build, and stay organized.</p></div>
    <div className="landing-capabilities">{cards.map(({title,icon:Icon,key,description}) => <article key={key}><Icon size={28} /><h3>{title}</h3><p>{description}</p><small>{label(key)}</small></article>)}</div>
  </section>;
};
