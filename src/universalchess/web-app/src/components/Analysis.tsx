import { useEffect, useState, useRef } from 'react';
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
import { getStockfishService } from '../services/stockfish';
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
  const [sfReady, setSfReady] = useState(false);
  
  const chartRef = useRef<ChartJS<'line'> | null>(null);
  const lastPgnRef = useRef('');
  const queueRef = useRef<number[]>([]);
  const processingRef = useRef(false);

  // Total moves in the game
  const totalMoves = moves.length > 0 ? moves.length - 1 : 0;  // moves[0] is start position

  // Initialize Stockfish once
  useEffect(() => {
    const sf = getStockfishService();
    sf.init()
      .then(() => {
        console.log('[Analysis] Stockfish ready');
        setSfReady(true);
      })
      .catch((e) => {
        console.error('[Analysis] Failed to initialize Stockfish:', e);
      });

    return () => {
      sf.stop();
    };
  }, []);

  // Parse PGN and build move history
  useEffect(() => {
    if (!pgn || pgn === lastPgnRef.current) return;
    lastPgnRef.current = pgn;

    console.log('[Analysis] Parsing PGN, length:', pgn.length);

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
      console.log('[Analysis] Parsed', newMoves.length - 1, 'moves');
    } catch (e) {
      console.error('[Analysis] Failed to parse PGN:', e);
    }

    const prevLength = moves.length;
    setMoves(newMoves);

    // Build analysis queue
    queueRef.current = [];
    for (let i = 1; i < newMoves.length; i++) {
      queueRef.current.push(i);
    }
    console.log('[Analysis] Queue:', queueRef.current.length, 'positions');

    // Handle position based on mode
    if (mode === 'live') {
      if (movePos > 0 && movePos < prevLength - 1 && newMoves.length > prevLength) {
        setNewMovesToast(newMoves.length - 1 - movePos);
      } else {
        setMovePos(newMoves.length - 1);
      }
    } else if (mode === 'static' && movePos === 0) {
      setMovePos(newMoves.length - 1);
    }
  }, [pgn, mode]);

  // Store moves in a ref so processNext always has current data
  const movesRef = useRef<MoveData[]>([]);
  useEffect(() => {
    movesRef.current = moves;
  }, [moves]);

  // Process queue when Stockfish is ready and we have moves
  useEffect(() => {
    if (!sfReady || queueRef.current.length === 0 || processingRef.current) return;
    if (movesRef.current.length === 0) return;  // Wait for moves to be populated

    const processNext = async () => {
      if (queueRef.current.length === 0) {
        processingRef.current = false;
        setAnalyzing(false);
        console.log('[Analysis] Queue complete');
        return;
      }

      processingRef.current = true;
      setAnalyzing(true);

      const index = queueRef.current.shift()!;
      
      // Get move data from ref (always current)
      const move = movesRef.current[index];
      if (!move) {
        console.log(`[Analysis] Move ${index} not found, skipping`);
        setTimeout(processNext, 0);
        return;
      }

      if (move.eval !== null) {
        // Already analyzed, skip
        setTimeout(processNext, 0);
        return;
      }

      // Capture the FEN before async operation
      const fenToAnalyze = move.fen;
      const isBlackToMove = fenToAnalyze.includes(' b ');

      console.log(`[Analysis] Analyzing move ${index}: ${move.san}`);

      // Analyze this position
      const sf = getStockfishService();
      sf.analyze(fenToAnalyze, 10)
        .then((result) => {
          // Stockfish returns score from side-to-move's perspective.
          // We want all scores from White's perspective for consistent chart.
          let cp = result.score ?? 0;
          let mate = result.mate;
          
          if (isBlackToMove) {
            cp = -cp;
            if (mate !== null) {
              mate = -mate;
            }
          }
          
          // For chart: use large values for mate, otherwise centipawns
          const evalValue = mate !== null ? (mate > 0 ? 10000 : -10000) : cp;
          
          console.log(`[Analysis] Move ${index} result: raw=${result.score}, black=${isBlackToMove}, cp=${cp}, eval=${evalValue}`);
          
          setMoves((prev) => {
            const updated = [...prev];
            if (updated[index]) {
              updated[index] = {
                ...updated[index],
                eval: evalValue,
                mate: mate,
              };
            }
            return updated;
          });

          // Process next in queue
          setTimeout(processNext, 0);
        })
        .catch((e) => {
          console.error('[Analysis] Analysis failed for move', index, e);
          setTimeout(processNext, 0);
        });
    };

    console.log('[Analysis] Starting queue processing, moves available:', movesRef.current.length);
    processNext();
  }, [sfReady, moves.length]);

  // Analyze current position at higher depth when movePos changes
  // BUT only if the queue is done processing (to avoid overwriting pendingResolve)
  useEffect(() => {
    if (!sfReady || movePos <= 0) return;
    if (processingRef.current) return;  // Queue is still processing
    
    const move = moves[movePos];
    if (!move) return;

    const sf = getStockfishService();
    sf.analyze(move.fen, 16)
      .then((result) => {
        // Normalize to White's perspective
        const isBlackToMove = move.fen.includes(' b ');
        
        let cp = result.score ?? 0;
        let mate = result.mate;
        
        if (isBlackToMove) {
          cp = -cp;
          if (mate !== null) {
            mate = -mate;
          }
        }
        
        setCurrentEval({
          cp: mate !== null ? (mate > 0 ? 10000 : -10000) : cp,
          mate: mate,
        });
        setBestMove(result.bestMove);
      })
      .catch(() => {
        // Keep previous eval
      });
  }, [sfReady, movePos, moves, analyzing]);  // Re-run when analyzing changes (queue finishes)

  // Notify parent of position change
  useEffect(() => {
    if (onPositionChange && movePos >= 0 && moves[movePos]) {
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
    return 50 - (clampedCp / 20);
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

  // Chart data - evaluations for each move after the start position
  // The chart shows one point per move, with the evaluation from white's perspective
  const analyzedMoves = moves.slice(1);  // Skip start position
  const chartLabels = analyzedMoves.map((_, i) => String(i + 1));
  const chartEvals = analyzedMoves.map((m) => {
    if (m.eval === null) return 0;  // Show 0 for unanalyzed instead of null (avoids gaps)
    return Math.max(-500, Math.min(500, m.eval));
  });
  
  // Debug: log chart data when moves change
  useEffect(() => {
    if (analyzedMoves.length > 0) {
      const evalSummary = analyzedMoves.map((m, i) => `${i+1}:${m.eval}`).join(', ');
      console.log('[Analysis] Chart evals:', evalSummary);
    }
  }, [moves]);

  const chartData = {
    labels: chartLabels,
    datasets: [
      {
        label: 'Eval',
        data: chartEvals,
        fill: true,
        borderColor: 'rgb(150, 150, 150)',
        borderWidth: 2,
        tension: 0.4,
        backgroundColor: 'rgba(150, 150, 150, 0.3)',
        pointRadius: analyzedMoves.map((_, i) => i + 1 === movePos ? 6 : 3),
        pointBackgroundColor: analyzedMoves.map((_, i) =>
          i + 1 === movePos ? '#aa44aa' : 'rgba(255, 255, 255, 1)'
        ),
        pointBorderColor: analyzedMoves.map((_, i) =>
          i + 1 === movePos ? '#aa44aa' : 'rgb(150, 150, 150)'
        ),
      },
    ],
  };

  const chartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    animation: {
      duration: 0,  // Disable animations for faster updates
    },
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
        type: 'linear' as const,
        min: -500,
        max: 500,
        ticks: {
          stepSize: 250,
          callback: function(tickValue: string | number) {
            const value = typeof tickValue === 'number' ? tickValue : parseFloat(tickValue);
            return (value / 100).toFixed(0);
          },
        },
        grid: { color: 'rgba(200,200,200,0.3)' },
      },
      x: {
        type: 'category' as const,
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
            analyzing ? 'Analyzing...' : (sfReady ? 'Waiting...' : 'Loading Stockfish...')
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
