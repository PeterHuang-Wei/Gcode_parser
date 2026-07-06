O0001 (SINGLE-FORM CANNED CYCLES: G32/G90/G92/G94, PHASE 3) ;
G50 X50.0 Z100.0 ;

(-- G90: straight turning cycle, two passes via modal X carry --) ;
G90 X30.0 Z50.0 F0.3 ;
X20.0 ;

(-- G94: straight facing cycle --) ;
G94 X10.0 Z80.0 F0.2 ;

(-- G92: straight thread cutting cycle --) ;
G92 X30.0 Z50.0 F2.0 ;

M30 ;
