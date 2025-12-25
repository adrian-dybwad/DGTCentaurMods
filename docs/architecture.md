# Universal Chess - Architecture Diagrams

## 1. Application Startup Flow

```mermaid
flowchart TD
    subgraph Startup["Application Startup"]
        A[main.py entry] --> B[Parse Arguments]
        B --> C[Load Game Settings]
        C --> D[Initialize Display Manager]
        D --> E[Show Splash Screen]
        E --> F[Subscribe Board Events]
        F --> G[Register Signal Handlers]
        G --> H[Start Services]
        
        subgraph Services["Service Initialization"]
            H --> H1[SystemPollingService]
            H --> H2[ChessGameService]
        end
        
        H1 --> I[Initialize BLE Manager]
        H2 --> I
        I --> J[Start BLE Mainloop Thread]
        J --> K[Initialize RFCOMM Thread]
        K --> L{Check Incomplete Game?}
        
        L -->|Yes| M[Resume Game]
        L -->|No| N[Show Main Menu]
        
        M --> O[AppState = GAME]
        N --> P[AppState = MENU]
    end
```

## 2. Main Application State Machine

```mermaid
stateDiagram-v2
    [*] --> MENU: Startup (no game to resume)
    [*] --> GAME: Startup (resume incomplete game)
    
    MENU --> GAME: Select "Universal"
    MENU --> GAME: Piece moved on board
    MENU --> GAME: BLE/RFCOMM client connects
    MENU --> SETTINGS: Select "Settings"
    MENU --> SHUTDOWN: Select "Shutdown"
    MENU --> IDLE: Press BACK
    
    IDLE --> MENU: Press TICK
    
    SETTINGS --> MENU: Press BACK
    SETTINGS --> GAME: BLE client connects
    SETTINGS --> POSITIONS: Select "Positions"
    
    POSITIONS --> GAME: Load position
    POSITIONS --> SETTINGS: Press BACK
    
    GAME --> MENU: Game ends + BACK pressed
    GAME --> GAME: Moves, corrections, etc.
    
    SHUTDOWN --> [*]
```

## 3. State Objects and Observer Pattern

```mermaid
flowchart LR
    subgraph StateObjects["State Objects (state/)"]
        CGS[ChessGameState]
        CCS[ChessClockState]
        AS[AnalysisState]
        SS[SystemState]
        CRS[ChromecastState]
    end
    
    subgraph Observers["Observers (Widgets)"]
        CBW[ChessBoardWidget]
        CCW[ChessClockWidget]
        GAW[GameAnalysisWidget]
        SBW[StatusBarWidget]
    end
    
    subgraph Mutators["Services (mutate state)"]
        GM[GameManager]
        CCSvc[ChessClockService]
        AnSvc[AnalysisService]
        SPS[SystemPollingService]
    end
    
    %% State mutations
    GM -->|push_move, pop_move, reset| CGS
    CCSvc -->|tick, set_times, set_active| CCS
    AnSvc -->|set_score, set_mate_score| AS
    SPS -->|set_battery, set_wifi, set_bluetooth| SS
    
    %% AnalysisService observes ChessGameState
    CGS -->|on_position_change| AnSvc
    
    %% Observer notifications to widgets
    CGS -->|on_position_change| CBW
    CCS -->|on_tick, on_state_change| CCW
    AS -->|on_score_change, on_history_change| GAW
    SS -->|on_battery_change, on_wifi_change| SBW
```

## 4. Game Event Flow (Move Execution)

```mermaid
sequenceDiagram
    participant Board as Physical Board
    participant Univ as universal.py
    participant CM as ControllerManager
    participant LC as LocalController
    participant GM as GameManager
    participant GS as ChessGameState
    participant DM as DisplayManager
    participant CBW as ChessBoardWidget
    
    Board->>Univ: field_callback(LIFT, e2)
    Univ->>CM: on_field_event(LIFT, e2)
    CM->>LC: on_field_event(LIFT, e2)
    LC->>GM: receive_field(LIFT, e2)
    GM->>GM: _handle_piece_lift(e2)
    Note over GM: Store source square, calculate legal moves
    
    Board->>Univ: field_callback(PLACE, e4)
    Univ->>CM: on_field_event(PLACE, e4)
    CM->>LC: on_field_event(PLACE, e4)
    LC->>GM: receive_field(PLACE, e4)
    GM->>GM: _handle_piece_place(e4)
    GM->>GM: _execute_move(e4)
    GM->>GS: push_move(e2e4)
    
    GS->>GS: _board.push(move)
    GS->>GS: notify_position_change()
    
    GS-->>CBW: callback()
    CBW->>CBW: Update FEN, invalidate cache
    CBW->>CBW: request_update()
    
    GS-->>DM: callback()
    DM->>DM: Trigger analysis
    DM->>DM: Update clock active color
```

## 5. Bluetooth Connection Flow

