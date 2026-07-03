# FANUC 車床 G-code 路徑模擬器 — 架構規劃

## 1. 目標

輸入 FANUC 車床（Lathe，ZX 兩軸）控制系統的 NC 程式（含用戶宏程序），
輸出刀具路徑（toolpath），並以 matplotlib（離線）與網頁（互動）兩種方式視覺化。

範圍依據兩份參考手冊：

- `fanuc-macro.pdf`（B-63944CM/02 第16章 用戶宏程序）→ 變量、運算指令、
  宏語句/NC語句、GOTO/IF/WHILE、G65 宏調用
- `g_code.pdf`（B-64484CM-1/05 第3、4章）→ G32 螺紋切削、G90/G92/G94
  單一型固定循環、G70~G76 複合型固定循環

第一版**從一開始就納入用戶宏程序**（G65、變量、IF/WHILE），因為許多實務
G-code（尤其是固定循環的變體與參數化程式）大量依賴宏功能。

技術棧：Python。matplotlib 做離線靜態/動畫視覺化；另外把 toolpath 匯出成
JSON，搭配一個獨立網頁（HTML+Canvas/SVG）做互動式檢視（可拖曳時間軸、
分辨快速/切削路徑）。

## 2. 專案結構

```
Gcode_parser/
  gcode_sim/
    __init__.py
    lexer.py            # 原始碼 → token（位址字、括號運算式、關鍵字）
    ast_nodes.py         # AST 節點定義（NCBlock, Assignment, Goto, If, While, ...）
    parser.py            # token → 每個程式段的 AST
    expression.py         # <表達式> 遞迴下降解析 + 求值（運算子優先序、函數）
    variables.py          # 變量儲存：局部/公共/系統變量、空值語意
    interpreter.py         # 主執行迴圈：模態狀態、控制流、宏調用/子程式堆疊、G50
    tool_table.py           # ToolEntry / ToolTable（T 代碼查詢）
    canned_cycles/
      __init__.py
      contour.py           # 輪廓子解譯器（G70/G71/G72/G73 共用，見第7節）
      turning.py          # G90（外/內徑車削）、G94（端面車削）
      threading.py        # G32、G92（螺紋切削循環）、G76（複合型螺紋）
      roughing.py         # G71、G72（外徑/端面粗車，類型I/II）
      pattern_repeat.py    # G73（閉環/仿形粗車）
      finishing.py         # G70（精車）
      grooving.py          # G74、G75（端面/外徑切斷、切槽、深孔鑽）
    motion.py             # 直線/圓弧插補的幾何運算（點列生成）
    tool_comp.py            # G41/G42 刀尖半徑補償（Phase 4.5）
    toolpath.py            # Move / Toolpath / ToolTable 資料結構
    simulator.py           # 串接 interpreter → canned_cycles → tool_comp → toolpath
    export_json.py         # toolpath → JSON（供網頁 viewer 使用）
    viz_matplotlib.py       # 離線繪圖/動畫
    cli.py                 # 指令列入口：gcode-sim run foo.nc --plot
  web_viewer/
    index.html            # 獨立網頁，讀取 toolpath JSON 顯示互動路徑
    viewer.js
    viewer.css
  tests/
    fixtures/             # 手冊範例程式（見第6節）
    test_lexer.py
    test_expression.py
    test_variables.py
    test_control_flow.py
    test_macro_call.py
    test_interpolation.py
    test_canned_cycles/
      test_g71.py
      test_g72.py
      test_g73.py
      test_g76.py
      ...
  examples/
    01_basic_line_arc.nc
    02_macro_sum.nc        # 手冊 O9500 / O0001 範例
    03_g90_taper.nc
    04_g71_rough_type1.nc
    05_g73_pattern.nc
    06_g76_thread.nc
  docs/
    PLAN.md               # 本文件
    grammar.md            # G-code / 宏語法的正式文法（BNF）
    variables.md           # 變量對應表、系統變量支援清單
```

## 3. 解析流程（Lexer → Parser → AST）

### 3.1 Lexer
- 依 `;` 或換行切分程式段（block）。
- 去除註解（`( ... )`）；`%`、`O` 程式號單獨處理。
- 產生 token：位址字母（如 `X`、`G`、`#`）、數字、運算子
  (`+ - * / = [ ] ,`)、比較算符（`EQ NE GT GE LT LE`）、
  邏輯算符（`AND OR XOR`）、關鍵字（`GOTO IF THEN WHILE DO END`）、
  函數名（`SIN COS TAN ASIN ACOS ATAN SQRT ABS ROUND FIX FUP LN EXP POW
  BIN BCD ADP` 及其兩字母縮寫）、系統變量名稱（`[#_XXXX[n]]` 形式）。

