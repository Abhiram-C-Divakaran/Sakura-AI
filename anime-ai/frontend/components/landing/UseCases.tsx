import { PenLine, Search, Code2, Layers } from 'lucide-react';
export const UseCases = () => <section id="use-cases" className="landing-section landing-container">
  <div className="landing-section-heading"><p className="landing-eyebrow">BUILT FOR YOUR WORK</p><h2>One workspace for the way you work.</h2></div>
  <div className="landing-use-cases">{[
    {icon:PenLine,title:'Create',body:'Brainstorm, write, plan, and explore visual ideas.'},
    {icon:Search,title:'Research',body:'Explore information, summarize sources, and work with documents.'},
    {icon:Code2,title:'Build',body:'Work through real software projects with Sakura Code.'},
    {icon:Layers,title:'Organize',body:'Keep projects, files, conversations, and tasks together.'},
  ].map(({icon:Icon,title,body}) => <article key={title}><Icon size={27} /><h3>{title}</h3><p>{body}</p></article>)}</div>
</section>;
