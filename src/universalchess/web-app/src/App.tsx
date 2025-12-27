import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { Navbar } from './components/Navbar';
import { LiveBoard } from './pages/LiveBoard';
import { Games } from './pages/Games';
import { Analyze } from './pages/Analyze';
import { Settings } from './pages/Settings';
import { Licenses } from './pages/Licenses';
import { Support } from './pages/Support';
import './App.css';

function App() {
  return (
    <BrowserRouter>
      <div className="app">
        <Navbar />
        <main className="main-content">
          <Routes>
            <Route path="/" element={<LiveBoard />} />
            <Route path="/games" element={<Games />} />
            <Route path="/analyze/:gameId" element={<Analyze />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/licenses" element={<Licenses />} />
            <Route path="/support" element={<Support />} />
          </Routes>
        </main>
        <footer className="footer">
          <p>
            Universal Chess — Open source chess board enhancements.{' '}
            <a href="https://github.com/adrian-dybwad/Universal-Chess" target="_blank" rel="noopener noreferrer">
              GitHub
            </a>
          </p>
        </footer>
      </div>
    </BrowserRouter>
  );
}

export default App;
