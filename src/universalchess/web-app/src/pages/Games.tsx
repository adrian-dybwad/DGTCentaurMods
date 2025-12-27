import { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { Button, Card, Badge } from '../components/ui';
import type { GameRecord } from '../types/game';
import { apiFetch } from '../utils/api';
import './Games.css';

/**
 * Games history page.
 */
export function Games() {
  const [games, setGames] = useState<GameRecord[]>([]);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [expandedPgn, setExpandedPgn] = useState<Record<number, string>>({});

  const fetchGames = useCallback(async () => {
    setLoading(true);
    try {
      const response = await apiFetch(`/getgames/${page}`);
      const data = await response.json();
      const gameList = Object.values(data) as GameRecord[];
      setGames(gameList);
    } catch (e) {
      console.error('Failed to fetch games:', e);
      setGames([]);
    } finally {
      setLoading(false);
    }
  }, [page]);

  useEffect(() => {
    fetchGames();
  }, [fetchGames]);

  const togglePgn = async (gameId: number) => {
    if (expandedPgn[gameId]) {
      setExpandedPgn((prev) => {
        const next = { ...prev };
        delete next[gameId];
        return next;
      });
      return;
    }

    try {
      const response = await apiFetch(`/getpgn/${gameId}`);
      const pgn = await response.text();
      setExpandedPgn((prev) => ({ ...prev, [gameId]: pgn }));
    } catch (e) {
      console.error('Failed to fetch PGN:', e);
    }
  };

  const deleteGame = async (gameId: number) => {
    if (!confirm('Delete this game? This cannot be undone.')) return;
    try {
      await apiFetch(`/deletegame/${gameId}`);
      fetchGames();
    } catch (e) {
      console.error('Failed to delete game:', e);
    }
  };

  return (
    <div className="page container--lg">
      <div className="page-header">
        <h1 className="page-title">Game History</h1>
        <div className="flex gap-4 items-center">
          <Button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1}>
            ◀ Previous
          </Button>
          <span className="text-muted">Page {page}</span>
          <Button onClick={() => setPage((p) => p + 1)} disabled={games.length === 0}>
            Next ▶
          </Button>
        </div>
      </div>

      {loading ? (
        <div className="loading">Loading games...</div>
      ) : games.length === 0 ? (
        <div className="empty">No games found</div>
      ) : (
        <div className="flex flex-col gap-4">
          {games.map((game) => (
            <Card key={game.id}>
              <div className="game-header">
                <div className="game-players">
                  <strong>{game.white || 'Player'}</strong>
                  <span className="text-muted">(W)</span>
                  <span className="game-vs">vs</span>
                  <strong>{game.black || 'Player'}</strong>
                  <span className="text-muted">(B)</span>
                </div>
                {game.result && <Badge>{game.result}</Badge>}
              </div>

              <div className="game-meta">
                {game.created_at && (
                  <span>{new Date(game.created_at).toLocaleDateString()}</span>
                )}
                {game.source && <span>{game.source}</span>}
              </div>

              {expandedPgn[game.id] && (
                <pre className="game-pgn">{expandedPgn[game.id]}</pre>
              )}

              <div className="flex gap-2 mt-4">
                <Button size="sm" onClick={() => togglePgn(game.id)}>
                  {expandedPgn[game.id] ? 'Hide PGN' : 'Show PGN'}
                </Button>
                <Link to={`/analyze/${game.id}`}>
                  <Button size="sm" variant="primary">Analyze</Button>
                </Link>
                <Button size="sm" variant="danger" onClick={() => deleteGame(game.id)}>
                  Delete
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
