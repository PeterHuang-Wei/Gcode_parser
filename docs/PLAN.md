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
    interpreter.py         # 主執行迴圈：模態狀態、控制流、宏調用堆疊
    canned_cycles/
      __init__.py
      turning.py          # G90（外/內徑車削）、G94（端面車削）
      threading.py        # G32、G92（螺紋切削循環）、G76（複合型螺紋）
      roughing.py         # G71、G72（外徑/端面粗車，類型I/II）
      pattern_repeat.py    # G73（閉環/仿形粗車）
      finishing.py         # G70（精車）
      grooving.py          # G74、G75（端面/外徑切斷、切槽、深孔鑽）
    motion.py             # 直線/圓弧插補的幾何運算（點列生成）
    toolpath.py            # Move / Toolpath 資料結構
    simulator.py           # 串接 interpreter → canned_cycles → toolpath
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
    start: tuple[float, float]   # (Z, X) 依手冊慣例 X 為直徑值
    end: tuple[float, float]
    feed: float | None
    spindle: float | None
    arc_center: tuple[float, float] | None = None
    arc_ccw: bool | None = None
    source_line: int | None = None   # 對應原始程式行號，方便除錯
    cycle: str | None = None         # 產生此移動的固定循環名稱（若有）

@dataclass
class Toolpath:
    moves: list[Move]
    diameter_programming: bool = True  # X 為直徑值（手冊預設）
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
  插補 + matplotlib 靜態繪圖。用 `examples/01_basic_line_arc.nc` 驗證。
- **Phase 1** 變量系統 + 表達式求值 + 賦值語句 + GOTO/IF/WHILE
  （先不含 G65，用直接賦值公共變量測試控制流）。
- **Phase 2** G65 宏調用（自變量傳遞、局部變量frame、調用堆疊、巢狀限制）。
  用 `examples/02_macro_sum.nc` 驗證。
- **Phase 3** 單一型固定循環 G90/G92/G94、G32（含多線螺紋 Q）。
- **Phase 4** 複合型固定循環，依第7節建議順序逐一實作（G71→G70→G72→
  G73→G76→G74/G75）。
- **Phase 5** 網頁互動 viewer（JSON匯出 + Canvas）、動畫。
- **Phase 6**（stretch）刀尖半徑補償整合、庫存材料切削模擬（stock removal，
  多邊形布林運算視覺化材料被切除的過程）。

## 12. 待確認的開放問題

1. **系統變量支援範圍**：模擬用途下，是否需要支援刀具偏置（#2001+）、
   工件座標系（#5201+）等，或先只做位置回讀？→ 建議先做最小集合，
   之後依實際測試程式需求擴充。
2. **報警碼重現程度**：是否需要模擬器輸出對應真機的 PS0xxx 報警碼
   字串（教學用途可能有幫助），或只需一般 Python 例外訊息？
3. **刀尖半徑補償優先度**：若近期就有需要 G41/G42 準確路徑的程式要跑，
   建議提前到 Phase 4 之後、Phase 5 之前處理，而非放到 Phase 6。

---

以上為架構規劃，尚未動手寫程式碼。請確認方向或提出調整，之後再依此
文件逐階段實作。