```mermaid
sequenceDiagram
    participant App as Chess App (Phone)
    participant BLE as BleManager
    participant Univ as universal.py
    participant CM as ControllerManager
    participant RC as RemoteController
    participant GM as GameManager
    
    App->>BLE: Connect via BLE/RFCOMM
    BLE->>Univ: on_connected callback
    
    alt In MENU state
        Univ->>Univ: _start_game_mode()
        Univ->>CM: create controllers
        CM->>LC: LocalController()
        CM->>RC: RemoteController()
        Univ->>CM: activate_remote()
        CM->>RC: start()
        RC->>RC: Create emulators (Millennium/Pegasus/Chessnut)
    else In GAME state
        Univ->>Univ: Show confirmation dialog
        Univ->>CM: activate_remote()
    end
    
    App->>BLE: Send command
    BLE->>Univ: on_data_received(bytes)
    Univ->>CM: on_bluetooth_data(bytes)
    CM->>RC: on_bluetooth_data(bytes)
    RC->>RC: Route to active emulator
    
    RC-->>BLE: Response bytes
    BLE-->>App: Forward response
```

## 6. Display Widget Hierarchy

```mermaid
flowchart TD
    subgraph DisplayManager
        DM[DisplayManager]
    end
    
    subgraph WidgetFramework["Widget Framework (epaper/)"]
        FM[FrameworkManager]
        FB[FrameBuffer]
    end
    
    subgraph Widgets["Game Widgets"]
        SB[StatusBarWidget]
        CB[ChessBoardWidget]
        CC[ChessClockWidget]
        GA[GameAnalysisWidget]
        AW[AlertWidget]
    end
    
    subgraph MenuWidgets["Menu Widgets"]
        IM[IconMenuWidget]
        KB[KeyboardWidget]
        SP[SplashScreen]
    end
    
    DM --> FM
    FM --> FB
    FB --> |render to| EPD[E-Paper Display]
    
    FM --> SB
    FM --> CB
    FM --> CC
    FM --> GA
    FM --> AW
    FM --> IM
    FM --> KB
    FM --> SP
    
    subgraph StateSubscriptions["State Subscriptions"]
        CGS2[ChessGameState] -.->|on_position_change| CB
        CCS2[ChessClockState] -.->|on_tick| CC
        AS2[AnalysisState] -.->|on_score_change| GA
        SS2[SystemState] -.->|on_battery/wifi/bt| SB
    end
```

## 7. Module Dependencies

```mermaid
flowchart TD
    subgraph EntryPoint
        MAIN[universal.py]
    end
    
    subgraph Managers
        PM[ProtocolManager]
        GM[GameManager]
        DM[DisplayManager]
        CONN[ConnectionManager]
    end
    
    subgraph Controllers
        CM[ControllerManager]
        LC[LocalController]
        RC[RemoteController]
    end
    
    subgraph State["State Objects"]
        CGS[ChessGameState]
        CCS[ChessClockState]
        AS[AnalysisState]
        SS[SystemState]
    end
    
    subgraph Services
        CCSC[ChessClockService]
        SPS[SystemPollingService]
        CGSvc[ChessGameService]
    end
    
    subgraph Players
        HP[HumanPlayer]
        EP[EnginePlayer]
        LP[LichessPlayer]
        PMgr[PlayerManager]
    end
    
    subgraph Emulators
        MIL[Millennium]
        PEG[Pegasus]
        CN[Chessnut]
    end
    
    subgraph Hardware
        BOARD[board.py]
        EPAPER[epaper framework]
    end
    
    MAIN --> PM
    MAIN --> DM
    MAIN --> CM
    MAIN --> CONN
    
    PM --> GM
    CM --> LC
    CM --> RC
    
    LC --> GM
    LC --> PMgr
    RC --> MIL
    RC --> PEG
    RC --> CN
    
    GM --> CGS
    GM --> PMgr
    
    PMgr --> HP
    PMgr --> EP
    PMgr --> LP
    
    DM --> CCSC
    DM --> AS
    CCSC --> CCS
    SPS --> SS
    CGSvc --> CGS
    
    BOARD --> EPAPER
```

## 8. Correction Mode Flow

```mermaid
sequenceDiagram
    participant Board as Physical Board
    participant GM as GameManager
    participant GS as ChessGameState
    participant LED as Board LEDs
    
    Note over Board,LED: Player makes wrong move
    
    Board->>GM: receive_field(PLACE, wrong_square)
    GM->>GM: _handle_piece_place()
    GM->>GM: Move not in legal_destination_squares
    GM->>GM: _enter_correction_mode()
    GM->>GM: _provide_correction_guidance()
    
    GM->>LED: Flash LEDs showing required correction
    
    loop Until board matches expected state
        Board->>GM: receive_field(event)
        GM->>GM: _handle_field_event_in_correction_mode()
        GM->>GS: to_piece_presence_state()
        GM->>GM: Compare current vs expected
        
        alt States match
            GM->>GM: _exit_correction_mode()
            GM->>LED: ledsOff()
            Note over GM: Resume normal game flow
        else States differ
            GM->>GM: _provide_correction_guidance()
            GM->>LED: Flash correction LEDs
        end
    end
```

