import { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { ConnectionStatus } from './ConnectionStatus';
import './Navbar.css';

interface NavItem {
  path: string;
  label: string;
  icon: string;
}

const navItems: NavItem[] = [
  { path: '/', label: 'Live Board', icon: '♟' },
  { path: '/games', label: 'Games', icon: '📋' },
  { path: '/settings', label: 'Settings', icon: '⚙️' },
  { path: '/licenses', label: 'Licenses', icon: '📜' },
  { path: '/support', label: 'Support', icon: '💬' },
];

/**
 * Main navigation bar.
 */
export function Navbar() {
  const [menuOpen, setMenuOpen] = useState(false);
  const location = useLocation();

  return (
    <nav className="navbar">
      <div className="navbar-brand">
        <Link to="/" className="navbar-logo">
          <span className="logo-icon">♞</span>
          <span className="logo-text">Universal Chess</span>
        </Link>
        <button
          className={`navbar-burger ${menuOpen ? 'is-active' : ''}`}
          onClick={() => setMenuOpen(!menuOpen)}
          aria-label="menu"
        >
          <span />
          <span />
          <span />
        </button>
      </div>

      <div className={`navbar-menu ${menuOpen ? 'is-active' : ''}`}>
        <div className="navbar-start">
          {navItems.map((item) => (
            <Link
              key={item.path}
              to={item.path}
              className={`navbar-item ${location.pathname === item.path ? 'is-active' : ''}`}
              onClick={() => setMenuOpen(false)}
            >
              <span className="nav-icon">{item.icon}</span>
              {item.label}
            </Link>
          ))}
        </div>
        <div className="navbar-end">
          <ConnectionStatus />
        </div>
      </div>

      <p className="navbar-tagline">Connect, play, and analyze chess on your smart chess board</p>
    </nav>
  );
}