### 3.2 程式段分類（依手冊 16.5 節）
- **宏語句**：含 `=`（運算指令）、含 `GOTO/IF/WHILE`、含宏調用
  （`G65/G66/G66.1/G67` 或自訂義的 G/M 代碼調用）。
- **NC語句**：其餘（一般移動指令、固定循環指令等）。

### 3.3 Parser → AST
- `Assignment(target: VarRef, expr: Expr)`
- `Goto(target: int | Expr)`
- `IfGoto(cond: Expr, target: int | Expr)` / `IfThen(cond: Expr, stmt: Stmt)`
- `WhileDo(cond: Expr, id: int, body: list[Block])` … `End(id)`（巢狀 ≤3層，
  依手冊 16.6.4 限制）
- `MacroCall(prog: int|Expr, repeat: int|Expr, args: dict[str, Expr])`
  （G65 P_ L_ 自變量指定，依手冊 16.7.1 第I/II類字母對應表）
- `NCStatement(seq_no, words: list[(address, Expr|float)])`

VarRef 支援 `#i`、`#[expr]`、系統變量名稱 `[#_NAME[n]]`。

## 4. 表達式求值（Expression）

依手冊 16.3 節：
- 優先順序：①函數 → ②`* / AND` → ③`+ - OR XOR`
- 括號 `[ ]` 可巢狀最多5層（超過拋出可讀的錯誤，而非模擬真實 PS0118 報警碼，
  但保留報警碼字串於錯誤訊息方便對照手冊）
- 函數：三角函數（角度制）、`ATAN[j]/[k]` 兩自變量與 `ATAN[j]` 一自變量、
  `ROUND/FIX/FUP/ABS/SQRT/LN/EXP/POW/BIN/BCD/ADP`
- 用 Python `decimal.Decimal` 或 `float`（雙精度）實作；先以 float 為主，
  精度誤差章節（16.3 限制）先記錄於文件、非模擬重點，除非後續需要重現
  誤差案例做教學用途。

## 5. 變量系統（Variables）

依手冊 16.1 節設計：

| 類別 | 範圍 | 生命週期 | 讀寫 |
|---|---|---|---|
| 局部變量 | `#1~#33` | 每次宏調用產生新的一層（stack frame） | 讀/寫 |
| 公共變量（易失） | `#100~#199` | 全域，關機（模擬開始）清除 | 讀/寫 |
| 公共變量（保持） | `#500~#999` | 全域，跨程式保留 | 讀/寫（可設唯讀範圍） |
| 系統變量 | `#1000+` | 依變量號固定用途 | 依變量而定 |
| 空值 | `#0`、`#3100` | 永遠是空值 | 唯讀 |

- `EmptyValue` sentinel：依 16.1「未定義變量」表格實作 EQ/NE 與
  GE/GT/LE/LT 對空值的不同判定邏輯。
- `VariableStack`：`push_frame(args: dict)` / `pop_frame()`，供 G65 巢狀
  調用使用（宏調用≤5層、子程式調用≤10層、合計≤15層，依16.7節限制，
  超過時拋錯）。
- 系統變量初期只實作模擬用得到的最小集合：目前刀具位置回讀
  （對應 `#5001~#5006` 絕對座標、`#5021~` 機床座標概念，用模擬器內部
  當前座標填入），其餘系統變量先回傳 `NotSupportedError`
  並清楚列出於 `docs/variables.md`。

## 6. 執行引擎（Interpreter）

- **模態狀態 ModalState**：注意車床 G 代碼群組與銑床不同——
  `G90/G92/G94` 在此手冊中屬於「01組固定循環」而非銑床的絕對/增量模式；
  絕對/增量由位址決定（`X/Z` = 絕對，`U/W` = 增量），因此 ModalState 不需要
  絕對/增量旗標，改為在每個 NC 語句解析時依位址字母判斷。
