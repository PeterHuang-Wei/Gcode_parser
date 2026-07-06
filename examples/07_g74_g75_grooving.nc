O0004 (COMPOUND CANNED CYCLES: G74 FACE PECK DRILLING, G75 OD GROOVING, PHASE 4) ;
G50 X44.0 Z2.0 ;

(-- G74: three face holes, Delta i=6.0 X shift, Delta k=4.0 Z peck, e=0.3 --) ;
G74 R0.3 ;
G74 X10.0 Z-12.0 P6.0 Q4.0 F0.15 ;

(-- reposition before the G75 groove --) ;
G00 X44.0 Z-30.0 ;

(-- G75: two OD grooves, Delta i=3.0 X peck, Delta k=5.0 Z shift, e=0.3 --) ;
G75 R0.3 ;
G75 X24.0 Z-40.0 P3.0 Q5.0 F0.15 ;

G00 X44.0 Z2.0 ;
M30 ;