## 9. Clock Service Flow

```mermaid
sequenceDiagram
    participant DM as DisplayManager
    participant CCSvc as ChessClockService
    participant CCS as ChessClockState
    participant CCW as ChessClockWidget
    
    DM->>CCSvc: start_clock(white_seconds, black_seconds, timed)
    CCSvc->>CCS: set_times(white, black)
    CCSvc->>CCS: set_timed_mode(true)
    CCSvc->>CCS: set_running(true)
    CCS-->>CCW: on_state_change callback
    CCW->>CCW: request_update()
    
    CCSvc->>CCSvc: Start countdown thread
    
    loop Every second while running
        CCSvc->>CCS: tick()
        CCS->>CCS: Decrement active player time
        CCS-->>CCW: on_tick callback
        CCW->>CCW: request_update()
        
        alt Time reaches 0
            CCS->>CCS: notify_flag(color)
            CCS-->>DM: on_flag callback
            DM->>DM: Handle time forfeit
        end
    end
    
    Note over DM,CCW: On move made
    DM->>CCSvc: switch_turn()
    CCSvc->>CCS: set_active(other_color)
    CCS-->>CCW: on_state_change callback
```

## 10. Complete System Overview

```mermaid
flowchart TB
    subgraph Hardware["Hardware Layer"]
        CENTAUR[DGT Centaur Board]
        EPAPER[E-Paper Display]
        BT[Bluetooth Radio]
    end
    
    subgraph BoardModule["Board Module"]
        SYNC[sync_centaur.py]
        BOARD[board.py]
    end
    
    subgraph Communication["Communication Layer"]
        BLE[BleManager]
        RFCOMM[RfcommManager]
        CONN[ConnectionManager]
    end
    
    subgraph Controllers["Controller Layer"]
        CM[ControllerManager]
        LC[LocalController]
        RC[RemoteController]
    end
    
    subgraph GameLogic["Game Logic Layer"]
        PM[ProtocolManager]
        GM[GameManager]
        PMgr[PlayerManager]
    end
    
    subgraph StateLayer["State Layer (Observable)"]
        CGS[ChessGameState]
        CCS[ChessClockState]
        AS[AnalysisState]
        SS[SystemState]
    end
    
    subgraph ServiceLayer["Service Layer"]
        CCSC[ChessClockService]
        SPS[SystemPollingService]
        ASVC[AnalysisService]
    end
    
    subgraph DisplayLayer["Display Layer"]
        DM[DisplayManager]
        FM[FrameworkManager]
        WIDGETS[Widgets]
    end
    
    subgraph Emulators["Emulator Layer"]
        MIL[Millennium]
        PEG[Pegasus]
        CN[Chessnut]
    end
    
    %% Hardware connections
    CENTAUR <--> SYNC
    SYNC <--> BOARD
    EPAPER <--> FM
    BT <--> BLE
    BT <--> RFCOMM
    
    %% Communication flow
    BLE --> CONN
    RFCOMM --> CONN
    CONN --> CM
    
    %% Controller flow
    CM --> LC
    CM --> RC
    LC --> GM
    RC --> MIL
    RC --> PEG
    RC --> CN
    
    %% Game logic
    PM --> GM
    GM --> PMgr
    
    %% State mutations
    GM -->|mutate| CGS
    CCSC -->|mutate| CCS
    ASVC -->|mutate| AS
    SPS -->|mutate| SS
    
    CGS -->|observe| ASVC
    
    %% State observations
    CGS -.->|observe| WIDGETS
    CCS -.->|observe| WIDGETS
    AS -.->|observe| WIDGETS
    SS -.->|observe| WIDGETS
    
    %% Display
    DM --> FM
    FM --> WIDGETS
    
    %% Board events
    BOARD -->|events| LC
    BOARD -->|events| GM
```

## Key Architectural Principles

1. **State Objects are the Single Source of Truth**
   - All game state lives in `ChessGameState`
   - All clock state lives in `ChessClockState`
   - Widgets observe state, never mutate it

2. **Mutations Only Through State Methods**
   - `push_move()`, `pop_move()`, `reset()`, `set_position()`
   - Methods automatically notify observers
   - No direct field access from outside

3. **Observer Pattern for UI Updates**
   - Widgets subscribe to state changes
   - State notifies all observers on mutation
   - Decouples game logic from display logic

4. **Controller Abstraction**
   - `LocalController` handles local play (human + engine)
   - `RemoteController` handles Bluetooth app connections
   - `ControllerManager` switches between them

5. **Service Layer for Background Tasks**
   - `ChessClockService` manages countdown thread
   - `SystemPollingService` polls battery/wifi/bluetooth
   - Services mutate state, state notifies widgets