- **G50 座標設定 / 主軸最高轉速限制**：`G50` 車床專用，同一 G 代碼依
  指定的位址分成兩種完全不同語意，需在 parser 層依位址判斷分派：
  - `G50 X_ Z_（IP_）`：不產生移動，而是把「目前刀具實際位置」登記為
    指定的座標值，之後的絕對座標（X/Z）都以此為基準換算。實作上等同
    於重新設定 interpreter 內部「工件座標系原點偏移量」，而非移動刀具。
    需在 Phase 0 就支援，否則手冊範例程式的起始點會全部算錯。
  - `G50 S_`：設定主軸最高轉速限制（RPM 上限），只在 `G96`（恆線速度
    控制）模式下才有實際意義——線速度控制時直徑越小、轉速理論上越高，
    此限制防止轉速超過機械極限。路徑幾何完全不受影響，歸類為第13節
    第7點「記錄但不影響路徑幾何」的中繼資料（`Toolpath.max_spindle_rpm`
    之類欄位即可），不需要參與運動計算。
  - 同一程式段可能同時出現 `X/Z` 與 `S`（同時做座標設定與轉速限制），
    parser 需要能分別處理、不互斥。
- **主迴圈**：逐 block 執行 → 若為宏語句，交給對應處理器（賦值/控制流/
  宏調用）；若為 NC 語句，更新模態群組、取出移動相關位址，交給
  `motion.py`（G00/G01/G02/G03/G32）或 `canned_cycles/*`（G90/G92/G94/
  G70~G76）展開為原始移動（rapid/linear/arc/thread），append 進
  `Toolpath`。
- **控制流**：
  - `GOTOn`：以 `{seq_no: block_index}` 表建立跳轉（模擬器不需重現真機的
    「順序號存儲型 GOTO」效能優化，直接查表即可）。
  - `IF...GOTO` / `IF...THEN`
  - `WHILE...DO m / END m`：以堆疊實作，強制檢查 16.6.4 節的巢狀規則
    （識別號僅 1~3、範圍不可交叉、最多巢狀3層），違反時報錯。
- **宏調用（G65）**：依 P（程式號）、L（重複次數）、自變量（第I類：
  A B C D E F H I J K M Q R S T U V W X Y Z 各自對應 #1~#26 的表；
  第II類：A/B/C + 10組I/J/K）建立新的局部變量 frame，執行對應程式號的
  區塊，遇 `M99` 返回。
- **子程式調用（M98/M代碼/T代碼/S代碼調用）**：與 G65 分開的一級功能，
  不傳自變量、不建立新的局部變量 frame（沿用呼叫端的局部變量），僅
  push/pop 返回位址。與宏調用共用同一個 call stack 物件，但分開計數
  （宏調用≤5層、子程式調用≤10層、合計≤15層）。

## 7. 固定循環展開（canned_cycles/）

這是本專案幾何複雜度最高的部分，拆成獨立模組：

| 循環 | 模組 | 重點 |
|---|---|---|
| G32 | threading.py | 等導程螺紋（直線/錐度/旋渦），多線螺紋 Q 角度位移 |
| G90 | turning.py | 4動作循環：直線/錐度車削 |
| G92 | threading.py | 4動作螺紋切削循環（含倒角） |
| G94 | turning.py | 4動作端面/端面錐度車削 |
| G71 | roughing.py | 外徑粗車，類型I（單調輪廓）/類型II（含槽孔），
                       需要一個「輪廓子解譯器」執行 ns~nf 區間取得精車輪廓，
                       再依 Δd 分層、Δu/Δw 偏移生成粗車路徑 |
| G72 | roughing.py | 端面粗車，邏輯同 G71 但主軸方向互換 |
| G73 | pattern_repeat.py | 閉環/仿形粗車，依分割次數 d 逐步逼近輪廓 |
| G70 | finishing.py | 直接執行 ns~nf 精車輪廓（帶各段自己的 F/S/T） |
| G74 | grooving.py | 端面切斷/深孔鑽（Δk 進刀、Δd 退刀的間歇循環） |
| G75 | grooving.py | 外徑/內徑切斷、切槽（邏輯同G74，X/Z對調） |
| G76 | threading.py | 複合型螺紋切削循環（m,r,a 編碼於P；三角形遞減
                       進刀 Δd√n；最終精加工重複次數） |

**共用元件**：「輪廓子解譯器」（`contour.py`，供 G70/G71/G72/G73 共用）——
給定 ns/nf 範圍，用同一個 interpreter 執行該區間（G00/G01/G02/G03 組成的
折線+圓弧），輸出一條有序的輪廓折線，供各粗車循環做偏移/分層。

