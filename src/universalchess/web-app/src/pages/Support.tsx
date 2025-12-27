import './Support.css';

/**
 * Support page with links to project resources.
 */
export function Support() {
  return (
    <div className="support-page">
      <h1>Support</h1>

      <div className="support-cards">
        <a
          href="https://github.com/adrian-dybwad/Universal-Chess/issues"
          target="_blank"
          rel="noopener noreferrer"
          className="support-card"
        >
          <span className="card-icon">🐛</span>
          <h3>Report a Bug</h3>
          <p>Found an issue? Open a GitHub issue with details about what happened.</p>
        </a>

        <a
          href="https://github.com/adrian-dybwad/Universal-Chess/discussions"
          target="_blank"
          rel="noopener noreferrer"
          className="support-card"
        >
          <span className="card-icon">💬</span>
          <h3>Discussions</h3>
          <p>Join the community discussion, ask questions, and share ideas.</p>
        </a>

        <a
          href="https://github.com/adrian-dybwad/Universal-Chess"
          target="_blank"
          rel="noopener noreferrer"
          className="support-card"
        >
          <span className="card-icon">📖</span>
          <h3>Documentation</h3>
          <p>Read the project README and documentation on GitHub.</p>
        </a>

        <a
          href="https://github.com/adrian-dybwad/Universal-Chess/blob/main/CONTRIBUTING.md"
          target="_blank"
          rel="noopener noreferrer"
          className="support-card"
        >
          <span className="card-icon">🤝</span>
          <h3>Contribute</h3>
          <p>Want to help? Check out the contributing guide to get started.</p>
        </a>
      </div>

      <div className="attribution">
        <h2>Acknowledgments</h2>
        <p>
          Universal Chess is based on{' '}
          <a href="https://github.com/EdNekebno/DGTCentaur" target="_blank" rel="noopener noreferrer">
            DGTCentaur Mods
          </a>
          , originally created by Ed Nekebno and community contributors.
        </p>
        <p>
          Special thanks to all the open source chess engine authors whose work makes
          this project possible.
        </p>
      </div>
    </div>
  );
}

