import { useEffect, useState, useCallback, useRef } from 'react';
import { Line } from 'react-chartjs-2';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler,
} from 'chart.js';
import { Chess } from 'chess.js';
import { getStockfishService, StockfishService } from '../services/stockfish';
import './Analysis.css';

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend, Filler);

interface AnalysisProps {
  pgn: string;
  mode: 'live' | 'static';
  onPositionChange?: (fen: string, moveIndex: number) => void;
}

interface MoveData {
  fen: string;
  san: string;
  eval: number | null;  // centipawns, null if not analyzed
  mate: number | null;  // mate in N, null if not mate
}

/**
 * Analysis component matching the original Flask template design.
 * Features: eval score, best move, horizontal eval bar, chart, navigation.
 */
export function Analysis({ pgn, mode, onPositionChange }: AnalysisProps) {
  const [moves, setMoves] = useState<MoveData[]>([]);
  const [movePos, setMovePos] = useState(0);  // 0 = start, 1 = after first move, etc.
  const [currentEval, setCurrentEval] = useState<{ cp: number; mate: number | null }>({ cp: 0, mate: null });
  const [bestMove, setBestMove] = useState<string | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [newMovesToast, setNewMovesToast] = useState(0);
  
  const stockfishRef = useRef<StockfishService | null>(null);
  const analysisQueueRef = useRef<number[]>([]);
  const isProcessingRef = useRef(false);
  const chartRef = useRef<ChartJS<'line'> | null>(null);
  const lastPgnRef = useRef('');

  // Total moves in the game
  const totalMoves = moves.length - 1;  // moves[0] is start position

  // Parse PGN and build move history
  useEffect(() => {
    if (!pgn || pgn === lastPgnRef.current) return;
    lastPgnRef.current = pgn;

    const chess = new Chess();
    const newMoves: MoveData[] = [
      { fen: chess.fen(), san: 'Start', eval: null, mate: null },
    ];

    try {
      chess.loadPgn(pgn);
      const history = chess.history({ verbose: true });
      
      chess.reset();
      for (const move of history) {
        chess.move(move.san);
        newMoves.push({
          fen: chess.fen(),
          san: move.san,
          eval: null,
          mate: null,
        });
      }
    } catch (e) {
      console.error('[Analysis] Failed to parse PGN:', e);
    }

    const prevLength = moves.length;
    setMoves(newMoves);

    // Queue all positions for analysis
    analysisQueueRef.current = [];
    for (let i = 1; i < newMoves.length; i++) {
      analysisQueueRef.current.push(i);
    }

    // Handle position based on mode
    if (mode === 'live') {
      if (movePos > 0 && movePos < prevLength - 1 && newMoves.length > prevLength) {
        // User was reviewing history, show toast
        setNewMovesToast(newMoves.length - 1 - movePos);
      } else {
        // Jump to latest
        setMovePos(newMoves.length - 1);
      }
    } else if (mode === 'static' && movePos === 0) {
      // Static mode: jump to end on initial load
      setMovePos(newMoves.length - 1);
    }

    // Start queue processing
    processQueue();
  }, [pgn, mode]);

  // Initialize Stockfish
  useEffect(() => {
    const sf = getStockfishService();
    stockfishRef.current = sf;
    sf.init().catch((e) => {
      console.error('[Analysis] Failed to initialize Stockfish:', e);
    });

    return () => {
      sf.stop();
    };
  }, []);

  // Process analysis queue
  const processQueue = useCallback(async () => {
    if (isProcessingRef.current || !stockfishRef.current) return;
    if (analysisQueueRef.current.length === 0) {
      setAnalyzing(false);
      return;
    }

    isProcessingRef.current = true;
    setAnalyzing(true);

    const index = analysisQueueRef.current.shift()!;
    
    setMoves((prev) => {
      const move = prev[index];
      if (!move || move.eval !== null) {
        // Already analyzed or doesn't exist
        isProcessingRef.current = false;
        setTimeout(processQueue, 0);
        return prev;
      }

      stockfishRef.current!.analyze(move.fen, 10)
        .then((result) => {
          setMoves((current) => {
            const updated = [...current];
            if (updated[index]) {
              // Negate if black's turn (eval from white's perspective)
              let cp = result.score ?? 0;
              if (move.fen.includes(' b ')) {
                cp = -cp;
              }
              updated[index] = { 
                ...updated[index], 
                eval: result.mate !== null ? (result.mate > 0 ? 10000 : -10000) : cp,
                mate: result.mate,
              };
            }
            return updated;
          });
          
          isProcessingRef.current = false;
          processQueue();
        })
        .catch(() => {
          isProcessingRef.current = false;
          processQueue();
        });

      return prev;
    });
  }, []);

  // Analyze current position at higher depth
  useEffect(() => {
    if (movePos <= 0 || !stockfishRef.current) return;
    const move = moves[movePos];
    if (!move) return;

    stockfishRef.current.analyze(move.fen, 16)
      .then((result) => {
        let cp = result.score ?? 0;
        if (move.fen.includes(' b ')) {
          cp = -cp;
        }
        setCurrentEval({ 
          cp: result.mate !== null ? (result.mate > 0 ? 10000 : -10000) : cp, 
          mate: result.mate 
        });
        setBestMove(result.bestMove);
      })
      .catch(() => {
        // Keep previous eval
      });
  }, [movePos, moves]);

  // Notify parent of position change
  useEffect(() => {
    if (onPositionChange && movePos >= 0 && moves[movePos]) {
      // Pass placement-only FEN for chessboard.js
      onPositionChange(moves[movePos].fen.split(' ')[0], movePos);
    }
  }, [movePos, moves, onPositionChange]);

  // Navigation
  const goFirst = () => setMovePos(0);
  const goPrev = () => setMovePos((p) => Math.max(0, p - 1));
  const goNext = () => setMovePos((p) => Math.min(totalMoves, p + 1));
  const goLast = () => {
    setMovePos(totalMoves);
    setNewMovesToast(0);
  };
  const jumpToLatest = () => {
    setMovePos(totalMoves);
    setNewMovesToast(0);
  };

  // Format eval display
  const formatEval = (): { text: string; color: string } => {
    if (currentEval.mate !== null) {
      const m = currentEval.mate;
      return {
        text: m > 0 ? `M${m}` : `M${-m}`,
        color: m > 0 ? 'var(--color-success, green)' : 'var(--color-danger, red)',
      };
    }
    const pawns = (currentEval.cp / 100).toFixed(1);
    return {
      text: currentEval.cp >= 0 ? `+${pawns}` : pawns,
      color: '',
    };
  };

  // Eval bar value (0-100, 50 = equal)
  const evalBarValue = (() => {
    let effectiveCp = currentEval.cp;
    if (currentEval.mate !== null) {
      effectiveCp = currentEval.mate > 0 ? 10000 : -10000;
    }
    const clampedCp = Math.max(-1000, Math.min(1000, effectiveCp));
    return 50 - (clampedCp / 20);  // 50 is center
  })();

  // Eval bar class
  const evalBarClass = (() => {
    if (currentEval.cp > 100 || (currentEval.mate !== null && currentEval.mate > 0)) {
      return 'progress is-success';
    }
    if (currentEval.cp < -100 || (currentEval.mate !== null && currentEval.mate < 0)) {
      return 'progress is-danger';
    }
    return 'progress is-warning';
  })();

  // Chart data - only include analyzed positions
  const chartData = {
    labels: moves.slice(1).map((_, i) => i + 1),
    datasets: [
      {
        label: 'Eval',
        data: moves.slice(1).map((m) => {
          if (m.eval === null) return null;
          return Math.max(-500, Math.min(500, m.eval));
        }),
        fill: true,
        borderColor: 'rgb(150, 150, 150)',
        borderWidth: 1,
        tension: 0.4,
        backgroundColor: 'rgba(150, 150, 150, 0.3)',
        pointRadius: moves.slice(1).map((_, i) => i + 1 === movePos ? 6 : 3),
        pointBackgroundColor: moves.slice(1).map((_, i) => 
          i + 1 === movePos ? '#aa44aa' : 'rgba(255, 255, 255, 1)'
        ),
        spanGaps: true,
      },
    ],
  };

  const chartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      title: { display: false },
      tooltip: {
        callbacks: {
          title: (items: any[]) => `Move ${items[0]?.dataIndex + 1 || ''}`,
          label: (item: any) => {
            const cp = item.raw;
            if (cp === null) return 'Not analyzed';
            return `${(cp / 100).toFixed(2)} pawns`;
          },
        },
      },
    },
    scales: {
      y: {
        min: -500,
        max: 500,
        ticks: {
          stepSize: 250,
          callback: (value: number) => (value / 100).toFixed(0),
        },
        grid: { color: 'rgba(200,200,200,0.3)' },
      },
      x: {
        display: false,
        grid: { display: false },
      },
    },
    onClick: (_: any, elements: any[]) => {
      if (elements.length > 0) {
        setMovePos(elements[0].index + 1);
      }
    },
  };

  const evalDisplay = formatEval();

  return (
    <div className="analysis-widget">
      {/* Eval display and best move */}
      <div className="analysis-eval-display">
        <span 
          className="eval-score" 
          style={{ color: evalDisplay.color || undefined }}
        >
          {movePos > 0 ? evalDisplay.text : '0.0'}
        </span>
        <span className="eval-best-move">
          {bestMove ? (
            <>Best: <strong>{bestMove}</strong></>
          ) : (
            analyzing ? 'Analyzing...' : 'Waiting...'
          )}
        </span>
      </div>

      {/* Eval bar - horizontal progress bar */}
      <progress 
        className={evalBarClass}
        value={evalBarValue} 
        max={100}
      />

      {/* Chart */}
      <div className="analysis-chart">
        <Line 
          ref={chartRef as any}
          data={chartData} 
          options={chartOptions as any} 
        />
      </div>

      {/* Navigation buttons */}
      <div className="analysis-nav">
        <button className="button is-small" onClick={goFirst} title="First move">&lt;&lt;</button>
        <button className="button is-small" onClick={goPrev} title="Previous move">&lt;</button>
        <span className="move-indicator">{movePos}/{totalMoves}</span>
        <button className="button is-small" onClick={goNext} title="Next move">&gt;</button>
        <button className="button is-small" onClick={goLast} title="Last move">&gt;&gt;</button>
      </div>

      {/* New moves toast (live mode only) */}
      {mode === 'live' && newMovesToast > 0 && (
        <div className="notification is-info is-light new-moves-toast" onClick={jumpToLatest}>
          {newMovesToast} new move(s) - Click to view
        </div>
      )}
    </div>
  );
}