先實作順序建議：G90 → G94 → G71（類型I）→ G70 → G72 → G73 → G32 →
G92 → G76 → G71類型II（槽孔）→ G74/G75。理由：G90/G94/G70/G71類型I
幾何最單純且最常用，G76/類型II槽孔涉及最多分支條件，留到後面。

## 8. 刀具路徑資料結構（toolpath.py）

```python
@dataclass
class Move:
    kind: Literal["rapid", "linear", "arc", "thread"]
    start: tuple[float, float]   # (Z, X) 依手冊慣例 X 為直徑值；刀尖中心座標
    end: tuple[float, float]
    programmed_end: tuple[float, float] | None = None  # 編程座標（未套用刀尖
        # 半徑補償前的目標點）。Phase 0~4 恆等於 end；Phase 4.5 導入 G41/G42
        # 後，end 改為刀尖中心實際座標，programmed_end 保留原始編程座標，
        # 兩者都要能查得到（除錯、對照原始程式用）。
    feed: float | None = None
    spindle: float | None = None
    feed_mode: Literal["per_min", "per_rev"] | None = None   # G98/G99，僅記錄
    spindle_mode: Literal["rpm", "css"] | None = None         # G97/G96，僅記錄
    arc_center: tuple[float, float] | None = None
    arc_ccw: bool | None = None
    source_line: int | None = None   # 對應原始程式行號，方便除錯
    cycle: str | None = None         # 產生此移動的固定循環名稱（若有）
    tool: str | None = None          # 對應 ToolTable 的刀號（如 "0101"）

@dataclass
class Toolpath:
    moves: list[Move]
    diameter_programming: bool = True  # X 為直徑值（手冊預設）

@dataclass
class ToolEntry:
    tool_no: str          # 如 "01"（T0101 的前兩碼）
    offset_no: str        # 如 "01"（T0101 的後兩碼）
    nose_radius: float = 0.0     # 刀尖半徑，Phase 0~4 預設0（無影響）
    orientation: int = 0         # 假想刀尖方向 0~9，Phase 4.5 才用到

class ToolTable(dict[str, ToolEntry]):
    """key 為完整刀號字串（如 "0101"）。Phase 0 只需能存取/查詢，
    不強制每個 T 代碼都要先註冊，缺項時視為 nose_radius=0。"""
```

- X 軸依手冊註記預設為**直徑編程**（圖中以 X/2 換算半徑），提供設定切換
  半徑編程。
- 刀尖半徑補償（G41/G42）**列為 Phase 6 stretch goal**，先以理想尖點刀具
  模擬（忽略補償），因為補償在固定循環中的路徑差異本身就是獨立的幾何
  課題（見手冊 4.1.5、4.2.1 刀尖半徑補償段落），優先度低於把循環本身跑對。

## 9. 視覺化

- `viz_matplotlib.py`：
  - 靜態圖：rapid（虛線）vs 切削進給（實線）vs 螺紋（另一顏色），ZX 平面。
  - 動畫：`FuncAnimation` 逐步顯示刀具目前位置。
- `export_json.py` + `web_viewer/`：
  - 匯出 `{moves: [...], meta: {...}}`
  - 網頁用 Canvas 畫出路徑，可拖曳時間軸單步檢視、hover 顯示對應原始
    程式行號（呼應 `source_line` 欄位，方便對照除錯）。

## 10. 測試策略

- **黃金測試（Golden tests）**：直接採用兩份手冊裡的官方範例程式與其
  說明圖形，例如：
  - `O9500`/`O0001` 求1~10之和（宏程序範例，驗證變量/WHILE正確性，
    結果必須是55）
  - G71 類型I/II 範例、G73 範例（φ180 外徑範例）、G76 範例
    （`G76 P021260 Q100 R100; G76 X.. Z.. R.. P.. Q.. F..;`）
  這些程式在手冊中有預期的刀具路徑圖，可用來驗證關鍵點座標。
- 每個模組獨立單元測試（表達式優先序、空值語意真值表、WHILE巢狀規則、
  G65自變量對應表）。
- 不追求 100% 複製真機報警行為，但對手冊明確列出的「非法用法」
  （如巢狀超過3層、GOTO轉移進迴圈體內、槽孔缺 W0 指令等）至少要能
  偵測並拋出清楚錯誤，不要靜默出錯。

## 11. 分階段路線圖（Roadmap）

