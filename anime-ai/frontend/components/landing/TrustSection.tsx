import { Lock, ShieldCheck, Hand, Activity } from 'lucide-react';
export const TrustSection = () => <section id="trust" className="landing-section landing-container">
  <div className="landing-section-heading"><p className="landing-eyebrow">BUILT FOR REAL WORK</p><h2>Your workspace. Your control.</h2></div>
  <div className="landing-trust">{[
    {icon:Lock,title:'Account access controls',body:'Conversations and resources are scoped to your account.'},
    {icon:ShieldCheck,title:'Execution controls',body:'Production code execution requires a configured isolated environment. Availability is shown in the workspace.'},
    {icon:Hand,title:'Controlled actions',body:'Sensitive actions can require your confirmation before they run.'},
    {icon:Activity,title:'Transparent status',body:'See when capabilities are unavailable, limited, or need setup.'},
  ].map(({icon:Icon,title,body}) => <article key={title}><Icon size={26} /><div><h3>{title}</h3><p>{body}</p></div></article>)}</div>
</section>;
