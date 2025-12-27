import { useState } from 'react';
import { Card, Badge } from '../components/ui';
import './Licenses.css';

interface License {
  name: string;
  type: string;
  url?: string;
  text?: string;
}

const licenses: License[] = [
  {
    name: 'Universal Chess',
    type: 'GPL-3.0',
    url: 'https://github.com/adrian-dybwad/Universal-Chess/blob/main/LICENSE',
  },
  {
    name: 'DGTCentaur Mods (Original)',
    type: 'GPL-3.0',
    url: 'https://github.com/EdNekebno/DGTCentaur',
  },
  {
    name: 'react-chessboard',
    type: 'MIT',
    url: 'https://github.com/Clariity/react-chessboard',
  },
  {
    name: 'chess.js',
    type: 'BSD-2-Clause',
    url: 'https://github.com/jhlywa/chess.js',
  },
  {
    name: 'Stockfish',
    type: 'GPL-3.0',
    url: 'https://github.com/official-stockfish/Stockfish',
  },
  {
    name: 'React',
    type: 'MIT',
    url: 'https://github.com/facebook/react',
  },
  {
    name: 'Vite',
    type: 'MIT',
    url: 'https://github.com/vitejs/vite',
  },
  {
    name: 'Chart.js',
    type: 'MIT',
    url: 'https://github.com/chartjs/Chart.js',
  },
  {
    name: 'Zustand',
    type: 'MIT',
    url: 'https://github.com/pmndrs/zustand',
  },
];

/**
 * Licenses page showing all open source licenses.
 */
export function Licenses() {
  return (
    <div className="page container--lg">
      <h1 className="page-title mb-4">Open Source Licenses</h1>
      <p className="text-muted mb-6" style={{ lineHeight: 'var(--leading-relaxed)' }}>
        Universal Chess is open source software built on the shoulders of giants.
        Below are the licenses for this project and its dependencies.
      </p>

      <div className="flex flex-col gap-2">
        {licenses.map((license) => (
          <LicenseItem key={license.name} license={license} />
        ))}
      </div>
    </div>
  );
}

function LicenseItem({ license }: { license: License }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <Card
      className="license-card"
      onClick={() => license.text && setExpanded(!expanded)}
      style={{ cursor: license.text ? 'pointer' : 'default' }}
    >
      <div className="license-header">
        <div className="flex items-center gap-4">
          <h3 style={{ margin: 0, fontSize: 'var(--text-base)' }}>{license.name}</h3>
          <Badge>{license.type}</Badge>
        </div>
        {license.url && (
          <a
            href={license.url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
          >
            View on GitHub →
          </a>
        )}
      </div>

      {expanded && license.text && (
        <pre className="license-text">{license.text}</pre>
      )}
    </Card>
  );
}