- **Phase 0** 專案骨架：lexer + 純 NC 語句 parser（不含宏）+ G00/G01/G02/G03
  插補 + **G50 座標設定** + 最小 `ToolTable`（先允許留白）+ matplotlib
  靜態繪圖。`Move` dataclass 從此階段就加入 `programmed_end` 欄位（先恆
  等於 `end`），為 Phase 4.5 預留擴充空間。用 `examples/01_basic_line_arc.nc`
  驗證。
- **Phase 1** 變量系統 + 表達式求值 + 賦值語句 + GOTO/IF/WHILE +
  **M98 子程式調用**（不傳自變量，堆疊≤10層）
  （先不含 G65，用直接賦值公共變量測試控制流）。
- **Phase 2** G65 宏調用（自變量傳遞、局部變量frame、調用堆疊、巢狀限制，
  與 M98 共用 call stack 但分開計數，合計≤15層）。
  用 `examples/02_macro_sum.nc` 驗證。
- **Phase 3** 單一型固定循環 G90/G92/G94、G32（含多線螺紋 Q）。
- **Phase 4** 複合型固定循環，依第7節建議順序逐一實作（G71→G70→G72→
  G73→G76→G74/G75）。G76 的 `P(m)(r)(a)` 位數編碼解析需獨立單元測試。
- **Phase 4.5** 刀尖半徑補償（G41/G42）整合進固定循環與一般插補路徑，
  含循環起點偏置取消/重新起刀的時機處理（見第13節第4點）。
- **Phase 5** 網頁互動 viewer（JSON匯出 + Canvas）、動畫。
- **Phase 6**（stretch）庫存材料切削模擬（stock removal，多邊形布林運算
  視覺化材料被切除的過程）。

## 12. 開放問題與決議

1. **系統變量支援範圍** → 採建議：先做最小集合（僅座標位置回讀，如
   `#5001~#5006`），刀具偏置（#2001+）、工件座標系（#5201+）等之後依實際
   測試程式需求再擴充，並持續更新 `docs/variables.md` 標註「已支援／
   尚未支援」清單。
2. **報警碼重現程度** → 採一般訊息：模擬器拋出的是一般 Python 例外
   （如 `MacroError`、`CannedCycleError`），訊息內容可在括號中附註對應
   手冊報警碼（例如「(cf. PS0064) 精車形狀不是單調變化」）方便對照手冊
   除錯，但不模擬真實的報警狀態機（無需 alarm reset、SRVO 類報警等）。
3. **刀尖半徑補償（G41/G42）優先度** → 採建議：從 Phase 6 提前到
   Phase 4 之後、Phase 5（網頁互動視覺化）之前，獨立為 **Phase 4.5**。
   因為這不是「加一個模組」而已，會回頭影響每個固定循環的路徑計算方式
   （見下方第13節第4點），所以提前排定也代表 Phase 0 的資料結構需要
   提前預留擴充空間，避免 Phase 4.5 變成大改。

## 13. 補充注意事項（規劃反思）

規劃初稿之外，重新檢視兩份手冊後，以下幾點容易被忽略、但會直接影響
「能不能正確重現手冊範例程式」，特別列出：

1. **G50 座標系設定指令必須支援，且要區分兩種語意**。`G50` 為車床專用
   指令，依位址不同分成兩種完全不同功能（已確認並補上規格原文）：
   - `G50 IP_;`（`G50 X_ Z_;`）— Coordinate system setting：不是移動
     指令，而是「宣告目前刀具實際所在位置的座標值」。手冊幾乎所有範例
     程式開頭都有 `G50 X220.0 Z190.0;` 這類指令，若不支援，所有黃金
     測試範例的起始座標都會算錯。**排入 Phase 0**（與 G00/G01 插補一起
     做）。
   - `G50 S_;` — Maximum spindle speed clamp：設定恆線速度控制
     （G96）下的主軸最高轉速上限，純中繼資料、不影響路徑幾何，歸入
     第7點一起處理，Phase 0 只需能解析、不報錯即可，不強制模擬轉速
     鉗制邏輯。
   - parser 需依同一程式段內出現的位址（X/Z vs S）分派到對應處理邏輯，
     兩者可能同時出現在同一行。

