import { Card } from '../components/ui';
import './Support.css';

const supportLinks = [
  {
    icon: '🐛',
    title: 'Report a Bug',
    description: 'Found an issue? Open a GitHub issue with details about what happened.',
    url: 'https://github.com/adrian-dybwad/Universal-Chess/issues',
  },
  {
    icon: '💬',
    title: 'Discussions',
    description: 'Join the community discussion, ask questions, and share ideas.',
    url: 'https://github.com/adrian-dybwad/Universal-Chess/discussions',
  },
  {
    icon: '📖',
    title: 'Documentation',
    description: 'Read the project README and documentation on GitHub.',
    url: 'https://github.com/adrian-dybwad/Universal-Chess',
  },
  {
    icon: '🤝',
    title: 'Contribute',
    description: 'Want to help? Check out the contributing guide to get started.',
    url: 'https://github.com/adrian-dybwad/Universal-Chess/blob/main/CONTRIBUTING.md',
  },
];

/**
 * Support page with links to project resources.
 */
export function Support() {
  return (
    <div className="page container--lg">
      <h1 className="page-title mb-6">Support</h1>

      <div className="grid grid--auto-fit mb-6">
        {supportLinks.map((link) => (
          <a
            key={link.title}
            href={link.url}
            target="_blank"
            rel="noopener noreferrer"
            className="support-card"
          >
            <span className="support-icon">{link.icon}</span>
            <h3>{link.title}</h3>
            <p>{link.description}</p>
          </a>
        ))}
      </div>

      <Card variant="muted">
        <h2 style={{ fontSize: 'var(--text-lg)', marginBottom: 'var(--space-4)' }}>
          Acknowledgments
        </h2>
        <p className="text-muted" style={{ marginBottom: 'var(--space-3)' }}>
          Universal Chess is based on{' '}
          <a href="https://github.com/EdNekebno/DGTCentaur" target="_blank" rel="noopener noreferrer">
            DGTCentaur Mods
          </a>
          , originally created by Ed Nekebno and community contributors.
        </p>
        <p className="text-muted" style={{ marginBottom: 0 }}>
          Special thanks to all the open source chess engine authors whose work makes
          this project possible.
        </p>
      </Card>
    </div>
  );
}
