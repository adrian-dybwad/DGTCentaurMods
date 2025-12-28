/**
 * Game state received from SSE /events endpoint.
 * Property names match the snake_case JSON from Python backend.
 */
export interface GameState {
  fen: string;
  fen_full: string;
  pgn: string;
  move_number: number;
  turn: 'w' | 'b';
  white: string;
  black: string;
  result: string | null;
  game_id: number | null;
  game_over: boolean;
  /** Last move executed in UCI format (e.g., 'e2e4') */
  last_move: string | null;
  /** Move pending on the physical board (engine/Lichess move waiting to be executed) */
  pending_move: string | null;
}

/**
 * Stockfish analysis result for a position.
 */
export interface AnalysisResult {
  fen: string;
  score: number | null;
  mate: number | null;
  bestMove: string | null;
  depth: number;
}

/**
 * Game record from database.
 */
export interface GameRecord {
  id: number;
  white: string | null;
  black: string | null;
  result: string | null;
  created_at: string;
  source: string | null;
}

/**
 * Engine definition from backend.
 */
export interface EngineDefinition {
  name: string;
  display_name: string;
  description: string;
  summary: string;
  installed: boolean;
  has_prebuilt: boolean;
  install_time: string | null;
}

/**
 * Connection status for SSE.
 */
export type ConnectionStatus = 'connected' | 'reconnecting' | 'disconnected';
