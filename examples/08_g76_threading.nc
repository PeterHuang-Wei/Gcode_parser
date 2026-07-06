O0005 (COMPOUND CANNED CYCLE: G76 THREADING, PHASE 4) ;
G50 X44.0 Z2.0 ;

(-- G76: straight thread, k=2.0 thread height, Delta d=0.5 first cut,   --) ;
(-- Delta dmin=0.1, finish allowance d=0.2, m=2 finish repeat passes    --) ;
G76 P020000 Q0.1 R0.2 ;
G76 X40.0 Z-30.0 R0 P2.0 Q0.5 F2.0 ;

G00 X44.0 Z2.0 ;
M30 ;
