O0003 (COMPOUND CANNED CYCLES: G73 PATTERN REPEAT + G70 FINISHING, PHASE 4) ;
G50 X44.0 Z2.0 ;

(-- G73: rough a pre-formed stepped shaft in 4 parallel-offset passes,   --) ;
(-- retreating a total of Delta i=6.0 X / Delta k=3.0 Z, leaving         --) ;
(-- Delta u=1.0 diameter / Delta w=0.5 finishing stock                   --) ;
G73 U6.0 W3.0 R4 ;
G73 P10 Q60 U1.0 W0.5 F0.2 ;
N10 G00 X10.0 ;
N20 G01 Z-10.0 F0.15 ;
N30 X20.0 Z-20.0 ;
N40 Z-30.0 ;
N50 X30.0 Z-40.0 ;
N60 Z-50.0 ;

(-- G70: re-run N10..N60 for the real finishing pass --) ;
G70 P10 Q60 ;

G00 X44.0 Z2.0 ;
M30 ;
