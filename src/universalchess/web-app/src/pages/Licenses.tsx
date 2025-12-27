import { useState } from 'react';
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
    text: `GNU GENERAL PUBLIC LICENSE
Version 3, 29 June 2007

Copyright (C) 2007 Free Software Foundation, Inc.
Everyone is permitted to copy and distribute verbatim copies
of this license document, but changing it is not allowed.

...

(Full GPL-3.0 text available at the URL above)`,
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
    text: `BSD 2-Clause License

Copyright (c) 2021, Jeff Hlywa

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.`,
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
  const [expanded, setExpanded] = useState<string | null>(null);

  return (
    <div className="licenses-page">
      <h1>Open Source Licenses</h1>
      <p className="intro">
        Universal Chess is open source software built on the shoulders of giants.
        Below are the licenses for this project and its dependencies.
      </p>

      <div className="licenses-list">
        {licenses.map((license) => (
          <div key={license.name} className="license-card">
            <div
              className="license-header"
              onClick={() => setExpanded(expanded === license.name ? null : license.name)}
            >
              <div className="license-info">
                <h3>{license.name}</h3>
                <span className="license-type">{license.type}</span>
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

            {expanded === license.name && license.text && (
              <pre className="license-text">{license.text}</pre>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

