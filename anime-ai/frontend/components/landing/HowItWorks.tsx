export const HowItWorks = () => <section id="how-it-works" className="landing-section landing-container">
  <div className="landing-section-heading"><p className="landing-eyebrow">HOW IT WORKS</p><h2>Get started in seconds.</h2></div>
  <ol className="landing-steps">{[
    ['Start a conversation','Ask a question, upload something, or start a project.'],
    ['Choose how Sakura helps','Chat, research, code, analyze files, or create images with available tools.'],
    ['Move toward a finished result','Sakura uses the relevant context and tools to help you complete the work.'],
  ].map(([title,description],i) => <li key={title}><span>{String(i+1).padStart(2,'0')}</span><div><h3>{title}</h3><p>{description}</p></div></li>)}</ol>
</section>;