2. **M98 子程式調用列為 Phase 1 就要支援的第一級功能**，不要只做 G65。
   手冊 16.7 節明確把「宏調用（G65/G66/G66.1/G67，可傳自變量）」與
   「子程式調用（M98/M代碼/T代碼/S代碼調用，不可傳自變量）」分成兩類。
   許多實務程式只用 M98 做單純重複（例如同一輪廓車削N刀），沒有用到
   變量，若只做 G65 會漏掉一大類常見程式。子程式調用堆疊（≤10層）與
   宏調用堆疊（≤5層，合計≤15層）需要分開計數但共用同一個
   call stack 機制。

3. **T 代碼與最小刀具表**。範例程式中的 `T0101`（刀號01、補正號01）
   目前規劃只當作中繼資料記錄，不影響路徑。但因為刀尖半徑補償
   （G41/G42）提前到 Phase 4.5，屆時「刀尖半徑」勢必要來自某個刀具定義，
   所以 Phase 0 就應該先建立一個簡單的 `ToolTable`（刀號 → 補正號 →
   刀尖半徑/假想刀尖方向，先允許全部留白/預設0），避免 Phase 4.5 時
   又要回頭改資料結構。

4. **刀尖半徑補償提前後，資料結構要預留「程式路徑」與「補償後路徑」
   分離存放**。手冊 4.1.5、4.2.1 節說明固定循環搭配 G41/G42 時，偏置
   在循環起點會暫時取消、在下一個移動指令才重新起刀，且刀尖中心路徑
   與編程路徑不同（見刀尖半徑中心路徑圖）。若 `Move`/`Toolpath` 一開始
   沒有把「編程座標」與「刀尖中心座標」分開存，Phase 4.5 要疊加補償時
   會被迫大改第7、8節已完成的固定循環模組。因此第8節的 `Move` dataclass
   建議從 Phase 0 就加上 `programmed_end: tuple | None` 欄位（先恆等於
   `end`），Phase 4.5 再讓補償計算填入真正偏移後的 `end`。

5. **明確排除的行為（非路徑幾何，屬即時操作員介入）**：單程序段停止、
   進給暫停（feed hold）、螺紋切削循環收回功能（4.1.2節「帶有螺紋切削
   循環收回功能時...」）、手動干預（4.1.6節）。這些都是「操作中」的
   即時行為，模擬器是離線跑完整支程式，不存在操作員暫停，因此**明確
   不模擬**，並在 `docs/variables.md` 或程式碼註解中寫清楚原因，避免
   日後被誤認為遺漏。

6. **G76 的 `P(m)(r)(a)` 是位數編碼，不是一般數值**，例如
   `P021260` = m=02（最終精加工重複次數）、r=12（螺紋倒角量，
   1.2L）、a=60（刀尖角度60°），要用固定位數切割（2+2+2位）解析，
   而非當成單一數字使用。這是解析階段容易犯錯的地方，需要在
   `parser.py`／`threading.py` 加專門的單元測試覆蓋（含 `m,r,a` 用參數
   預設值省略指定的情形）。

7. **記錄但不影響路徑幾何的模態資訊**：`G96/G97`（恆線速度/恆轉速）、
   `G98/G99`（每分鐘進給/每轉進給）、`G20/G21`（英制/公制）。這些會
   影響動畫播放的時間感、單位換算，但不改變刀具路徑的幾何形狀。
   規劃上把它們存成 `Move` 或 `Toolpath` 的中繼資料（`feed_mode`、
   `spindle_mode`、`unit`），供視覺化/動畫使用，但不參與路徑計算，
   並在文件中明講「有記錄、不影響幾何」，避免被誤以為完全忽略。

8. **可選程序段跳過 `/`（block skip）先做成可關閉的設定**，預設不跳過
   （即完整模擬全部程式），因為手冊提到 `/n`（n=1~9）不可作為變量使用，
   代表這是獨立語法元素，需要 lexer 層識別但預設不啟用跳過行為。

9. **OCR 文字需要與原圖交叉確認**。兩份手冊是透過 PDF 頁面轉文字/圖片
   取得，部份參數預設值、範圍數字（例如報警碼、參數編號）在撰寫
   `grammar.md`、`variables.md` 時建議保留「見手冊原圖第X頁」的註記，
   而不是完全依賴已抄錄的文字，降低謄寫誤差風險。

---

以上為架構規劃，尚未動手寫程式碼。待你確認本次補充後，下一步將依
第11節路線圖從 Phase 0 開始實作（含本次新增的 G50、M98、ToolTable
雛形）。
