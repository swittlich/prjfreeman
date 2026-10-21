// SPDX-License-Identifier: ISC
// Copyright (C) 2026 Sebastian Wittlich
// Techmap from yosys-internal cells to the primitives of the XC2064 model.

// $lut (from "abc -lut 3:4") -> XC2000_LUT3 (F or G) or XC2000_LUT4 (F and G together).
// Smaller functions are replicated in INIT so that the open inputs have no influence.
module \$lut (A, Y);
	parameter WIDTH = 0;
	parameter LUT = 0;

	(* force_downto *)
	input [WIDTH-1:0] A;
	output Y;

	generate
		if (WIDTH == 1) begin
			XC2000_LUT3 #(.INIT({4{LUT[1:0]}})) _TECHMAP_REPLACE_ (.I({2'bxx, A}), .O(Y));
		end else if (WIDTH == 2) begin
			XC2000_LUT3 #(.INIT({2{LUT[3:0]}})) _TECHMAP_REPLACE_ (.I({1'bx, A}), .O(Y));
		end else if (WIDTH == 3) begin
			XC2000_LUT3 #(.INIT(LUT[7:0])) _TECHMAP_REPLACE_ (.I(A), .O(Y));
		end else if (WIDTH == 4) begin
			XC2000_LUT4 #(.INIT(LUT[15:0])) _TECHMAP_REPLACE_ (.I(A), .O(Y));
		end else begin
			wire _TECHMAP_FAIL_ = 1;
		end
	endgenerate
endmodule

// Storage elements (after dfflegalize) -> XC2000_DFF with LATCH/CLKINV. Constantly inactive set/reset inputs
// stay open so that they do not occupy any of the CLB inputs.
module \$_DFF_P_ (input C, input D, output Q);
	XC2000_DFF #(.LATCH(0), .CLKINV(0)) _TECHMAP_REPLACE_ (.CLK(C), .D(D), .Q(Q));
endmodule

module \$_DFF_N_ (input C, input D, output Q);
	XC2000_DFF #(.LATCH(0), .CLKINV(1)) _TECHMAP_REPLACE_ (.CLK(C), .D(D), .Q(Q));
endmodule

module \$_DLATCH_P_ (input E, input D, output Q);
	XC2000_DFF #(.LATCH(1), .CLKINV(0)) _TECHMAP_REPLACE_ (.CLK(E), .D(D), .Q(Q));
endmodule

module \$_DLATCH_N_ (input E, input D, output Q);
	XC2000_DFF #(.LATCH(1), .CLKINV(1)) _TECHMAP_REPLACE_ (.CLK(E), .D(D), .Q(Q));
endmodule

module \$_DFFSR_PPP_ (input C, input S, input R, input D, output Q);
	parameter _TECHMAP_CONSTMSK_S_ = 0;
	parameter _TECHMAP_CONSTVAL_S_ = 0;
	parameter _TECHMAP_CONSTMSK_R_ = 0;
	parameter _TECHMAP_CONSTVAL_R_ = 0;
	wire s = (_TECHMAP_CONSTMSK_S_ && !_TECHMAP_CONSTVAL_S_) ? 1'bx : S;
	wire r = (_TECHMAP_CONSTMSK_R_ && !_TECHMAP_CONSTVAL_R_) ? 1'bx : R;
	XC2000_DFF #(.LATCH(0), .CLKINV(0)) _TECHMAP_REPLACE_ (.CLK(C), .D(D), .S(s), .R(r), .Q(Q));
endmodule

module \$_DFFSR_NPP_ (input C, input S, input R, input D, output Q);
	parameter _TECHMAP_CONSTMSK_S_ = 0;
	parameter _TECHMAP_CONSTVAL_S_ = 0;
	parameter _TECHMAP_CONSTMSK_R_ = 0;
	parameter _TECHMAP_CONSTVAL_R_ = 0;
	wire s = (_TECHMAP_CONSTMSK_S_ && !_TECHMAP_CONSTVAL_S_) ? 1'bx : S;
	wire r = (_TECHMAP_CONSTMSK_R_ && !_TECHMAP_CONSTVAL_R_) ? 1'bx : R;
	XC2000_DFF #(.LATCH(0), .CLKINV(1)) _TECHMAP_REPLACE_ (.CLK(C), .D(D), .S(s), .R(r), .Q(Q));
endmodule

module \$_DLATCHSR_PPP_ (input E, input S, input R, input D, output Q);
	parameter _TECHMAP_CONSTMSK_S_ = 0;
	parameter _TECHMAP_CONSTVAL_S_ = 0;
	parameter _TECHMAP_CONSTMSK_R_ = 0;
	parameter _TECHMAP_CONSTVAL_R_ = 0;
	wire s = (_TECHMAP_CONSTMSK_S_ && !_TECHMAP_CONSTVAL_S_) ? 1'bx : S;
	wire r = (_TECHMAP_CONSTMSK_R_ && !_TECHMAP_CONSTVAL_R_) ? 1'bx : R;
	XC2000_DFF #(.LATCH(1), .CLKINV(0)) _TECHMAP_REPLACE_ (.CLK(E), .D(D), .S(s), .R(r), .Q(Q));
endmodule

module \$_DLATCHSR_NPP_ (input E, input S, input R, input D, output Q);
	parameter _TECHMAP_CONSTMSK_S_ = 0;
	parameter _TECHMAP_CONSTVAL_S_ = 0;
	parameter _TECHMAP_CONSTMSK_R_ = 0;
	parameter _TECHMAP_CONSTVAL_R_ = 0;
	wire s = (_TECHMAP_CONSTMSK_S_ && !_TECHMAP_CONSTVAL_S_) ? 1'bx : S;
	wire r = (_TECHMAP_CONSTMSK_R_ && !_TECHMAP_CONSTVAL_R_) ? 1'bx : R;
	XC2000_DFF #(.LATCH(1), .CLKINV(1)) _TECHMAP_REPLACE_ (.CLK(E), .D(D), .S(s), .R(r), .Q(Q));
endmodule
