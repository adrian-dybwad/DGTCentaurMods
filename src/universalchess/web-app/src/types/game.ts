/**
 * Game state received from SSE /events endpoint.
 */
export interface GameState {
  fen: string;
  fen_full: string;
  pgn: string;
  move_number: number;
  white: string;
  black: string;
  result: string | null;
  game_id: number | null;
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

